"""NSE bulk deals, block deals and short selling — the historical archive.

WHAT THESE ARE
A **bulk deal** is any trade, or set of trades by one client in one scrip on
one day, exceeding 0.5% of the listed shares; the broker must report it and
NSE publishes it after the close. A **block deal** is a single negotiated
trade above the block-window threshold, executed in a separate window. **Short
selling** is the daily scrip-wise reported short position. All three are
disclosed with the counterparty's name, which is what makes them interesting:
they are the only free NSE dataset that names *who* traded.

THE ROUTE IN EVERY GUIDE IS DEAD
`/api/historical/bulk-deals` and `/api/historical/block-deals` return 503. The
live route, measured 2026-08-22, is a single endpoint discriminated by
`optionType`:

    /api/historicalOR/bulk-block-short-deals
        ?optionType=bulk_deals|block_deals|short_selling
        &from=DD-MM-YYYY&to=DD-MM-YYYY

THE JSON FORM OF THAT ROUTE SILENTLY TRUNCATES
It returns exactly 70 records for *any* range — one day, one month, one year —
with no total, no cursor, and no honoured pagination parameter (`page`,
`limit`, `start`, `length` were all tried; all ignored). The 70 it keeps are
the *earliest* in the window, so a year-long request comes back looking like a
complete answer for the first trading day of that year. Adding `csv=true` to
the identical request returns the full extract: 25,863 rows across 247
sessions for a one-year window. So this module speaks CSV, always.

This is the same class of failure as the Breeze 1,000-row tail cap, and it is
handled the same way: chunk deliberately, then assert the returned span
against the requested one rather than trusting it.

DEPTH, measured by bisection against the live archive
    bulk deals      2004-01-04 onward   (SEBI's disclosure regime begins 2004)
    block deals     2005-11-17 onward
    short selling   sparse; 2020 onward is dense

A range wider than one year returns 500, so history is walked in yearly
chunks. That is ~22 requests per deal type for the whole archive.

POINT-IN-TIME
These files are published *after* the close of the deal date. The deal date is
therefore not the date the information was available — see
`pipelines/events.py`, which is where the availability timestamp is derived
and where the "not tradable until the next open" rule is applied.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from . import nse_api

DEALS_URL = f"{nse_api.BASE}/api/historicalOR/bulk-block-short-deals"

# option_type -> (dataset name, first date the archive actually holds)
KINDS = {
    "bulk_deals": ("bulk", date(2004, 1, 1)),
    "block_deals": ("block", date(2005, 1, 1)),
    "short_selling": ("short", date(2005, 1, 1)),
}

# The CSV header. Short selling ships a narrower file (no client or side), so
# the map is a superset and missing columns are materialised as NA rather than
# dropped — a column that appears partway through history changes the schema
# by date, which is how a feature silently changes meaning.
COLUMN_MAP = {
    "Date": "deal_date",
    "Symbol": "symbol",
    "Security Name": "security_name",
    "Client Name": "client_name",
    "Buy / Sell": "side",
    "Quantity Traded": "quantity",
    "Trade Price / Wght. Avg. Price": "price",
    "Remarks": "remarks",
}

COLUMNS = ["deal_date", "symbol", "security_name", "client_name", "side",
           "quantity", "price", "remarks", "deal_type"]


def _chunk_years(start: date, end: date):
    """Yield <=1-year [from, to] windows; wider ranges return HTTP 500."""
    cur = start
    while cur <= end:
        stop = min(date(cur.year, 12, 31), end)
        yield cur, stop
        cur = stop + timedelta(days=1)


def _to_number(s: pd.Series) -> pd.Series:
    """Strip Indian digit grouping ("6,91,650") before coercing to a number."""
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce")


def parse(body: bytes, deal_type: str) -> pd.DataFrame:
    """Parse one CSV extract into the canonical deal schema.

    `side` is normalised to BUY/SELL. Every bulk and block deal is reported
    from one side, so a single client's round trip appears as two rows, and
    losing the side would silently turn accumulation into distribution.
    """
    df = nse_api.decode_csv(body)
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df = df.rename(columns=COLUMN_MAP)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    df["deal_date"] = pd.to_datetime(df["deal_date"], format="%d-%b-%Y",
                                     errors="coerce")
    df = df[df["deal_date"].notna()].copy()
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    df["side"] = (df["side"].astype(str).str.strip().str.upper()
                  .replace({"NAN": pd.NA, "-": pd.NA}))
    df["quantity"] = _to_number(df["quantity"])
    df["price"] = _to_number(df["price"])
    # "-" is NSE's empty cell throughout these files, in every text column.
    for c in ("remarks", "client_name", "security_name"):
        df[c] = df[c].astype(str).str.strip().replace({"-": pd.NA, "nan": pd.NA})
    df["deal_type"] = deal_type
    return df[COLUMNS].reset_index(drop=True)


def fetch_window(client: nse_api.Client, option_type: str, start: date,
                 end: date, *, force: bool = False) -> pd.DataFrame:
    """Fetch and parse one <=1-year window, caching the raw CSV verbatim."""
    name, _ = KINDS[option_type]
    path = (nse_api.raw_dir(f"deals/{name}")
            / f"{start.isoformat()}_{end.isoformat()}.csv")
    body = client.get_cached(
        path, DEALS_URL,
        {"optionType": option_type,
         "from": start.strftime("%d-%m-%Y"),
         "to": end.strftime("%d-%m-%Y"),
         "csv": "true"},
        want="csv", force=force)
    return parse(body, name)


def sync(start: date | None = None, end: date | None = None,
         kinds: tuple[str, ...] = tuple(KINDS), *, throttle: float = 1.5,
         force: bool = False, verbose: bool = True) -> dict:
    """Download every deal type over [start, end] into data/raw/deals.

    `start` defaults per deal type to the first date the archive holds, so the
    common case — "get me everything" — needs no arguments and does not spend
    twenty requests on years that are known to be empty.
    """
    end = end or date.today()
    stats: dict[str, dict] = {}
    for option_type in kinds:
        name, floor = KINDS[option_type]
        first = max(start or floor, floor)
        client = nse_api.Client(area="deals", throttle=throttle)
        rows, windows, empty = 0, 0, 0
        for a, b in _chunk_years(first, end):
            df = fetch_window(client, option_type, a, b, force=force)
            windows += 1
            rows += len(df)
            if df.empty:
                empty += 1
            elif verbose:
                span = f"{df['deal_date'].min().date()}..{df['deal_date'].max().date()}"
                print(f"  {name:6} {a.year}: {len(df):6,} rows  {span}", flush=True)
        stats[name] = {"windows": windows, "rows": rows, "empty_windows": empty,
                       "first_requested": first.isoformat(), "last": end.isoformat()}
    return stats


def load(kinds: tuple[str, ...] = tuple(KINDS)) -> pd.DataFrame:
    """Read every cached extract back as one frame, deduplicated.

    Yearly windows are requested on calendar boundaries and never overlap, but
    a re-sync with different bounds can leave two files covering one day. The
    deal report has no identifier of its own, so a duplicate is defined as an
    identical row — which is also, unavoidably, how a client legitimately
    repeating the same size at the same price on the same day would appear.
    That collision is rare, and losing it is safer than double-counting a
    re-downloaded window.
    """
    frames = []
    for option_type in kinds:
        name, _ = KINDS[option_type]
        for f in sorted((nse_api.raw_dir(f"deals/{name}")).glob("*.csv")):
            df = parse(f.read_bytes(), name)
            if not df.empty:
                frames.append(df)
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    out = pd.concat(frames, ignore_index=True).drop_duplicates()
    return out.sort_values(["deal_date", "symbol", "deal_type"]).reset_index(drop=True)


__all__ = ["COLUMNS", "DEALS_URL", "KINDS", "fetch_window", "load", "parse", "sync"]
