"""NSE's derivatives bhavcopy archive: the point-in-time F&O universe.

WHY THIS EXISTS
An NRI cannot trade intraday in the cash segment and cannot short cash equities.
Every intraday or bearish claim this lab makes is therefore executable only in
F&O, which means the tradable universe is not "liquid NSE equities" but
"securities that had a stock futures contract *on that session*". That universe
is a moving target: SEBI's eligibility criteria have been revised upward more
than once, and names enter and leave continuously.

The archive answers it exactly. Each session's file lists every contract that
actually traded that day, so the set of `FUTSTK` symbols in the file *is* the
point-in-time stock-futures universe. No vendor list, no inclusion circular
scraping, and — critically — no survivorship: a name that left F&O in 2022 is
present in 2021's files and absent from 2023's, which is what a current
"F&O list" download can never tell you.

TWO ARCHIVE ERAS, and the crossover is abrupt
  * legacy  `content/historical/DERIVATIVES/{YYYY}/{MMM}/fo{DDMMMYYYY}bhav.csv.zip`
    serves through **2024-07-05** and 404s after.
  * UDiFF   `content/fo/BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip`
    serves from ~2024-05 onward and 404s before.
Both were verified live on 2026-08-25; they overlap for roughly two months.
The eras carry different column names, different instrument-type spellings and
different information, so `parse_*` normalises both to one schema rather than
letting era-specific column names leak into research code.

WHAT EACH ERA GIVES, AND THE ONE THING ONLY UDiFF HAS
UDiFF carries `NewBrdLotQty` — the contract lot size — directly. The legacy
format does not, so lot size is *derived* from turnover, contract count and
price. That derivation is good to a rounding error, but it is a derived field
and is flagged as such in `lot_size_source`: position quantisation on a small
book is decided by lot size, so a study must be able to tell a reported lot
from an inferred one.

Legacy `VAL_INLAKH` is lakh rupees; UDiFF `TtlTrfVal` is rupees. They are
normalised to rupees. Legacy `CONTRACTS` counts contracts; UDiFF
`TtlTradgVol` also counts contracts in the FO segment (not shares), so the
implied notional is contracts * lot * price in both eras.

THE HOLIDAY TRAP APPLIES HERE TOO
`sources/nse.py` documents that an equity bhavcopy URL for a non-session can
serve the *previous* session's file with HTTP 200. The derivatives archive is
served by the same host under the same conventions, so the same defence is
used: the session date comes from the file's own `TIMESTAMP` / `TradDt`
column, never from the URL that was requested. A file that resolves to a date
we already hold is simply re-filed, not counted as a new session.
"""
from __future__ import annotations

import io
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from ...core import config

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.nseindia.com/"}

LEGACY_URL = ("https://nsearchives.nseindia.com/content/historical/DERIVATIVES/"
              "{yyyy}/{mmm}/fo{dd}{mmm}{yyyy}bhav.csv.zip")
UDIFF_URL = ("https://nsearchives.nseindia.com/content/fo/"
             "BhavCopy_NSE_FO_0_0_0_{yyyymmdd}_F_0000.csv.zip")

# Measured 2026-08-25: legacy answers 2024-07-05 and 404s on 2024-07-08.
# The eras overlap before that, so the boundary is a preference, not a cliff:
# `fetch_day` tries UDiFF first from here and legacy first before it, and
# falls back to the other era either way.
UDIFF_PREFERRED_FROM = date(2024, 6, 1)

FO_DIR = config.RAW_DIR / "fo_bhavcopy"
FUTURES_BARS = config.NORMALIZED_DIR / "fo_futures_daily.parquet"

# One normalised schema across both eras.
COLUMNS = (
    "session", "symbol", "instrument", "expiry", "open", "high", "low",
    "close", "settle", "underlying_close", "contracts", "traded_value",
    "open_interest", "change_in_open_interest", "lot_size", "lot_size_source",
    "source_era",
)

# Legacy INSTRUMENT / UDiFF FinInstrmTp -> canonical instrument label.
_INSTRUMENT_MAP = {
    "FUTSTK": "stock_future", "STF": "stock_future",
    "FUTIDX": "index_future", "IDF": "index_future",
    "OPTSTK": "stock_option", "STO": "stock_option",
    "OPTIDX": "index_option", "IDO": "index_option",
}


class DerivativesError(RuntimeError):
    pass


def legacy_url(day: date) -> str:
    stamp = pd.Timestamp(day)
    return LEGACY_URL.format(
        yyyy=stamp.strftime("%Y"), mmm=stamp.strftime("%b").upper(),
        dd=stamp.strftime("%d"))


def udiff_url(day: date) -> str:
    return UDIFF_URL.format(yyyymmdd=pd.Timestamp(day).strftime("%Y%m%d"))


def _day_path(day: date, root: Path | None = None) -> Path:
    base = root or FO_DIR
    stamp = pd.Timestamp(day)
    return base / stamp.strftime("%Y") / f"fo_{stamp.strftime('%Y%m%d')}.parquet"


