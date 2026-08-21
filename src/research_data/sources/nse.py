"""NSE's own public archives: daily bhavcopy + index constituent lists.

This replaces Breeze for the entire daily layer. Bhavcopy is free, unthrottled,
complete, and — critically — **point-in-time**: each day's file lists exactly the
securities that traded that day, which is what kills survivorship bias. Breeze is
then only needed for 1-second opening data on the handful of screened candidates.

The legacy `sec_bhavdata_full` format is preferred over UDiFF because it carries
TURNOVER_LACS (traded value, the liquidity measure we actually want) and
delivery quantity/percentage. Available from ~2020 onward; 2019 and earlier 404.

THREE ARCHIVE QUIRKS, all discovered empirically and all handled below:

  1. NSE trades on some weekends. Union Budget Saturdays (2020-02-01,
     2025-02-01), Diwali Muhurat sessions, and disaster-recovery-site drills
     (2024-01-20, 2024-03-02, 2024-05-18) are real sessions on Sat/Sun. Asking
     only for Mon-Fri silently drops them, which leaves a one-session hole that
     later reads as a market-wide price step.
  2. A session's file is not always served at that session's URL. The
     2021-11-04 Muhurat bhavcopy is served at the 05112021 URL. So the file's
     own DATE1 decides where it is stored, never the date we asked for. This
     subsumes the holiday-stale behaviour: a holiday URL returning the prior
     session simply re-resolves to a day we already hold.
  3. On 2022-08-08 the ".csv" URL returns an XLSX workbook (PK zip header).
     One day out of ~1,600, so it is a fallback rather than a format guess.
"""
from __future__ import annotations

import io
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from ...core import config

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.nseindia.com/"}

BHAV_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
INDEX_URL = "https://nsearchives.nseindia.com/content/indices/{name}.csv"
# Authoritative ETF list. ETFs trade in the EQ series, so without this they
# pass a volatility-contraction screen trivially: liquid/debt ETFs barely move
# by construction, which reads as a permanent "tight base".
ETF_LIST_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"

BHAV_DIR = config.RAW_DIR / "bhavcopy"
# The legacy era lands in its own tree, not merged into BHAV_DIR. Two reasons:
# the delivery columns are NaN throughout, so a family with a delivery floor
# must be able to ask for the modern archive alone; and a re-pull of one era
# must never be able to truncate the other.
LEGACY_BHAV_DIR = config.RAW_DIR / "bhavcopy_legacy"
INDEX_DIR = config.METADATA_DIR / "index_lists"
DAILY_BARS = config.NORMALIZED_DIR / "daily_bars.parquet"

# Size tiers, largest first. Membership in the smallest list a symbol appears in
# gives its size bucket — NSE publishes no free market-cap file, so index
# membership is the honest point-in-time-ish proxy for "how big is this".
SIZE_LISTS = [
    ("ind_nifty50list", 50),
    ("ind_nifty100list", 100),
    ("ind_nifty200list", 200),
    ("ind_nifty500list", 500),
    ("ind_niftytotalmarket_list", 750),
    ("ind_niftymicrocap250_list", 1000),
]

# Sectoral indices, used both for sector labels and as a cross-check on the
# Industry column that ships inside the broad-market lists.
SECTOR_LISTS = [
    "ind_niftybanklist", "ind_niftyitlist", "ind_niftyautolist",
    "ind_niftypharmalist", "ind_niftymetallist", "ind_niftyfmcglist",
    "ind_niftyrealtylist", "ind_niftyenergylist", "ind_niftyoilgaslist",
    "ind_niftyconsumerdurableslist", "ind_niftyhealthcarelist",
    "ind_niftypsubanklist", "ind_niftyinfralist", "ind_niftycommoditieslist",
]

COLUMN_MAP = {
    "SYMBOL": "symbol", "SERIES": "series", "DATE1": "date",
    "PREV_CLOSE": "prev_close", "OPEN_PRICE": "open", "HIGH_PRICE": "high",
    "LOW_PRICE": "low", "CLOSE_PRICE": "close", "LAST_PRICE": "last",
    "AVG_PRICE": "vwap", "TTL_TRD_QNTY": "volume", "TURNOVER_LACS": "turnover_lacs",
    "NO_OF_TRADES": "trades", "DELIV_QTY": "deliv_qty", "DELIV_PER": "deliv_pct",
}

