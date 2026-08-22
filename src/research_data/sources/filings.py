"""NSE financial results — filing metadata, revisions, and the raw XBRL archive.

This is the earnings pipeline's collection half. It stops deliberately short
of normalising the numbers: what it guarantees is that for any (symbol,
period) you can say *when the market could first know*, *which version of the
answer it knew*, and *exactly which bytes said so*.

TWO REGIMES, AND THE SEAM BETWEEN THEM
NSE moved listed entities to Integrated Filing–Financial from 2025-04-01, and
the old endpoint did not migrate — it froze. Measured 2026-08-22:

    /api/corporates-financial-results?index=equities&symbol=X&period=Quarterly|Annual
        periods  2005-03-31 .. 2024-12-31
        broadcast 2007-07 .. 2025-01, then nothing. FROZEN.

    /api/integrated-filing-results?index=equities&symbol=X&period=Quarterly
        the post-2025-04-01 regime, `type` = "Integrated Filing- Financials"
        (governance filings share the endpoint and are dropped here)

Neither alone is the history. Both are fetched and unioned, and `regime`
records which one a row came from so a discontinuity at 2025-04-01 can be
seen rather than discovered.

THERE IS NO DATE-RANGE FORM
`from_date`/`to_date` on the results endpoint returns zero records — it is
per-symbol only. So a full backfill is one request per symbol per period type
per regime, not a date sweep. Against ~2,000 symbols that is ~8,000 requests:
hours at a polite throttle, and the reason `sync` takes a symbol list.

REVISIONS ARE REAL AND MUST NOT BE COLLAPSED
NSE requires a revised XBRL for mismatches, restatements and voluntary
revisions. Measured on five symbols: RELIANCE carries 6 periods with more than
one filing, SUZLON 8, INFY 4. `(symbol, period)` is therefore **not** a key.
Every filing is kept as its own row, `supersedes` links it to the version it
replaced, and `is_latest` marks the survivor. A backtest that wants "what was
known on date D" filters on `broadcast_at <= D` and takes the last one — which
is only possible because the superseded rows are still there.

The integrated regime states this outright (`type_Sub` = Original/Revised,
`revised_Date`, `revision_Remark`); the legacy regime does not, so revisions
there are inferred from repeated period keys, ordered by broadcast time.

BROADCAST TIMESTAMPS DO NOT COVER THE WHOLE HISTORY
Periods begin 2005-03-31 but the earliest broadcast timestamp is 2007-07. The
2005-2007 records were backfilled and carry no dissemination time. They are
kept, with `time_known=False`, and `pipelines/events.py` refuses to treat them
as intraday-available. Use `broadcast_at` as the availability timestamp; never
the period end.

THE RAW FILINGS ARE ARCHIVED, NOT LINKED
`archive_xbrl` stores each filing's bytes under their own SHA-256 and records
the hash on the metadata row. NSE rewrites and re-hosts; a URL captured today
is not a promise about tomorrow, and a restatement that quietly replaces a
file at the same URL would otherwise be invisible.
"""
from __future__ import annotations

import hashlib
from datetime import date

import pandas as pd

from . import nse_api

LEGACY_URL = f"{nse_api.BASE}/api/corporates-financial-results"
INTEGRATED_URL = f"{nse_api.BASE}/api/integrated-filing-results"

# The date the Integrated Filing regime took over. Rows either side of it come
# from different endpoints with different fields; this is the documented seam.
INTEGRATED_FROM = date(2025, 4, 1)

XBRL_DIR = "xbrl"

COLUMNS = [
    "filing_id", "symbol", "company", "isin",
    "period_start", "period_end", "result_type", "relating_to",
    "financial_year", "scope", "audited", "cumulative", "ind_as", "is_bank",
    "broadcast_at", "filed_at", "disseminated_at", "dissemination_lag",
    "time_known", "regime", "revision", "revised_at", "revision_remark",
    "seq_id", "xbrl_url", "ixbrl_url", "pdf_url",
]