def _unzip(content: bytes) -> pd.DataFrame:
    archive = zipfile.ZipFile(io.BytesIO(content))
    names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    if not names:
        raise DerivativesError("derivatives archive contained no CSV member")
    return pd.read_csv(archive.open(names[0]), low_memory=False)


def _derive_lot_size(contracts: pd.Series, traded_value: pd.Series,
                     price: pd.Series) -> pd.Series:
    """Recover lot size from turnover when the era does not report it.

    traded_value = contracts * lot * price, so lot = value / (contracts * price).
    Rounded to the nearest integer: NSE lot sizes are integers, and the residual
    here is the difference between the day's traded prices and its close.
    """
    denominator = pd.to_numeric(contracts * price, errors="coerce").replace(0, float("nan"))
    lot = (pd.to_numeric(traded_value, errors="coerce") / denominator).round()
    return lot.where(lot > 0)


def parse_legacy(content: bytes | pd.DataFrame) -> pd.DataFrame:
    frame = content if isinstance(content, pd.DataFrame) else _unzip(content)
    frame = frame.rename(columns=lambda name: str(name).strip())
    required = {"INSTRUMENT", "SYMBOL", "EXPIRY_DT", "CLOSE", "TIMESTAMP"}
    if missing := required - set(frame.columns):
        raise DerivativesError(f"legacy derivatives file missing {sorted(missing)}")
    out = pd.DataFrame({
        "session": pd.to_datetime(frame["TIMESTAMP"], format="%d-%b-%Y",
                                  errors="coerce"),
        "symbol": frame["SYMBOL"].astype(str).str.strip().str.upper(),
        "instrument": frame["INSTRUMENT"].astype(str).str.strip().str.upper()
            .map(_INSTRUMENT_MAP),
        "expiry": pd.to_datetime(frame["EXPIRY_DT"], format="%d-%b-%Y",
                                 errors="coerce"),
        "open": pd.to_numeric(frame.get("OPEN"), errors="coerce"),
        "high": pd.to_numeric(frame.get("HIGH"), errors="coerce"),
        "low": pd.to_numeric(frame.get("LOW"), errors="coerce"),
        "close": pd.to_numeric(frame.get("CLOSE"), errors="coerce"),
        "settle": pd.to_numeric(frame.get("SETTLE_PR"), errors="coerce"),
        # The legacy era publishes no underlying price column at all. It is
        # left missing rather than back-filled from the cash tape here: the
        # cash join belongs to the panel builder, which knows about renames.
        "underlying_close": pd.NA,
        "contracts": pd.to_numeric(frame.get("CONTRACTS"), errors="coerce"),
        "traded_value": pd.to_numeric(frame.get("VAL_INLAKH"),
                                      errors="coerce") * 100_000.0,
        "open_interest": pd.to_numeric(frame.get("OPEN_INT"), errors="coerce"),
        "change_in_open_interest": pd.to_numeric(frame.get("CHG_IN_OI"),
                                                 errors="coerce"),
    })
    out["lot_size"] = _derive_lot_size(
        out["contracts"], out["traded_value"], out["close"])
    out["lot_size_source"] = "derived_from_turnover"
    out["source_era"] = "legacy"
    return out[list(COLUMNS)]


def parse_udiff(content: bytes | pd.DataFrame) -> pd.DataFrame:
    frame = content if isinstance(content, pd.DataFrame) else _unzip(content)
    frame = frame.rename(columns=lambda name: str(name).strip())
    required = {"FinInstrmTp", "TckrSymb", "XpryDt", "ClsPric", "TradDt"}
    if missing := required - set(frame.columns):
        raise DerivativesError(f"UDiFF derivatives file missing {sorted(missing)}")
    out = pd.DataFrame({
        "session": pd.to_datetime(frame["TradDt"], errors="coerce"),
        "symbol": frame["TckrSymb"].astype(str).str.strip().str.upper(),
        "instrument": frame["FinInstrmTp"].astype(str).str.strip().str.upper()
            .map(_INSTRUMENT_MAP),
        "expiry": pd.to_datetime(frame["XpryDt"], errors="coerce"),
        "open": pd.to_numeric(frame.get("OpnPric"), errors="coerce"),
        "high": pd.to_numeric(frame.get("HghPric"), errors="coerce"),
        "low": pd.to_numeric(frame.get("LwPric"), errors="coerce"),
        "close": pd.to_numeric(frame.get("ClsPric"), errors="coerce"),
        "settle": pd.to_numeric(frame.get("SttlmPric"), errors="coerce"),
        "underlying_close": pd.to_numeric(frame.get("UndrlygPric"),
                                          errors="coerce"),
        "contracts": pd.to_numeric(frame.get("TtlTradgVol"), errors="coerce"),
        "traded_value": pd.to_numeric(frame.get("TtlTrfVal"), errors="coerce"),
        "open_interest": pd.to_numeric(frame.get("OpnIntrst"), errors="coerce"),
        "change_in_open_interest": pd.to_numeric(
            frame.get("ChngInOpnIntrst"), errors="coerce"),
        "lot_size": pd.to_numeric(frame.get("NewBrdLotQty"), errors="coerce"),
    })
    out["lot_size"] = out["lot_size"].where(out["lot_size"] > 0)
    out["lot_size_source"] = "reported"
    out["source_era"] = "udiff"
    return out[list(COLUMNS)]


