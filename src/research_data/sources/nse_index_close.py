"""NSE's daily all-index close archive — the buy-and-hold hurdle.

WHY A NEW SOURCE
The lab already builds an equal-weighted investable market index in
`pipelines/context`, which is the right hurdle for a cross-sectional signal
because it removes the market's *level* from a stock-picking claim. It is the
wrong hurdle for a whole-portfolio strategy that someone would hold *instead of*
an index fund. That comparison has to be against the thing they would actually
buy, and in India that is the Nifty 50.

`content/indices/ind_close_all_{DDMMYYYY}.csv` carries every NSE index for one
session: OHLC, turnover, and — the reason this file rather than a price series —
**P/E, P/B and Div Yield**.

THE DIVIDEND YIELD COLUMN IS THE WHOLE POINT
The Nifty 50 quoted everywhere is a *price* index. Over 6.7 years its published
dividend yield averages a little over 1.2%, so a strategy compared against the
price index is handed roughly 8% of cumulative return it did not earn. NSE
publishes a Nifty 50 TRI, but not in this file and not in any archive that
serves plainly, so the total return here is accrued from the file's own
`Div Yield`: each session adds `yield / 365 * calendar_days` to the price
return. That is an approximation — real dividends arrive in lumps on ex-dates,
not smoothly — but it is unbiased in level over any period long enough to
contain a full dividend season, and this study's shortest comparison is a year.

THE HOLIDAY TRAP, AGAIN
As everywhere else on this host, a URL for a non-session can answer 200 with a
neighbouring session's file. The date is therefore taken from the file's own
`Index Date` column and the row is filed under that, never under the requested
day.
"""
from __future__ import annotations

import io
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from ...core import config

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.nseindia.com/"}

INDEX_CLOSE_URL = ("https://nsearchives.nseindia.com/content/indices/"
                   "ind_close_all_{ddmmyyyy}.csv")

INDEX_DIR = config.RAW_DIR / "index_close"
INDEX_PATH = config.NORMALIZED_DIR / "index_close_daily.parquet"

# Kept narrow on purpose: the file holds ~120 indices and the study needs a
# benchmark, not an index zoo. Widen deliberately.
KEEP_INDICES = ("Nifty 50", "Nifty 500", "Nifty Next 50", "Nifty Bank",
                "Nifty Midcap 150", "Nifty 50 Futures Index",
                "Nifty 50 Futures TR Index", "Nifty 50 Arbitrage")

COLUMNS = ("session", "index_name", "open", "high", "low", "close",
           "turnover", "pe", "pb", "div_yield")


class IndexCloseError(RuntimeError):
    pass


def url_for(day: date) -> str:
    return INDEX_CLOSE_URL.format(ddmmyyyy=pd.Timestamp(day).strftime("%d%m%Y"))


def _day_path(day: date, root: Path | None = None) -> Path:
    stamp = pd.Timestamp(day)
    base = root or INDEX_DIR
    return base / stamp.strftime("%Y") / f"idx_{stamp.strftime('%Y%m%d')}.parquet"


def _num(series: pd.Series) -> pd.Series:
    # The file writes "-" for a missing value and ".82" for 0.82.
    return pd.to_numeric(series.astype(str).str.strip().replace("-", ""),
                         errors="coerce")


def parse(text: str) -> pd.DataFrame:
    frame = pd.read_csv(io.StringIO(text))
    frame = frame.rename(columns=lambda name: str(name).strip())
    required = {"Index Name", "Index Date", "Closing Index Value"}
    if missing := required - set(frame.columns):
        raise IndexCloseError(f"index close file missing {sorted(missing)}")
    out = pd.DataFrame({
        "session": pd.to_datetime(frame["Index Date"], format="%d-%m-%Y",
                                  errors="coerce"),
        "index_name": frame["Index Name"].astype(str).str.strip(),
        "open": _num(frame.get("Open Index Value")),
        "high": _num(frame.get("High Index Value")),
        "low": _num(frame.get("Low Index Value")),
        "close": _num(frame["Closing Index Value"]),
        "turnover": _num(frame.get("Turnover (Rs. Cr.)")),
        "pe": _num(frame.get("P/E")),
        "pb": _num(frame.get("P/B")),
        "div_yield": _num(frame.get("Div Yield")),
    })
    return out.loc[out["session"].notna() & out["close"].notna()]


