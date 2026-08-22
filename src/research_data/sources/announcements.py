"""NSE corporate announcements — the exchange dissemination feed.

WHY THIS IS THE MOST PIT-HONEST FEED NSE PUBLISHES
Every other dataset here is dated by the event; this one is dated by the
*disclosure*. Each record carries the time the company filed, the time the
exchange received it and the time the exchange disseminated it, so the moment
the market could first know is in the data rather than being assumed. For a
lab whose characteristic failure is lookahead (`AGENTS.md`), that is worth
more than the announcement text.

    /api/corporate-announcements?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY

MEASURED BEHAVIOUR, 2026-08-22
  * **No row cap.** Two single-day requests returned 574 and 602 records; the
    two-day request covering both returned exactly 1,176. That equality is the
    check worth keeping — it is what the deals endpoint fails.
  * **Depth**: records exist from 2003, thin until 2005, dense from then on.
  * **The timestamps are date-only before ~2008.** Every 2005 record carries
    `an_dt` at 00:00:00; by 2008 real intraday times are present throughout.
    A midnight timestamp does not mean the market knew at midnight — it means
    the time was not recorded. Treating it as 00:00:00 hands an experiment a
    full day of lookahead on every pre-2008 announcement, so the era is
    flagged here (`time_known`) and resolved in `pipelines/events.py`.
  * Volume is heavy — roughly 600 records a day, ~1.2 MB of JSON for three
    days — so the feed is fetched in monthly chunks and cached.

WHAT THIS IS NOT
This module collects and timestamps announcements. It does not read them.
`desc` is a coarse NSE-assigned subject and `attchmntText` is a one-line
human summary; the substance is in the linked PDF. Extracting signal from that
corpus is a separate problem, and a much harder one than collecting it.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from . import nse_api

ANN_URL = f"{nse_api.BASE}/api/corporate-announcements"

# The archive holds a handful of 2003-2004 records; density arrives with 2005.
FIRST_DATE = date(2003, 1, 1)

FIELD_MAP = {
    "symbol": "symbol",
    "sm_name": "company",
    "sm_isin": "isin",
    "smIndustry": "industry",
    "desc": "subject",
    "attchmntText": "details",
    "attchmntFile": "attachment_url",
    "fileSize": "attachment_size",
    "an_dt": "broadcast_at",
    "exchdisstime": "disseminated_at",
    "difference": "dissemination_lag",
    "seq_id": "seq_id",
    "hasXbrl": "has_xbrl",
}

COLUMNS = ["symbol", "company", "isin", "industry", "subject", "details",
           "broadcast_at", "disseminated_at", "dissemination_lag",
           "time_known", "attachment_url", "attachment_size", "seq_id",
           "has_xbrl"]

_TS_FORMATS = ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y")


def _timestamp(s: pd.Series) -> pd.Series:
    """Parse NSE's several timestamp spellings without silently inventing one.

    `pd.to_datetime(..., errors="coerce")` on a mixed column will happily read
    "20-Aug-2026" as midnight, which is correct here only because the caller
    is told about it through `time_known`. The formats are tried strictly, in
    order, so a genuinely unparseable value stays NaT rather than being
    guessed at by dateutil.
    """
    s = s.astype(str).str.strip()
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    for fmt in _TS_FORMATS:
        todo = out.isna()
        if not todo.any():
            break
        out[todo] = pd.to_datetime(s[todo], format=fmt, errors="coerce")
    return out


def _chunk_months(start: date, end: date):
    """Yield calendar-month [from, to] windows. ~600 records/day is a lot."""
    cur = start.replace(day=1)
    while cur <= end:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield max(cur, start), min(nxt - timedelta(days=1), end)
        cur = nxt


def parse(records: list[dict]) -> pd.DataFrame:
    """Normalise the announcement feed, preserving the disclosure timestamps.

    `time_known` is False where the source recorded a date but no time. The
    distinction cannot be recovered later: once a midnight timestamp is in a
    parquet file it is indistinguishable from a genuine 00:00 filing, of which
    there are real ones (NSE's own overnight batch disseminates at 00:00:04).
    """
    if not records:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(records)
    df = df.rename(columns={k: v for k, v in FIELD_MAP.items() if k in df.columns})
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    df["broadcast_at"] = _timestamp(df["broadcast_at"])
    df["disseminated_at"] = _timestamp(df["disseminated_at"])
    df["time_known"] = nse_api.time_is_known(df["broadcast_at"],
                                             df["disseminated_at"])

    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    for c in ("company", "isin", "industry", "subject", "details",
              "attachment_url", "attachment_size", "dissemination_lag"):
        df[c] = (df[c].astype(str).str.strip()
                 .replace({"-": pd.NA, "nan": pd.NA, "None": pd.NA, "": pd.NA}))
    df["has_xbrl"] = df["has_xbrl"].fillna(False).astype(bool)
    df["seq_id"] = df["seq_id"].astype(str).str.strip()
    df = df[df["broadcast_at"].notna()]
    return df[COLUMNS].reset_index(drop=True)


def fetch_window(client: nse_api.Client, start: date, end: date, *,
                 force: bool = False) -> pd.DataFrame:
    path = (nse_api.raw_dir("announcements")
            / f"{start.isoformat()}_{end.isoformat()}.json")
    body = client.get_cached(
        path, ANN_URL,
        {"index": "equities",
         "from_date": start.strftime("%d-%m-%Y"),
         "to_date": end.strftime("%d-%m-%Y")},
        want="json", force=force)
    return parse(nse_api.decode_json(body))


def sync(start: date | None = None, end: date | None = None, *,
         throttle: float = 1.5, force: bool = False,
         verbose: bool = True) -> dict:
    """Download the announcement feed month by month into data/raw."""
    start = start or FIRST_DATE
    end = end or date.today()
    client = nse_api.Client(area="announcements", throttle=throttle)
    rows, windows, empty = 0, 0, 0
    for a, b in _chunk_months(start, end):
        df = fetch_window(client, a, b, force=force)
        windows += 1
        rows += len(df)
        if df.empty:
            empty += 1
        elif verbose:
            no_time = int((~df["time_known"]).sum())
            print(f"  announcements {a:%Y-%m}: {len(df):6,} rows"
                  + (f"  ({no_time:,} without a time)" if no_time else ""),
                  flush=True)
    return {"windows": windows, "rows": rows, "empty_windows": empty,
            "first": start.isoformat(), "last": end.isoformat()}


def load(start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """Read every cached month back as one frame.

    Deduplication is on `seq_id`, NSE's own record identifier, so a re-synced
    or overlapping month cannot double-count. Where `seq_id` is absent — the
    early era leaves it null — the whole record is compared instead.
    """
    frames = []
    for f in sorted(nse_api.raw_dir("announcements").glob("*.json")):
        df = parse(nse_api.decode_json(f.read_bytes()))
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    has_id = out["seq_id"].notna() & (out["seq_id"].astype(str) != "nan")
    out = pd.concat([out[has_id].drop_duplicates(subset=["seq_id"]),
                     out[~has_id].drop_duplicates()], ignore_index=True)
    if start is not None:
        out = out[out["broadcast_at"] >= pd.Timestamp(start)]
    if end is not None:
        out = out[out["broadcast_at"] <= pd.Timestamp(end) + pd.Timedelta(days=1)]
    return out.sort_values(["broadcast_at", "symbol"]).reset_index(drop=True)


__all__ = ["ANN_URL", "COLUMNS", "FIRST_DATE", "fetch_window", "load", "parse", "sync"]