def fetch_day(day: date, session: requests.Session | None = None,
              timeout: int = 60) -> tuple[date, pd.DataFrame] | None:
    """Fetch one session's derivatives bhavcopy from whichever era serves it.

    Returns ``(session_date, frame)`` where ``session_date`` comes from inside
    the file, or ``None`` when neither era has the day (a genuine non-session,
    or an archive hole).
    """
    client = session or requests.Session()
    prefer_udiff = day >= UDIFF_PREFERRED_FROM
    attempts = (
        [(udiff_url(day), parse_udiff), (legacy_url(day), parse_legacy)]
        if prefer_udiff else
        [(legacy_url(day), parse_legacy), (udiff_url(day), parse_udiff)])
    for url, parser in attempts:
        try:
            response = client.get(url, headers=HEADERS, timeout=timeout)
        except requests.RequestException:
            continue
        if response.status_code != 200 or not response.content[:2] == b"PK":
            continue
        try:
            frame = parser(response.content)
        except (DerivativesError, ValueError, zipfile.BadZipFile):
            continue
        frame = frame.loc[frame["session"].notna() & frame["instrument"].notna()]
        if frame.empty:
            continue
        # Trust the file, never the URL: a holiday URL can serve a neighbouring
        # session with HTTP 200.
        stamps = frame["session"].dropna().unique()
        if len(stamps) != 1:
            raise DerivativesError(
                f"derivatives file for {day} spans {len(stamps)} sessions")
        return pd.Timestamp(stamps[0]).date(), frame.reset_index(drop=True)
    return None


def sync(start: date, end: date, throttle: float = 0.20, workers: int = 4,
         root: Path | None = None, verbose: bool = True) -> dict:
    """Download every missing derivatives session in [start, end].

    Files are stored under the date *inside* the file. Weekends are requested
    too: NSE trades some Saturdays, and skipping them leaves a hole that later
    reads as a market-wide gap.
    """
    base = root or FO_DIR
    base.mkdir(parents=True, exist_ok=True)
    days = [start + timedelta(days=offset)
            for offset in range((end - start).days + 1)]
    pending = [day for day in days if not _day_path(day, base).exists()]
    stats = {"requested": len(days), "pending": len(pending),
             "downloaded": 0, "absent": 0, "failed": 0}
    if not pending:
        return stats

    client = requests.Session()

    def one(day: date) -> tuple[date, pd.DataFrame] | None:
        time.sleep(throttle)
        try:
            return fetch_day(day, client)
        except DerivativesError:
            stats["failed"] += 1
            return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, result in enumerate(pool.map(one, pending), start=1):
            if result is None:
                stats["absent"] += 1
            else:
                session_date, frame = result
                path = _day_path(session_date, base)
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    frame.to_parquet(path, index=False)
                    stats["downloaded"] += 1
            if verbose and index % 100 == 0:
                print(f"  fo bhavcopy {index}/{len(pending)} "
                      f"ok={stats['downloaded']} absent={stats['absent']}",
                      flush=True)
    return stats


def load_range(start: date | None = None, end: date | None = None,
               root: Path | None = None,
               instruments: tuple[str, ...] = ("stock_future",)) -> pd.DataFrame:
    """Load stored derivatives rows, optionally filtered by instrument type."""
    base = root or FO_DIR
    if not base.exists():
        return pd.DataFrame(columns=list(COLUMNS))
    frames = []
    for path in sorted(base.rglob("fo_*.parquet")):
        stamp = pd.Timestamp(path.stem.removeprefix("fo_")).date()
        if start and stamp < start:
            continue
        if end and stamp > end:
            continue
        frames.append(pd.read_parquet(path))
    if not frames:
        return pd.DataFrame(columns=list(COLUMNS))
    out = pd.concat(frames, ignore_index=True)
    if instruments:
        out = out.loc[out["instrument"].isin(instruments)]
    return out.sort_values(["session", "symbol", "expiry"],
                           kind="stable").reset_index(drop=True)


def stored_sessions(root: Path | None = None) -> list[date]:
    base = root or FO_DIR
    if not base.exists():
        return []
    return sorted(
        pd.Timestamp(path.stem.removeprefix("fo_")).date()
        for path in base.rglob("fo_*.parquet"))


__all__ = [
    "COLUMNS", "DerivativesError", "FO_DIR", "FUTURES_BARS",
    "UDIFF_PREFERRED_FROM", "fetch_day", "legacy_url", "load_range",
    "parse_legacy", "parse_udiff", "stored_sessions", "sync", "udiff_url",
]