LEGACY_BHAV_URL = "https://nsearchives.nseindia.com/content/historical/EQUITIES/{yyyy}/{mmm}/cm{dd}{mmm}{yyyy}bhav.csv.zip"

LEGACY_COLUMN_MAP = {
    "SYMBOL": "symbol", "SERIES": "series", "TIMESTAMP": "date",
    "OPEN": "open", "HIGH": "high", "LOW": "low", "CLOSE": "close",
    "LAST": "last", "PREVCLOSE": "prev_close", "TOTTRDQTY": "volume",
    "TOTTRDVAL": "turnover", "TOTALTRADES": "trades", "ISIN": "isin",
}


def bhav_url(d: date) -> str:
    return BHAV_URL.format(ddmmyyyy=d.strftime("%d%m%Y"))


def legacy_bhav_url(d: date) -> str:
    return LEGACY_BHAV_URL.format(
        dd=d.strftime("%d"),
        mmm=d.strftime("%b").upper(),
        yyyy=d.strftime("%Y"),
    )


def _day_path(d: date, root: Path | None = None) -> Path:
    base = root or BHAV_DIR
    return base / f"{d.year}" / f"{d.strftime('%Y-%m-%d')}.parquet"


def _read_table(content: bytes) -> pd.DataFrame:
    """CSV normally; XLSX when NSE serves a workbook at the .csv URL (2022-08-08)."""
    if content[:2] == b"PK":
        # Check if it is a zip containing a CSV (legacy format) or XLSX
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                csv_names = [n for n in z.namelist() if n.endswith(".csv")]
                if csv_names:
                    return pd.read_csv(z.open(csv_names[0]), skipinitialspace=True)
        except Exception:
            pass
        return pd.read_excel(io.BytesIO(content))
    return pd.read_csv(io.StringIO(content.decode("utf-8", "replace")),
                       skipinitialspace=True)


def parse_legacy_bhavcopy(text: str | bytes, d: date | None = None) -> pd.DataFrame:
    """Parse a legacy pre-2020 bhavcopy (cmDDMMMYYYYbhav.csv.zip).

    Same contract as `parse_bhavcopy` — same column names, same units — so the
    two eras concatenate without a reconciliation step. Three differences are
    intrinsic to the format rather than choices made here:

      * no DELIV_QTY/DELIV_PER, so delivery is NaN rather than absent. A column
        that vanishes changes the panel's schema by date; one that goes NaN
        does not, and NaN is the honest answer to "what was delivery in 2007".
      * no AVG_PRICE, so `vwap` is NaN for the same reason.
      * TOTTRDVAL is already rupees, where the modern file gives lakhs. It is
        stored as rupees in both, because a unit that changes at a date
        boundary is a silent factor-of-100,000 break in every turnover-based
        feature.

    ISIN is carried through. Over thirty years symbols are renamed and reused,
    and the ticker alone does not identify a security across that span.
    """
    content = text if isinstance(text, bytes) else text.encode("utf-8", "replace")
    df = _read_table(content)
    df.columns = [str(c).strip().upper() for c in df.columns]
    df = df.rename(columns=LEGACY_COLUMN_MAP)
    keep = [c for c in LEGACY_COLUMN_MAP.values() if c in df.columns]
    df = df[keep]
    for c in df.select_dtypes(include="object").columns:
        df[c] = df[c].astype(str).str.strip()
    df = df[df["series"].isin(["EQ", "BE"])].copy()
    num = ["open", "high", "low", "close", "prev_close", "last",
           "volume", "turnover", "trades"]
    for c in num:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # TIMESTAMP is "15-MAR-2021"; trust the file's own date, as the modern
    # parser does, so a URL serving a neighbouring session still files right.
    parsed = pd.to_datetime(df["date"], format="%d-%b-%Y", errors="coerce")
    miss = parsed.isna()
    if miss.any():
        parsed[miss] = pd.to_datetime(df.loc[miss, "date"], errors="coerce",
                                      dayfirst=True)
    df["date"] = parsed
    df = df[df["date"].notna()]

    # The archive gained columns over thirty years: TOTALTRADES appears in the
    # 2000s, ISIN around 2003, and AVG_PRICE/delivery never. Rather than track
    # which era has which, every column in the contract is materialised, NaN
    # where the source has nothing to say. A column that appears partway
    # through the history would otherwise change the panel's schema by date,
    # and a feature computed across that boundary would silently change
    # meaning rather than fail.
    order = ["date", "symbol", "series", "open", "high", "low", "close",
             "prev_close", "last", "vwap", "volume", "turnover", "trades",
             "deliv_qty", "deliv_pct", "isin"]
    for c in order:
        if c not in df.columns:
            df[c] = pd.NA if c == "isin" else np.nan
    return df[order].reset_index(drop=True)


