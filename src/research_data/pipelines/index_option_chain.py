"""The NIFTY option chain — weekly and monthly — priced against the index.

WHY THIS IS A SEPARATE TABLE FROM `option_chain`
The stock chain and the index chain look alike and settle nothing alike, and the
differences are exactly the ones a strategy is built on:

  * **Cash settlement.** A NIFTY option that finishes in the money pays the
    difference in rupees. Nothing is delivered, so there is no assignment, no
    physical-settlement brokerage, and no share position to inherit. The single
    most expensive line item in the stock wheel — 0.25% of notional every time a
    contract settles in the money — simply does not exist here.
  * **Weeklies.** Stock options are monthly only. NIFTY has had weekly expiries
    since February 2019, so the whole 2020-2026 sample supports a weekly cycle.
    Both live in this table; `expiry_kind` tells them apart.
  * **The underlying is not tradable.** A stock option's underlying has a cash
    print in the same tape. An index does not: you cannot buy the Nifty 50. Any
    strategy that is long the index is really long a *proxy* — an ETF, or a
    futures position — and the gap between proxy and index is a real source of
    P&L. This table therefore carries the index level only, and leaves the proxy
    to the strategy, so that the basis is visible rather than assumed away.

SETTLEMENT IS THE INDEX CLOSE, WHICH IS NOT THE LAST TRADE
NSE settles index options on the closing value of the index on expiry day, and
that close is the last-half-hour weighted average of the index rather than its
final print. The `Closing Index Value` published in `ind_close_all` *is* that
average, so `underlying` here is already the number a contract settles against.
This is a place where the convenient column happens to be the correct one, which
is worth stating because it usually is not.

LOT SIZE IS CARRIED FOR CAPITAL, NOT FOR RETURNS
A covered call holds one lot of index exposure per lot of calls sold, so lot
size cancels out of every return this table is used to compute. It survives here
only to answer "what is the smallest book that can run this", which over the
sample moved a great deal: 75 units, then 50 from June 2021, then 25 from April
2024, then back to 75 in January 2025 under SEBI's raised minimum contract value,
then 65 at the end of 2025.

It cannot be read off the option rows. `nse_derivatives` recovers lot size from
`turnover / (contracts * price)`, and on an option row that division is nonsense
because the archive reports option turnover on the **strike notional** rather
than on the premium. It is recovered instead from the NIFTY *futures* row, where
turnover really is price times quantity, and then median-smoothed: the legacy
era's per-session value flickers between 74 and 77 on rounding alone, and only
its level is information.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ...core import config
from ..sources import nse_derivatives, nse_index_close

CHAIN_DIR = config.NORMALIZED_DIR / "option_chain_index"

CHAIN_COLUMNS = (
    "session", "symbol", "expiry", "expiry_kind", "strike", "option_type",
    "days_to_expiry", "settle", "close", "contracts", "open_interest",
    "lot_size", "underlying", "moneyness", "source_era",
)


@dataclass(frozen=True)
class IndexChainConfig:
    symbol: str = "NIFTY"
    # Weekly NIFTY strikes are listed far wider than they are traded. 0.25 in
    # log terms (~ +28% / -22%) covers every strike a covered call or a wheel
    # would ever choose and drops most of the file.
    max_log_moneyness: float = 0.25


def _index_spot(name: str = "Nifty 50") -> pd.DataFrame:
    frame = pd.read_parquet(nse_index_close.INDEX_PATH)
    frame = frame.loc[frame["index_name"] == name][["session", "close"]]
    return frame.rename(columns={"close": "underlying"}).dropna()


def _lot_sizes(symbol: str = "NIFTY", root: Path | None = None,
               window: int = 21) -> pd.DataFrame:
    """Lot size per session from the futures row, median-smoothed.

    The legacy era derives lot size from turnover and lands within a unit or two
    of the truth; the median over a rolling window recovers the exact integer,
    and the udiff era reports it outright so smoothing is a no-op there.
    """
    base = root or (config.RAW_DIR / "fo_bhavcopy")
    frames = []
    for file in sorted(base.rglob("fo_*.parquet")):
        day = pd.read_parquet(file, columns=["session", "symbol", "instrument",
                                             "expiry", "lot_size"])
        day = day.loc[(day["symbol"] == symbol)
                      & (day["instrument"] == "index_future")]
        if not day.empty:
            frames.append(day.sort_values("expiry").iloc[[0]][["session", "lot_size"]])
    if not frames:
        raise RuntimeError(f"no {symbol} index futures rows for lot size")
    lots = pd.concat(frames).sort_values("session").reset_index(drop=True)
    smooth = lots["lot_size"].rolling(window, center=True, min_periods=1).median()
    lots["lot_size"] = smooth.round()
    return lots


def _classify_expiries(chain: pd.DataFrame) -> pd.Series:
    """Monthly if it is the last expiry of its calendar month, else weekly.

    Derived from the expiry set itself rather than from a rule. NSE has moved
    the expiry weekday twice inside this sample and shifts it around holidays,
    so any weekday rule is right until it abruptly is not — but "the last one in
    the month is the monthly contract" has held throughout.
    """
    expiries = pd.Series(sorted(pd.to_datetime(chain["expiry"].unique())))
    period = expiries.dt.to_period("M")
    is_monthly = expiries.groupby(period).transform("max") == expiries
    lookup = dict(zip(expiries, np.where(is_monthly, "monthly", "weekly")))
    return chain["expiry"].map(lookup).astype("string")


def build(cfg: IndexChainConfig | None = None, root: Path | None = None,
          out: Path | None = None, verbose: bool = True) -> Path:
    cfg = cfg or IndexChainConfig()
    base = root or nse_derivatives.FO_OPTIONS_DIR
    target = out or CHAIN_DIR
    spot = _index_spot()
    lots = _lot_sizes(cfg.symbol)

    frames: list[pd.DataFrame] = []
    paths = sorted(base.rglob("fo_*.parquet"))
    for index, path in enumerate(paths, start=1):
        day = pd.read_parquet(path)
        day = day.loc[(day["instrument"] == "index_option")
                      & (day["symbol"] == cfg.symbol)
                      & day["strike"].notna() & day["option_type"].notna()]
        if day.empty:
            continue
        day = day.drop(columns=["lot_size", "lot_size_source", "underlying_close"])
        day = day.merge(lots, on="session", how="left")
        day = day.merge(spot, on="session", how="inner")
        if day.empty:
            continue
        day["moneyness"] = np.log(day["strike"] / day["underlying"])
        day = day.loc[day["moneyness"].abs() <= cfg.max_log_moneyness]
        if day.empty:
            continue
        day["days_to_expiry"] = (day["expiry"] - day["session"]).dt.days
        frames.append(day)
        if verbose and index % 400 == 0:
            print(f"  index chain {index}/{len(paths)} "
                  f"rows={sum(map(len, frames)):,}", flush=True)

    if not frames:
        raise RuntimeError("no index option rows survived the chain filters")
    chain = pd.concat(frames, ignore_index=True)
    chain["expiry_kind"] = _classify_expiries(chain)
    chain = chain[list(CHAIN_COLUMNS)].sort_values(
        ["session", "expiry", "strike", "option_type"], kind="stable")
    target.mkdir(parents=True, exist_ok=True)
    for year, block in chain.groupby(chain["session"].dt.year):
        block.reset_index(drop=True).to_parquet(
            target / f"chain_{year}.parquet", index=False)
    if verbose:
        print(f"  index chain complete: {len(chain):,} rows -> {target}",
              flush=True)
    return target


def load(start: date | None = None, end: date | None = None,
         path: Path | None = None, columns: list[str] | None = None
         ) -> pd.DataFrame:
    base = path or CHAIN_DIR
    files = sorted(base.glob("chain_*.parquet"))
    if not files:
        raise FileNotFoundError(f"no index chain files under {base}")
    frames = []
    for file in files:
        year = int(file.stem.removeprefix("chain_"))
        if start is not None and year < pd.Timestamp(start).year:
            continue
        if end is not None and year > pd.Timestamp(end).year:
            continue
        frames.append(pd.read_parquet(file, columns=columns))
    chain = pd.concat(frames, ignore_index=True)
    if start is not None:
        chain = chain.loc[chain["session"] >= pd.Timestamp(start)]
    if end is not None:
        chain = chain.loc[chain["session"] <= pd.Timestamp(end)]
    return chain.reset_index(drop=True)


def expiry_calendar(chain: pd.DataFrame) -> pd.DataFrame:
    """Every expiry, its kind, and the sessions it was quoted across."""
    grouped = chain.groupby(["expiry", "expiry_kind"], as_index=False).agg(
        first_session=("session", "min"), last_session=("session", "max"),
        strikes=("strike", "nunique"), contracts=("contracts", "sum"))
    return grouped.sort_values("expiry").reset_index(drop=True)


__all__ = ["CHAIN_COLUMNS", "CHAIN_DIR", "IndexChainConfig", "build",
           "expiry_calendar", "load"]