_TS_FORMATS = ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y", "%d-%B-%Y")


def _timestamp(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip()
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    for fmt in _TS_FORMATS:
        todo = out.isna()
        if not todo.any():
            break
        out[todo] = pd.to_datetime(s[todo], format=fmt, errors="coerce")
    return out


def _date(s: pd.Series) -> pd.Series:
    """Dates arrive as both "31-Dec-2024" and "30-JUN-2026" across regimes."""
    s = s.astype(str).str.strip().str.title()
    return pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")


def _clean(s: pd.Series) -> pd.Series:
    return (s.astype(str).str.strip()
            .replace({"-": pd.NA, "nan": pd.NA, "None": pd.NA, "": pd.NA,
                      "null": pd.NA}))


def filing_id(symbol: str, period_end, scope: str, seq_id: str) -> str:
    """A stable id for one *version* of one filing.

    Keyed on the sequence number rather than the period, because two rows
    sharing (symbol, period, scope) is the normal case for a restatement and
    the whole point is to keep both.
    """
    raw = f"{symbol}|{period_end}|{scope}|{seq_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ------------------------------------------------------------ legacy regime

def parse_legacy(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(records)
    out = pd.DataFrame(index=df.index)
    out["symbol"] = _clean(df.get("symbol", pd.Series(pd.NA, index=df.index))).str.upper()
    out["company"] = _clean(df.get("companyName", pd.Series(pd.NA, index=df.index)))
    out["isin"] = _clean(df.get("isin", pd.Series(pd.NA, index=df.index)))
    out["period_start"] = _date(df.get("fromDate", pd.Series(pd.NA, index=df.index)))
    out["period_end"] = _date(df.get("toDate", pd.Series(pd.NA, index=df.index)))
    out["result_type"] = _clean(df.get("period", pd.Series(pd.NA, index=df.index))).str.lower()
    out["relating_to"] = _clean(df.get("relatingTo", pd.Series(pd.NA, index=df.index)))
    out["financial_year"] = _clean(df.get("financialYear", pd.Series(pd.NA, index=df.index)))
    out["scope"] = _clean(df.get("consolidated", pd.Series(pd.NA, index=df.index))).str.lower()
    out["audited"] = _clean(df.get("audited", pd.Series(pd.NA, index=df.index))).str.lower()
    out["cumulative"] = _clean(df.get("cumulative", pd.Series(pd.NA, index=df.index))).str.lower()
    out["ind_as"] = _clean(df.get("indAs", pd.Series(pd.NA, index=df.index)))
    # "bank" is NSE's flag for the banking taxonomy, which reports a different
    # set of line items entirely. Carrying it lets an XBRL consumer branch.
    out["is_bank"] = df.get("bank", pd.Series(pd.NA, index=df.index)).astype(str).str.upper().eq("B")

    out["broadcast_at"] = _timestamp(df.get("broadCastDate", pd.Series(pd.NA, index=df.index)))
    out["filed_at"] = _timestamp(df.get("filingDate", pd.Series(pd.NA, index=df.index)))
    out["disseminated_at"] = _timestamp(df.get("exchdisstime", pd.Series(pd.NA, index=df.index)))
    out["dissemination_lag"] = _clean(df.get("difference", pd.Series(pd.NA, index=df.index)))
    out["time_known"] = nse_api.time_is_known(out["broadcast_at"],
                                              out["disseminated_at"])

    out["regime"] = "legacy"
    # The legacy feed does not label revisions; they are inferred downstream
    # from repeated period keys, so nothing is asserted here.
    out["revision"] = pd.NA
    out["revised_at"] = pd.NaT
    out["revision_remark"] = pd.NA
    out["seq_id"] = _clean(df.get("seqNumber", pd.Series(pd.NA, index=df.index)))
    out["xbrl_url"] = _clean(df.get("xbrl", pd.Series(pd.NA, index=df.index)))
    out["ixbrl_url"] = pd.NA
    out["pdf_url"] = _clean(df.get("resultDetailedDataLink", pd.Series(pd.NA, index=df.index)))
    return _finish(out)


# -------------------------------------------------------- integrated regime

def parse_integrated(records: list[dict]) -> pd.DataFrame:
    """Parse the post-2025 feed, keeping only the financial filings.

    The endpoint serves governance filings from the same route. They carry no
    period and no financials, so including them would put rows in a results
    table that can never have a number attached.
    """
    if not records:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(records)
    kind = df.get("type", pd.Series("", index=df.index)).astype(str)
    df = df[kind.str.contains("Financial", case=False, na=False)].copy()
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df = df.reset_index(drop=True)

    out = pd.DataFrame(index=df.index)
    out["symbol"] = _clean(df.get("symbol", pd.Series(pd.NA, index=df.index))).str.upper()
    out["company"] = _clean(df.get("cmName", pd.Series(pd.NA, index=df.index)))
    out["isin"] = pd.NA
    # The integrated feed states only the quarter-end date; the period start
    # is not in the payload and is left missing rather than assumed to be the
    # quarter start, because half-yearly and annual filings share the field.
    out["period_start"] = pd.NaT
    out["period_end"] = _date(df.get("qe_Date", pd.Series(pd.NA, index=df.index)))
    out["result_type"] = "quarterly"
    out["relating_to"] = pd.NA
    out["financial_year"] = pd.NA
    out["scope"] = _clean(df.get("consolidated", pd.Series(pd.NA, index=df.index))).str.lower()
    out["audited"] = _clean(df.get("audited", pd.Series(pd.NA, index=df.index))).str.lower()
    out["cumulative"] = pd.NA
    out["ind_as"] = pd.NA
    out["is_bank"] = df.get("xbrl", pd.Series("", index=df.index)).astype(str).str.contains("BANKING")

    out["broadcast_at"] = _timestamp(df.get("broadcast_Date", pd.Series(pd.NA, index=df.index)))
    out["filed_at"] = _timestamp(df.get("creation_Date", pd.Series(pd.NA, index=df.index)))
    out["disseminated_at"] = _timestamp(df.get("creation_Date", pd.Series(pd.NA, index=df.index)))
    out["dissemination_lag"] = _clean(df.get("diff", pd.Series(pd.NA, index=df.index)))
    out["time_known"] = nse_api.time_is_known(out["broadcast_at"],
                                              out["disseminated_at"])

    out["regime"] = "integrated"
    out["revision"] = _clean(df.get("type_Sub", pd.Series(pd.NA, index=df.index))).str.lower()
    out["revised_at"] = _timestamp(df.get("revised_Date", pd.Series(pd.NA, index=df.index)))
    out["revision_remark"] = _clean(df.get("revision_Remark", pd.Series(pd.NA, index=df.index)))
    out["seq_id"] = _clean(df.get("seq_Id", pd.Series(pd.NA, index=df.index)))
    out["xbrl_url"] = _clean(df.get("xbrl", pd.Series(pd.NA, index=df.index)))
    out["ixbrl_url"] = _clean(df.get("ixbrl", pd.Series(pd.NA, index=df.index)))
    pdf = _clean(df.get("pdf_attach", pd.Series(pd.NA, index=df.index)))
    # NSE renders a missing attachment as a URL ending in "/null".
    out["pdf_url"] = pdf.where(~pdf.fillna("").str.endswith("null"), pd.NA)
    return _finish(out)


def _finish(out: pd.DataFrame) -> pd.DataFrame:
    out = out[out["symbol"].notna() & out["period_end"].notna()].copy()
    out["scope"] = out["scope"].replace({"non-consolidated": "standalone"})
    out["filing_id"] = [
        filing_id(r.symbol, r.period_end, str(r.scope), str(r.seq_id))
        for r in out.itertuples()
    ]
    return out[COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------- revisions

def mark_revisions(df: pd.DataFrame) -> pd.DataFrame:
    """Order filings within a period and link each to the one it supersedes.

    The key is (symbol, period_end, scope, result_type) and the order is
    `broadcast_at`. `revision_number` counts from 0 for the original, and
    `is_latest` marks the version a "current fundamentals" view would use —
    which is exactly the view a backtest must not use, so it is a column
    rather than a filter.
    """
    if df.empty:
        out = df.copy()
        for c, v in (("revision_number", 0), ("is_latest", True),
                     ("supersedes", pd.NA)):
            out[c] = v
        return out
    key = ["symbol", "period_end", "scope", "result_type"]
    out = df.sort_values(key + ["broadcast_at", "seq_id"]).reset_index(drop=True)
    grp = out.groupby(key, dropna=False)
    out["revision_number"] = grp.cumcount()
    out["supersedes"] = grp["filing_id"].shift(1)
    out["is_latest"] = out["revision_number"] == grp["revision_number"].transform("max")
    return out


# ----------------------------------------------------------------- fetching

def fetch_symbol(client: nse_api.Client, symbol: str, *,
                 period: str = "Quarterly", regime: str = "legacy",
                 force: bool = False) -> pd.DataFrame:
    """Fetch one symbol's filings from one regime, caching the raw JSON."""
    url = LEGACY_URL if regime == "legacy" else INTEGRATED_URL
    path = (nse_api.raw_dir(f"filings/{regime}/{period.lower()}")
            / f"{symbol.upper()}.json")
    body = client.get_cached(
        path, url, {"index": "equities", "symbol": symbol.upper(),
                    "period": period},
        want="json", force=force)
    records = nse_api.decode_json(body)
    return (parse_legacy(records) if regime == "legacy"
            else parse_integrated(records))


def sync(symbols: list[str], *, throttle: float = 1.5, force: bool = False,
         periods: tuple[str, ...] = ("Quarterly", "Annual"),
         regimes: tuple[str, ...] = ("legacy", "integrated"),
         verbose: bool = True) -> dict:
    """Fetch filing metadata for a symbol list across both regimes.

    There is no date-range form, so this is one request per symbol per period
    per regime. It is the expensive collector in this package by an order of
    magnitude; run it against a universe you actually intend to study.
    """
    client = nse_api.Client(area="results", throttle=throttle)
    stats = {"symbols": len(symbols), "requests": 0, "rows": 0, "failed": []}
    for i, sym in enumerate(symbols, 1):
        got = 0
        for regime in regimes:
            # The integrated feed has one period form; asking it for "Annual"
            # repeats the same payload.
            for period in (periods if regime == "legacy" else ("Quarterly",)):
                try:
                    df = fetch_symbol(client, sym, period=period,
                                      regime=regime, force=force)
                except nse_api.NSEBlocked as exc:
                    stats["failed"].append({"symbol": sym, "regime": regime,
                                            "period": period, "error": str(exc)})
                    continue
                stats["requests"] += 1
                stats["rows"] += len(df)
                got += len(df)
        if verbose and (i % 25 == 0 or i == len(symbols)):
            print(f"  filings {i}/{len(symbols)} rows={stats['rows']:,} "
                  f"failed={len(stats['failed'])}", flush=True)
    return stats


def load() -> pd.DataFrame:
    """Read every cached filing payload back, unioned and revision-linked."""
    frames = []
    for regime, parser in (("legacy", parse_legacy),
                           ("integrated", parse_integrated)):
        root = nse_api.raw_dir(f"filings/{regime}")
        for f in sorted(root.glob("*/*.json")):
            df = parser(nse_api.decode_json(f.read_bytes()))
            if not df.empty:
                frames.append(df)
    if not frames:
        return mark_revisions(pd.DataFrame(columns=COLUMNS))
    out = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["filing_id"])
    return mark_revisions(out)


__all__ = [
    "COLUMNS", "INTEGRATED_FROM", "INTEGRATED_URL", "LEGACY_URL",
    "fetch_symbol", "filing_id", "load", "mark_revisions", "parse_integrated",
    "parse_legacy", "sync",
]