def fetch_legacy_day(d: date, session: requests.Session | None = None,
                     timeout: int = 60) -> tuple[date, pd.DataFrame] | None:
    """Fetch the legacy bhavcopy at `d`'s URL; return (session_date, frame)."""
    s = session or requests.Session()
    try:
        r = s.get(legacy_bhav_url(d), headers=HEADERS, timeout=timeout)
    except requests.RequestException:
        return None
    if r.status_code != 200 or len(r.content) < 500:
        return None
    try:
        df = parse_legacy_bhavcopy(r.content, d)
    except Exception:
        return None
    if df.empty:
        return None
    return df["date"].iloc[0].date(), df


def parse_bhavcopy(text: str | bytes, d: date | None = None) -> pd.DataFrame:
    """Parse a bhavcopy CSV, trusting the file's own DATE1 over the URL.

    NSE serves the PREVIOUS trading day's file for holiday URLs rather than
    404ing: requesting 26012026 (Republic Day) returns rows dated 23-Jan-2026,
    byte-identical to the 23012026 file. Taking the requested date on faith
    duplicates a session onto every holiday and corrupts all rolling
    indicators, so the real date is read out of the data.
    """
    content = text if isinstance(text, bytes) else text.encode("utf-8", "replace")
    df = _read_table(content)
    df.columns = [str(c).strip().upper() for c in df.columns]
    df = df.rename(columns=COLUMN_MAP)
    keep = [c for c in COLUMN_MAP.values() if c in df.columns]
    df = df[keep]
    for c in df.select_dtypes(include="object").columns:
        df[c] = df[c].astype(str).str.strip()
    # Only real cash equities; EQ and BE are the tradeable series that matter.
    df = df[df["series"].isin(["EQ", "BE"])].copy()
    num = ["open", "high", "low", "close", "prev_close", "last", "vwap",
           "volume", "turnover_lacs", "trades", "deliv_qty", "deliv_pct"]
    for c in num:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # Trust the file's own date, not the URL we asked for. The XLSX variant
    # hands back real datetimes rather than "%d-%b-%Y" strings, so try the
    # strict format first and fall back to inference for whatever it missed.
    parsed = pd.to_datetime(df["date"], format="%d-%b-%Y", errors="coerce")
    if parsed.isna().any():
        loose = pd.to_datetime(df["date"], errors="coerce", dayfirst=True)
        parsed = parsed.fillna(loose)
    df["date"] = parsed
    df = df[df["date"].notna()]
    # TURNOVER_LACS is in lakhs of rupees; store rupees to avoid unit confusion.
    if "turnover_lacs" in df.columns:
        df["turnover"] = df["turnover_lacs"] * 1e5
        df = df.drop(columns=["turnover_lacs"])
    return df.reset_index(drop=True)


def fetch_day(d: date, session: requests.Session | None = None,
              timeout: int = 60) -> tuple[date, pd.DataFrame] | None:
    """Fetch the bhavcopy at `d`'s URL; return (session_date, frame) or None.

    The returned date is the file's own DATE1, which is not always `d`:

      * holiday URLs serve the previous session verbatim (requesting 26012026
        returns 23-Jan-2026), so the caller learns `d` itself did not trade;
      * the 2021-11-04 Muhurat session is served at the 05112021 URL, so a
        real session is only reachable by asking for a *different* day.

    Returning the true date instead of rejecting the mismatch keeps both cases
    correct: the caller stores the frame under the session it actually
    describes, and marks `d` as non-trading whenever the two differ.
    """
    s = session or requests.Session()
    try:
        r = s.get(bhav_url(d), headers=HEADERS, timeout=timeout)
    except requests.RequestException:
        return None
    if r.status_code != 200 or len(r.content) < 1000:
        return None
    try:
        df = parse_bhavcopy(r.content, d)
    except Exception:
        return None
    if df.empty:
        return None
    return df["date"].iloc[0].date(), df


