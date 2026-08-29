"""The point-in-time stock option chain, priced against the cash tape.

WHY THIS EXISTS SEPARATELY FROM `fo_universe`
`fo_universe` answers "which names had a futures contract, and what did a lot
cost". It deliberately keeps one row per symbol-session. An option strategy
needs the opposite shape: every strike of every expiry, because the thing being
chosen *is* the strike. The two cannot share a table.

They also cannot share a source file. `data/raw/fo_bhavcopy` was written by a
parser that dropped `STRIKE_PR` and `OPTION_TYP`, so its option rows collapsed
every strike of a symbol-expiry into indistinguishable duplicates. The futures
rows there are unaffected and still back `fo_universe`. The option legs were
re-fetched into `data/raw/fo_options` with the full contract key, and this
module reads only that tree.

WHY THE SAMPLE STARTS IN 2020, AND WHY THAT IS NOT A DATA LIMITATION
Two regime changes have to be behind us before an equity-option strategy that
*intends* to be assigned means anything on this exchange:

  * **European exercise**, from 2011-01-27. Before it, a short stock option
    could be assigned on any day, so "hold to expiry" was not a decision the
    seller got to make.
  * **Compulsory physical settlement** of stock derivatives, phased in over
    2019 and complete from the **October 2019 expiry**. Before it, an in-the-
    money short put settled in cash — the seller never received shares, so the
    second half of a wheel (own the stock, sell calls on it) simply did not
    exist as a mechanic.

From 2020-01-01 the whole sample sits inside one regime: assignment happens
only at expiry, and it delivers shares. That is the exact mechanic a wheel
assumes, so the window is a regime choice rather than the usual apology about
how far back the archive goes.

THE PRICE COLUMN IS A TRAP, AND IT IS NOT `close`
`close` is the day's **last traded price**. A stock-option strike that did not
trade today still carries one — from whenever it last traded, which may be
weeks ago and hundreds of rupees away. On 2020-01-02 the ACC 1220 CE shows
`close` 374.90 against a `settle` of 278.30, because the underlying had moved
and nobody had traded that strike since. `settle` is the exchange's daily
settlement mark and is computed for every listed strike whether it traded or
not, so it is the only column that is a price *as of today* across the chain.

That still does not make an untraded strike executable. `contracts` and
`open_interest` are kept on every row precisely so that a study has to state
its own liquidity bar rather than inherit a silent one.

AND `traded_value` ON AN OPTION ROW IS NOT PREMIUM TURNOVER
Both eras report an option's turnover on the **strike notional**, not on the
premium that changed hands: measured across the archive, `traded_value` divides
into `contracts * lot * strike` at a median of 1.01-1.02, and into
`contracts * lot * price` at 59-71. So a liquidity screen written as "at least
₹X crore traded" reads an option chain as roughly seventy times more liquid
than it is. Premium turnover has to be reconstructed as
`contracts * lot_size * settle`; `contracts` itself is the honest bar.

MONEYNESS IS MEASURED AGAINST THE **RAW** CASH CLOSE
Strikes are quoted in the price the share actually had, and NSE restrikes the
chain on a corporate action rather than carrying adjusted strikes. Comparing a
strike to a split-adjusted close would therefore report a 1:5 split as a 400%
gap. The underlying here is `daily_bars.close` — unadjusted, series EQ — which
is the series strikes are denominated in. `adj_factor` is carried alongside so
a study can *detect* an action inside a holding period instead of silently
mispricing it.

LOT SIZE COMES FROM THE FUTURES ROW, NEVER FROM THE OPTION ROW
The legacy era does not report lot size, and `nse_derivatives` recovers it from
`turnover / (contracts * price)`. On a future, whose price is thousands of
rupees, the rounding error is nil. On a deep out-of-the-money option trading at
₹0.05 the same division is nonsense. So lot size is joined from the symbol's
own `stock_future` row for that session, via `fo_universe`, and rows whose
symbol had no futures contract that day are dropped — on this exchange a name
with options but no future does not exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ...core import config
from ..sources import nse_derivatives

# Written one file per year rather than as a single parquet. The banded chain
# is ~20M rows; concatenating that in one go peaks at several times its own
# size, and nothing downstream wants all of it at once anyway.
CHAIN_DIR = config.NORMALIZED_DIR / "option_chain_stock"

CHAIN_COLUMNS = (
    "session", "symbol", "expiry", "strike", "option_type", "days_to_expiry",
    "settle", "close", "contracts", "traded_value", "open_interest",
    "lot_size", "lot_size_source", "underlying", "adj_factor", "moneyness",
    "source_era",
)


@dataclass(frozen=True)
class ChainConfig:
    """What the stored chain keeps. Widening any of these means a rebuild."""

    # A strike further than this from spot is never a wheel candidate and is
    # most of the file. 0.40 in log terms is ~ +49% / -33%.
    max_log_moneyness: float = 0.40
    # Open interest is the weakest possible liveness bar: it says a contract
    # exists and someone holds it. It is not a tradability claim — that bar is
    # the strategy's to set, on `contracts`.
    min_open_interest: float = 1.0


def _cash_close() -> pd.DataFrame:
    """Unadjusted EQ closes, the series strikes are denominated in."""
    bars = pd.read_parquet(
        config.NORMALIZED_DIR / "daily_bars_adj.parquet",
        columns=["symbol", "series", "date", "close_raw", "adj_factor"])
    bars = bars.loc[bars["series"] == "EQ"]
    out = bars[["symbol", "date", "close_raw", "adj_factor"]].rename(
        columns={"date": "session", "close_raw": "underlying"})
    return out.dropna(subset=["underlying"]).drop_duplicates(
        subset=["symbol", "session"], keep="last")


def _lot_sizes() -> pd.DataFrame:
    """Lot size per symbol-session, taken from the futures row."""
    universe = pd.read_parquet(
        config.NORMALIZED_DIR / "fo_universe.parquet",
        columns=["symbol", "session", "lot_size", "lot_size_source"])
    return universe.dropna(subset=["lot_size"]).drop_duplicates(
        subset=["symbol", "session"], keep="last")


def _flush(frames: list[pd.DataFrame], year: str, target: Path) -> int:
    if not frames:
        return 0
    block = pd.concat(frames, ignore_index=True).sort_values(
        ["session", "symbol", "expiry", "strike", "option_type"], kind="stable")
    target.mkdir(parents=True, exist_ok=True)
    block.reset_index(drop=True).to_parquet(target / f"chain_{year}.parquet",
                                            index=False)
    return len(block)


def build(cfg: ChainConfig | None = None, root: Path | None = None,
          out: Path | None = None, verbose: bool = True) -> Path:
    """Fold the daily option files into a banded, joined chain, by year."""
    cfg = cfg or ChainConfig()
    base = root or nse_derivatives.FO_OPTIONS_DIR
    target = out or CHAIN_DIR
    cash = _cash_close()
    lots = _lot_sizes()

    frames: list[pd.DataFrame] = []
    current = None
    total = 0
    paths = sorted(base.rglob("fo_*.parquet"))
    for index, path in enumerate(paths, start=1):
        year = path.parent.name
        if current is not None and year != current:
            total += _flush(frames, current, target)
            frames = []
        current = year
        day = pd.read_parquet(path)
        day = day.loc[day["instrument"] == "stock_option"]
        day = day.loc[day["strike"].notna() & day["option_type"].notna()]
        if day.empty:
            continue
        day = day.loc[day["open_interest"].fillna(0) >= cfg.min_open_interest]
        if day.empty:
            continue
        # The option row's own lot size is a turnover-derived fiction on cheap
        # strikes; the futures row's is not. Drop, never impute.
        day = day.drop(columns=["lot_size", "lot_size_source"])
        day = day.merge(lots, on=["symbol", "session"], how="inner")
        day = day.merge(cash, on=["symbol", "session"], how="inner")
        if day.empty:
            continue
        day["moneyness"] = np.log(day["strike"] / day["underlying"])
        day = day.loc[day["moneyness"].abs() <= cfg.max_log_moneyness]
        if day.empty:
            continue
        day["days_to_expiry"] = (day["expiry"] - day["session"]).dt.days
        frames.append(day[list(CHAIN_COLUMNS)])
        if verbose and index % 200 == 0:
            print(f"  chain {index}/{len(paths)} "
                  f"rows={total + sum(map(len, frames)):,}", flush=True)

    total += _flush(frames, current, target)
    if not total:
        raise RuntimeError("no option rows survived the chain filters")
    if verbose:
        print(f"  chain complete: {total:,} rows -> {target}", flush=True)
    return target


def load(start: date | None = None, end: date | None = None,
         path: Path | None = None, columns: list[str] | None = None
         ) -> pd.DataFrame:
    base = path or CHAIN_DIR
    files = sorted(base.glob("chain_*.parquet"))
    if not files:
        raise FileNotFoundError(f"no chain files under {base}")
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


def settlement_prices() -> pd.DataFrame:
    """Unadjusted EQ closes used for stock-option final settlement."""
    cash = _cash_close().rename(columns={"underlying": "price"})
    return cash[["symbol", "session", "price", "adj_factor"]]


def expiry_calendar(chain: pd.DataFrame) -> pd.DataFrame:
    """Every stock-option expiry, and the session it was last quoted on.

    Derived from the tape rather than from the last-Thursday rule. NSE has
    moved the expiry weekday more than once and shifts it around holidays, so a
    rule reproduces the calendar until it abruptly does not; the set of expiry
    dates that actually appear in the files cannot be wrong.
    """
    grouped = chain.groupby("expiry", as_index=False).agg(
        first_session=("session", "min"), last_session=("session", "max"),
        symbols=("symbol", "nunique"))
    return grouped.sort_values("expiry").reset_index(drop=True)


__all__ = ["CHAIN_COLUMNS", "CHAIN_DIR", "ChainConfig", "build",
           "expiry_calendar", "load", "settlement_prices"]
