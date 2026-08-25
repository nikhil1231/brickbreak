"""The point-in-time stock-futures universe, and what a lot actually costs.

WHY THE UNIVERSE MOVED
The lab's equity work screened a ₹3-25 crore median-turnover band, an
illiquidity prior that made sense for multi-day cash positions. It does not
survive contact with the account that has to trade it: an NRI cannot square off
intraday in the cash segment and cannot short cash equities at all, so every
intraday or bearish claim is executable only in F&O. NSE's F&O eligibility floor
sits far above ₹25 crore of turnover, so the overlap between the old universe and
the tradable one is essentially empty.

This module rebuilds the universe from the only source that knows it exactly:
the session's own derivatives bhavcopy. A symbol had a stock futures contract on
a session if and only if a `stock_future` row for it appears in that session's
file. Names that left F&O in 2022 are present in 2021 and absent from 2023,
which is what a current "F&O list" download can never reconstruct.

WHAT THIS BUYS BEYOND ELIGIBILITY
  * **Real futures prices.** PLAN.md §14 requires a futures claim to be tested
    on contracts, not on the cash series standing in for them. Near-month OHLC
    and settlement come from here.
  * **Open interest.** The nearest thing the tape offers to who is on the other
    side. OI building through a break and holding across the retest is a
    participation statement; price alone cannot make one.
  * **Lot size, and therefore the truth about position sizing.** On a ₹5-10 lakh
    book the binding constraint is not liquidity but quantisation: one lot is
    indivisible. `lot_notional_report` measures what a lot actually cost in each
    era rather than assuming, which matters because SEBI raised the minimum
    contract value late in the sample — so a backtest sized on historical lots
    understates the constraint the account faces today.

THE ROLL IS NOT COSMETIC
`near_expiry` is the nearest contract that has not yet expired. On expiry day
that contract is settling, so `is_expiry_session` marks it and `next_expiry`
carries the contract a position would actually roll into. A study that holds
through an expiry without acknowledging the roll is pricing a contract that
ceased to exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ...core import config
from ..sources import nse_derivatives

UNIVERSE_PATH = config.NORMALIZED_DIR / "fo_universe.parquet"

UNIVERSE_COLUMNS = (
    "symbol", "session", "near_expiry", "next_expiry", "is_expiry_session",
    "days_to_expiry", "lot_size", "lot_size_source", "futures_open",
    "futures_high", "futures_low", "futures_close", "futures_settle",
    "underlying_close", "contracts", "traded_value", "open_interest",
    "change_in_open_interest", "oi_notional", "lot_notional", "source_era",
)


class UniverseError(RuntimeError):
    pass


@dataclass(frozen=True)
class UniverseConfig:
    """Frozen liquidity priors for the tradable subset.

    These are declared economic priors, not fitted thresholds. `min_lot_turnover`
    is expressed in lots rather than rupees because what a small book needs is
    the ability to get one lot in and out without being the market.
    """

    min_contracts_per_session: int = 500
    min_traded_value_cr: float = 5.0
    min_sessions_in_window: int = 15
    window_sessions: int = 20

    def __post_init__(self) -> None:
        if self.min_contracts_per_session < 0 or self.min_traded_value_cr < 0:
            raise ValueError("liquidity floors cannot be negative")
        if self.window_sessions < 1:
            raise ValueError("rolling window must span a session")
        if self.min_sessions_in_window > self.window_sessions:
            raise ValueError("cannot require more sessions than the window holds")


def build(start: date | None = None, end: date | None = None,
          root: Path | None = None) -> pd.DataFrame:
    """Collapse the contract-level archive to one row per symbol-session.

    The near-month contract represents the symbol: it carries essentially all
    the liquidity, and it is what a directional position would actually hold.
    """
    contracts = nse_derivatives.load_range(
        start=start, end=end, root=root, instruments=("stock_future",))
    if contracts.empty:
        raise UniverseError(
            "no stock-futures rows on disk; run nse_derivatives.sync first")
    work = contracts.copy()
    work["session"] = pd.to_datetime(work["session"]).dt.normalize()
    work["expiry"] = pd.to_datetime(work["expiry"]).dt.normalize()
    work = work.loc[work["expiry"].ge(work["session"])]
    if work.empty:
        raise UniverseError("every stock-futures row expired before its session")

    work = work.sort_values(["symbol", "session", "expiry"], kind="stable")
    near = work.groupby(["symbol", "session"], sort=False).head(1).copy()

    # The contract a position rolls into, taken from the same session's file so
    # that nothing about the future leaks in.
    ranked = work.groupby(["symbol", "session"], sort=False)["expiry"]
    second = work.loc[ranked.rank(method="first") == 2,
                      ["symbol", "session", "expiry"]].rename(
                          columns={"expiry": "next_expiry"})
    near = near.merge(second, on=["symbol", "session"], how="left")

    near = near.rename(columns={
        "expiry": "near_expiry", "open": "futures_open", "high": "futures_high",
        "low": "futures_low", "close": "futures_close", "settle": "futures_settle",
    })
    near["is_expiry_session"] = near["near_expiry"].eq(near["session"])
    near["days_to_expiry"] = (near["near_expiry"] - near["session"]).dt.days
    near["lot_notional"] = near["lot_size"] * near["futures_close"]
    near["oi_notional"] = near["open_interest"] * near["futures_close"]
    for column in UNIVERSE_COLUMNS:
        if column not in near.columns:
            near[column] = np.nan
    return near[list(UNIVERSE_COLUMNS)].sort_values(
        ["session", "symbol"], kind="stable").reset_index(drop=True)


def save(universe: pd.DataFrame, path: Path | None = None) -> Path:
    target = path or UNIVERSE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    universe.to_parquet(target, index=False)
    return target


def load(path: Path | None = None) -> pd.DataFrame:
    target = path or UNIVERSE_PATH
    if not target.exists():
        raise UniverseError(f"F&O universe not built at {target}")
    return pd.read_parquet(target)


def tradable(universe: pd.DataFrame,
             config_: UniverseConfig | None = None) -> pd.DataFrame:
    """Flag symbol-sessions whose *lagged* activity clears the liquidity floors.

    Every input is shifted by one session. A symbol that becomes liquid today is
    not selectable today, because that fact was not available when the decision
    would have been taken.
    """
    cfg = config_ or UniverseConfig()
    work = universe.sort_values(["symbol", "session"], kind="stable").copy()
    grouped = work.groupby("symbol", sort=False)
    lagged_contracts = grouped["contracts"].shift(1)
    lagged_value = grouped["traded_value"].shift(1)

    def rolling(series: pd.Series, threshold: float) -> pd.Series:
        return (series.ge(threshold).groupby(work["symbol"], sort=False)
                .transform(lambda values: values.rolling(
                    cfg.window_sessions, min_periods=1).sum()))

    active_contracts = rolling(lagged_contracts, cfg.min_contracts_per_session)
    active_value = rolling(lagged_value, cfg.min_traded_value_cr * 1e7)
    work["lagged_median_contracts"] = (
        lagged_contracts.groupby(work["symbol"], sort=False).transform(
            lambda values: values.rolling(cfg.window_sessions, min_periods=1).median()))
    work["lagged_median_traded_value"] = (
        lagged_value.groupby(work["symbol"], sort=False).transform(
            lambda values: values.rolling(cfg.window_sessions, min_periods=1).median()))
    work["tradable"] = (
        active_contracts.ge(cfg.min_sessions_in_window)
        & active_value.ge(cfg.min_sessions_in_window))
    return work


def membership_report(universe: pd.DataFrame) -> dict[str, Any]:
    """How many names had futures, by year — the shape of the real universe."""
    work = universe.copy()
    work["year"] = pd.to_datetime(work["session"]).dt.year
    by_year = work.groupby("year").agg(
        sessions=("session", "nunique"), symbols=("symbol", "nunique"),
        symbol_sessions=("symbol", "size")).reset_index()
    by_year["mean_symbols_per_session"] = (
        by_year["symbol_sessions"] / by_year["sessions"]).round(1)
    entries = work.groupby("symbol")["session"].agg(["min", "max"])
    return {
        "sessions": int(work["session"].nunique()),
        "distinct_symbols": int(work["symbol"].nunique()),
        "symbol_sessions": int(len(work)),
        "first_session": str(work["session"].min().date()),
        "last_session": str(work["session"].max().date()),
        "by_year": by_year.to_dict("records"),
        "symbols_present_throughout": int(
            (entries["min"].eq(work["session"].min())
             & entries["max"].eq(work["session"].max())).sum()),
    }


def lot_notional_report(universe: pd.DataFrame,
                        capital_lakh: tuple[float, ...] = (5.0, 10.0),
                        margin_fraction: float = 0.18) -> dict[str, Any]:
    """What one lot costs, and therefore how many positions fit.

    `margin_fraction` is a stated assumption, not a measurement: SPAN plus
    exposure for stock futures typically lands near a fifth of notional, but it
    is symbol-specific and changes with volatility. It is reported alongside the
    result so the sensitivity is visible rather than buried.
    """
    work = universe.loc[universe["lot_notional"].gt(0)].copy()
    work["year"] = pd.to_datetime(work["session"]).dt.year
    rows = []
    for year, group in work.groupby("year"):
        median = float(group["lot_notional"].median())
        rows.append({
            "year": int(year),
            "median_lot_notional": round(median, 0),
            "p25_lot_notional": round(float(group["lot_notional"].quantile(0.25)), 0),
            "p75_lot_notional": round(float(group["lot_notional"].quantile(0.75)), 0),
            "median_margin": round(median * margin_fraction, 0),
            "reported_lot_share": round(
                float(group["lot_size_source"].eq("reported").mean()), 4),
            **{
                f"concurrent_positions_at_{int(capital)}L": int(
                    (capital * 100_000) // max(median * margin_fraction, 1))
                for capital in capital_lakh
            },
        })
    return {"margin_fraction_assumed": margin_fraction, "by_year": rows}


__all__ = [
    "UNIVERSE_COLUMNS", "UNIVERSE_PATH", "UniverseConfig", "UniverseError",
    "build", "load", "lot_notional_report", "membership_report", "save",
    "tradable",
]