def sync(start: date, end: date, throttle: float = 0.25, workers: int = 4,
         verbose: bool = True, weekends: bool = True,
         recheck_empty: bool = False, fetch=None, root: Path | None = None) -> dict:
    """Download every missing trading day in [start, end] into data/raw/bhavcopy.

    Every calendar day is requested, weekends included: NSE runs real sessions
    on some Saturdays and Sundays (budget days, Muhurat, DR-site drills), and
    skipping them leaves a hole that later looks like a market-wide price step.
    Non-trading days are recorded as empty markers so they cost one request
    ever, which is what keeps the weekend sweep cheap on subsequent runs.

    Frames are filed under the date *inside* the file, so a URL that serves a
    neighbouring session lands on the right day. `recheck_empty` re-requests
    days currently held as markers, which is how an already-populated archive
    picks up sessions that an earlier, weekday-only sync never asked for.
    """
    root = root or BHAV_DIR
    fetch = fetch or fetch_day
    root.mkdir(parents=True, exist_ok=True)

    def _is_marker(p: Path) -> bool:
        try:
            return p.exists() and len(pd.read_parquet(p, columns=["symbol"])) == 0
        except Exception:
            return False

    days = []
    d = start
    while d <= end:
        if weekends or d.weekday() < 5:
            p = _day_path(d, root)
            if not p.exists() or (recheck_empty and _is_marker(p)):
                days.append(d)
        d += timedelta(days=1)

    stats = {"requested": len(days), "downloaded": 0, "missing": 0, "rows": 0,
             "relocated": []}
    if not days:
        return stats

    lock_state = {"last": 0.0}

    def one(day: date):
        gap = time.monotonic() - lock_state["last"]
        if gap < throttle:
            time.sleep(throttle - gap)
        lock_state["last"] = time.monotonic()
        return day, fetch(day)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (day, got) in enumerate(ex.map(one, days), 1):
            actual, df = got if got else (None, None)
            if df is None or df.empty:
                # Empty marker = known non-trading day, so we never re-request it.
                _write_marker(day, root)
                stats["missing"] += 1
            elif actual == day:
                p = _day_path(day, root)
                p.parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(p, index=False)
                stats["downloaded"] += 1
                stats["rows"] += len(df)
            else:
                # This URL served a different session. `day` did not trade; the
                # session it did serve is stored where it belongs, if new.
                _write_marker(day, root)
                stats["missing"] += 1
                tgt = _day_path(actual, root)
                if not tgt.exists() or _is_marker(tgt):
                    tgt.parent.mkdir(parents=True, exist_ok=True)
                    df.to_parquet(tgt, index=False)
                    stats["downloaded"] += 1
                    stats["rows"] += len(df)
                    stats["relocated"].append(f"{day}->{actual}")
            if verbose and i % 50 == 0:
                print(f"  bhavcopy {i}/{len(days)} ok={stats['downloaded']} "
                      f"non-trading={stats['missing']} rows={stats['rows']:,}", flush=True)
    return stats


def _write_marker(d: date, root: Path | None = None) -> None:
    """Record a known non-trading day so it is never re-requested."""
    p = _day_path(d, root)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        return
    pd.DataFrame(columns=["symbol"]).to_parquet(p, index=False)


def sync_legacy(start: date, end: date, **kw) -> dict:
    """Sync the legacy (pre-delivery) archive into its own tree."""
    kw.setdefault("fetch", fetch_legacy_day)
    kw.setdefault("root", LEGACY_BHAV_DIR)
    return sync(start, end, **kw)