def fetch_day(day: date, session: requests.Session | None = None,
              timeout: int = 30) -> tuple[date, pd.DataFrame] | None:
    client = session or requests.Session()
    try:
        response = client.get(url_for(day), headers=HEADERS, timeout=timeout)
    except requests.RequestException:
        return None
    if response.status_code != 200 or not response.text.lstrip().startswith("Index"):
        return None
    frame = parse(response.text)
    if frame.empty:
        return None
    stamps = frame["session"].unique()
    if len(stamps) != 1:
        raise IndexCloseError(f"index file for {day} spans {len(stamps)} sessions")
    return pd.Timestamp(stamps[0]).date(), frame.reset_index(drop=True)


def sync(start: date, end: date, throttle: float = 0.15, workers: int = 4,
         root: Path | None = None, verbose: bool = True) -> dict:
    base = root or INDEX_DIR
    base.mkdir(parents=True, exist_ok=True)
    days = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    pending = [d for d in days if not _day_path(d, base).exists()]
    stats = {"requested": len(days), "pending": len(pending),
             "downloaded": 0, "absent": 0}
    if not pending:
        return stats
    client = requests.Session()

    def one(day: date):
        time.sleep(throttle)
        try:
            return fetch_day(day, client)
        except IndexCloseError:
            return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, result in enumerate(pool.map(one, pending), start=1):
            if result is None:
                stats["absent"] += 1
            else:
                stamp, frame = result
                frame = frame.loc[frame["index_name"].isin(KEEP_INDICES)]
                path = _day_path(stamp, base)
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    frame[list(COLUMNS)].to_parquet(path, index=False)
                    stats["downloaded"] += 1
            if verbose and index % 200 == 0:
                print(f"  index close {index}/{len(pending)} "
                      f"ok={stats['downloaded']}", flush=True)
    return stats


def consolidate(root: Path | None = None, out: Path | None = None) -> Path:
    base = root or INDEX_DIR
    frames = [pd.read_parquet(p) for p in sorted(base.rglob("idx_*.parquet"))]
    if not frames:
        raise IndexCloseError("no stored index-close files")
    frame = pd.concat(frames, ignore_index=True).drop_duplicates(
        subset=["session", "index_name"], keep="last")
    frame = frame.sort_values(["index_name", "session"]).reset_index(drop=True)
    target = out or INDEX_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(target, index=False)
    return target


def series(name: str = "Nifty 50", path: Path | None = None) -> pd.DataFrame:
    """Price level and an accrued total-return level for one index."""
    frame = pd.read_parquet(path or INDEX_PATH)
    frame = frame.loc[frame["index_name"] == name].sort_values("session")
    if frame.empty:
        raise IndexCloseError(f"no rows for index {name!r}")
    out = frame[["session", "close", "div_yield", "pe", "pb"]].reset_index(drop=True)
    gap = out["session"].diff().dt.days.fillna(0.0)
    price_return = out["close"].pct_change().fillna(0.0)
    # Dividends accrue on the *previous* session's yield: today's yield is
    # computed off today's close and is not knowable before it.
    accrual = (out["div_yield"].shift(1).fillna(0.0) / 100.0) * gap / 365.0
    out["price_level"] = (1.0 + price_return).cumprod()
    out["total_level"] = (1.0 + price_return + accrual).cumprod()
    return out


__all__ = ["COLUMNS", "INDEX_DIR", "INDEX_PATH", "IndexCloseError",
           "KEEP_INDICES", "consolidate", "fetch_day", "parse", "series",
           "sync", "url_for"]