def load_range(start: date | None = None, end: date | None = None,
               root: Path | None = None) -> pd.DataFrame:
    files = sorted((root or BHAV_DIR).glob("*/*.parquet"))
    frames = []
    for f in files:
        d = date.fromisoformat(f.stem)
        if (start and d < start) or (end and d > end):
            continue
        df = pd.read_parquet(f)
        if not df.empty and "close" in df.columns:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["symbol", "date"]).reset_index(drop=True)


def consolidate() -> Path:
    df = load_range()
    config.NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(DAILY_BARS, index=False)
    return DAILY_BARS


# ---------------------------------------------------------------- index lists

def fetch_index_lists(force: bool = False) -> dict[str, pd.DataFrame]:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    names = [n for n, _ in SIZE_LISTS] + SECTOR_LISTS
    s = requests.Session()
    for name in names:
        p = INDEX_DIR / f"{name}.csv"
        if force or not p.exists():
            r = s.get(INDEX_URL.format(name=name), headers=HEADERS, timeout=60)
            if r.status_code == 200 and len(r.content) > 200:
                p.write_bytes(r.content)
            time.sleep(0.25)
        if p.exists():
            df = pd.read_csv(p)
            df.columns = [c.strip() for c in df.columns]
            out[name] = df
    return out


def fetch_etf_symbols(force: bool = False) -> set[str]:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    p = INDEX_DIR / "eq_etfseclist.csv"
    if force or not p.exists():
        r = requests.get(ETF_LIST_URL, headers=HEADERS, timeout=60)
        if r.status_code == 200 and len(r.content) > 200:
            p.write_bytes(r.content)
    if not p.exists():
        return set()
    # This file is not clean UTF-8 (stray cp1252 bytes in security names).
    df = pd.read_csv(p, encoding="latin-1")
    df.columns = [c.strip() for c in df.columns]
    return {str(x).strip().upper() for x in df["Symbol"].dropna()}


def build_symbol_metadata(force: bool = False) -> pd.DataFrame:
    """symbol -> size_tier, size_tier_rank, sector.

    size_tier_rank is the size of the smallest broad index containing the symbol
    (50/100/200/500/750), or 9999 for everything outside NIFTY Total Market.
    It is a coarse stand-in for market-cap rank: NSE publishes no free market-cap
    file, so a true continuous rank is not available. Treat it as buckets.
    """
    lists = fetch_index_lists(force=force)
    rows: dict[str, dict] = {}

    # Broad lists, largest tier last so smaller (tighter) tiers win.
    for name, tier in sorted(SIZE_LISTS, key=lambda x: -x[1]):
        df = lists.get(name)
        if df is None or "Symbol" not in df.columns:
            continue
        for _, r in df.iterrows():
            sym = str(r["Symbol"]).strip()
            rec = rows.setdefault(sym, {"symbol": sym})
            rec["size_tier_rank"] = tier
            rec["size_tier"] = name.replace("ind_", "").replace("list", "").replace("_", "")
            if "Industry" in df.columns and pd.notna(r.get("Industry")):
                rec["sector"] = str(r["Industry"]).strip()
            if "ISIN Code" in df.columns:
                rec["isin"] = str(r.get("ISIN Code", "")).strip()

    # Sectoral membership is a stronger sector signal than the Industry column.
    for name in SECTOR_LISTS:
        df = lists.get(name)
        if df is None or "Symbol" not in df.columns:
            continue
        label = name.replace("ind_nifty", "").replace("list", "").upper()
        for _, r in df.iterrows():
            sym = str(r["Symbol"]).strip()
            rec = rows.setdefault(sym, {"symbol": sym})
            rec["sector_index"] = label

    etfs = fetch_etf_symbols(force=force)
    for sym in etfs:
        rows.setdefault(sym, {"symbol": sym})
    out = pd.DataFrame(list(rows.values()))
    out["is_etf"] = out["symbol"].str.upper().isin(etfs)
    for c in ("sector", "sector_index", "size_tier", "isin"):
        if c not in out.columns:
            out[c] = pd.NA
    if "size_tier_rank" not in out.columns:
        out["size_tier_rank"] = 9999
    out["size_tier_rank"] = out["size_tier_rank"].fillna(9999).astype(int)
    p = config.METADATA_DIR / "symbol_metadata.parquet"
    out.to_parquet(p, index=False)
    return out
