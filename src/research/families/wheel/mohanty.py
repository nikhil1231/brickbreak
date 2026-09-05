"""H069: the user's 33/33/34 staggered-stock covered-call rule.

The attribution is deliberately narrow. The public Mohanty interview page says
"staggered buying" but does not publish these thresholds; the user supplied
them in a follow-up. This module tests that supplied operationalisation.

One full-target call is written after only the first stock tranche is bought.
The uncovered remainder is not renamed away: it is marked daily, and the curve
reports both uncovered notional and negative cash needed when gap-up tranche
fills occur. SPAN is not reconstructed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .engine import (CostModel, PreparedWheelChain, RBI_REPO_PATH, _pick_lagged_strike,
                     _step)


@dataclass(frozen=True)
class TrancheConfig:
    symbols: tuple[str, ...]
    call_otm: float = .10
    initial_fraction: float = .33
    midpoint_fraction: float = .33
    final_fraction: float = .34
    min_strike_contracts: float = 250.0
    premium_column: str = "close"
    premium_haircut: float = .10
    cash_yield: str | float = "repo"
    funding_spread: float = .02
    starting_capital: float = 1.0
    costs: CostModel = field(default_factory=CostModel)

    def __post_init__(self):
        total = self.initial_fraction + self.midpoint_fraction + self.final_fraction
        if not np.isclose(total, 1.0):
            raise ValueError("tranche fractions must sum to one")


def _rate(cfg: TrancheConfig, stamp, cash: float) -> float:
    base = (_step(RBI_REPO_PATH, pd.Series([stamp]))[0]
            if cfg.cash_yield == "repo" else float(cfg.cash_yield))
    return base if cash >= 0 else base + cfg.funding_spread


def _buy(state: dict, fraction: float, spot: float, cfg: TrancheConfig,
         stamp, trades: list[dict], reason: str) -> None:
    target = state["target_qty"] * fraction
    remaining = state["target_qty"] - state["shares"]
    qty = min(target, max(remaining, 0.0))
    if qty <= 1e-12:
        return
    value = qty * spot
    fee = float(cfg.costs.cash_buy(value))
    state["cash"] -= value + fee
    state["shares"] += qty
    trades.append({"session": stamp, "symbol": state["symbol"],
                   "kind": "stock_buy", "reason": reason, "qty": qty,
                   "price": spot, "value": value, "fee": fee})


def _adjust(state: dict, factor: float) -> None:
    previous = state.get("adj_factor")
    if previous is None or not np.isfinite(previous):
        state["adj_factor"] = factor
        return
    ratio = factor / previous
    if not np.isclose(ratio, 1.0):
        state["shares"] *= ratio
        state["target_qty"] *= ratio
        if state.get("strike") is not None:
            state["strike"] /= ratio
        if state.get("entry_spot") is not None:
            state["entry_spot"] /= ratio
    state["adj_factor"] = factor


def _mark(day: pd.DataFrame, strike: float, fallback: float) -> float:
    if day.empty:
        return fallback
    calls = day.loc[(day["option_type"] == "CE") & (day["settle"] >= 0)]
    if calls.empty:
        return fallback
    row = calls.iloc[(calls["strike"] - strike).abs().argmin()]
    # A nearest strike after a corporate-action adjustment should be exact to
    # exchange rounding. A remote strike would be a different contract.
    if abs(float(row["strike"]) / strike - 1.0) > .015:
        return fallback
    return float(row["settle"])


def run(chain: pd.DataFrame, prices: pd.DataFrame, tape: PreparedWheelChain,
        cfg: TrancheConfig, *, staged: bool = True) -> dict[str, pd.DataFrame]:
    """Run fixed symbol sleeves and aggregate them on the daily cash grid."""
    symbols = set(cfg.symbols)
    chain = chain.loc[chain["symbol"].isin(symbols)].copy()
    prices = prices.loc[prices["symbol"].isin(symbols)].copy()
    price_by_day = {pd.Timestamp(day): block.set_index("symbol")
                    for day, block in prices.groupby("session")}
    option_by_key = {(pd.Timestamp(day), symbol, pd.Timestamp(expiry)): block
                     for (day, symbol, expiry), block in
                     chain.groupby(["session", "symbol", "expiry"], sort=False)}

    sleeve = cfg.starting_capital / len(cfg.symbols)
    states = {symbol: {"symbol": symbol, "cash": sleeve, "shares": 0.0,
                       "target_qty": 0.0, "stage": 0, "strike": None,
                       "entry_spot": None, "expiry": None,
                       "option_mark": 0.0, "adj_factor": None}
              for symbol in cfg.symbols}
    trades: list[dict] = []
    curve: list[dict] = []
    last_session = None

    for entry, contract_expiry, settlement in tape.pairs:
        execution = tape.by_session.get(entry, pd.DataFrame())
        selection = tape.prior_by_session.get(entry, pd.DataFrame())
        if execution.empty or selection.empty:
            continue
        execution = execution.loc[execution["expiry"] == contract_expiry]

        # Set each sleeve's new call at the entry close. A missing liquid call
        # means hold the current shares naked for the cycle, not invent a fill.
        for symbol, state in states.items():
            state["strike"] = None
            state["expiry"] = None
            state["option_mark"] = 0.0
            day_price = price_by_day.get(pd.Timestamp(entry))
            if day_price is None or symbol not in day_price.index:
                continue
            spot = float(day_price.loc[symbol, "price"])
            factor = float(day_price.loc[symbol, "adj_factor"])
            _adjust(state, factor)
            old = selection.loc[selection["symbol"] == symbol]
            live = execution.loc[execution["symbol"] == symbol]
            if old.empty or live.empty:
                continue
            ref = float(old["underlying"].iloc[0])
            option = _pick_lagged_strike(
                old, live, "CE", ref * np.exp(cfg.call_otm),
                cfg.min_strike_contracts, cfg.premium_column)
            if option is None:
                continue
            if state["shares"] <= 1e-12:
                equity = state["cash"]
                state["target_qty"] = equity / spot
                state["stage"] = 0
                state["entry_spot"] = spot
                first = cfg.initial_fraction if staged else 1.0
                _buy(state, first, spot, cfg, entry, trades, "initial")
                state["stage"] = 1 if staged else 3
            state["strike"] = float(option["strike"])
            state["entry_spot"] = spot
            state["expiry"] = pd.Timestamp(contract_expiry)
            state["option_mark"] = float(option["settle"])
            gross = float(option[cfg.premium_column]) * state["target_qty"]
            received = gross * (1.0 - cfg.premium_haircut)
            fee = float(cfg.costs.option_sale(
                np.array([received]), pd.Series([entry]))[0])
            state["cash"] += received - fee
            trades.append({"session": entry, "symbol": symbol,
                           "kind": "call_write", "reason": "monthly",
                           "qty": state["target_qty"],
                           "price": float(option[cfg.premium_column]),
                           "strike": state["strike"], "value": received,
                           "fee": fee})

        sessions = sorted(day for day in price_by_day
                          if pd.Timestamp(entry) <= day <= pd.Timestamp(settlement)
                          and (last_session is None or day > last_session))
        for session in sessions:
            if last_session is not None:
                days = (session - last_session).days
                for state in states.values():
                    rate = _rate(cfg, last_session, state["cash"])
                    state["cash"] += state["cash"] * rate * days / 365.0
            day_prices = price_by_day[session]
            total_equity = total_cash = total_stock = total_liability = 0.0
            total_uncovered = 0.0
            for symbol, state in states.items():
                if symbol not in day_prices.index:
                    continue
                spot = float(day_prices.loc[symbol, "price"])
                factor = float(day_prices.loc[symbol, "adj_factor"])
                _adjust(state, factor)
                strike = state.get("strike")
                if staged and strike is not None:
                    midpoint = state["entry_spot"] + .5 * (
                        strike - state["entry_spot"])
                    if state["stage"] < 2 and spot >= midpoint:
                        _buy(state, cfg.midpoint_fraction, spot, cfg, session,
                             trades, "midpoint")
                        state["stage"] = 2
                    if state["stage"] < 3 and spot >= strike:
                        _buy(state, cfg.final_fraction, spot, cfg, session,
                             trades, "strike")
                        state["stage"] = 3

                liability = 0.0
                if strike is not None:
                    options = option_by_key.get(
                        (session, symbol, state["expiry"]), pd.DataFrame())
                    fallback = max(spot - strike, 0.0)
                    state["option_mark"] = _mark(
                        options, strike, max(state["option_mark"], fallback))
                    liability = state["option_mark"] * state["target_qty"]

                if session == pd.Timestamp(settlement) and strike is not None:
                    if spot > strike:
                        # The terminal close crosses the final trigger first,
                        # so the shares exist before physical delivery.
                        missing = state["target_qty"] - state["shares"]
                        if missing > 1e-9:
                            _buy(state, missing / state["target_qty"], spot,
                                 cfg, session, trades, "terminal_cover")
                        value = strike * state["target_qty"]
                        fee = float(cfg.costs.physical(value, "sell"))
                        state["cash"] += value - fee
                        state["shares"] = 0.0
                        state["target_qty"] = 0.0
                        state["stage"] = 0
                        trades.append({"session": session, "symbol": symbol,
                                       "kind": "call_assignment",
                                       "reason": "itm", "qty": 0.0,
                                       "price": strike, "strike": strike,
                                       "value": value, "fee": fee})
                    else:
                        trades.append({"session": session, "symbol": symbol,
                                       "kind": "call_expiry",
                                       "reason": "otm", "qty": 0.0,
                                       "price": 0.0, "strike": strike,
                                       "value": 0.0, "fee": 0.0})
                    state["strike"] = None
                    state["expiry"] = None
                    state["option_mark"] = 0.0
                    liability = 0.0

                stock = state["shares"] * spot
                uncovered = (max(state["target_qty"] - state["shares"], 0.0)
                             * spot if state.get("strike") is not None else 0.0)
                total_cash += state["cash"]
                total_stock += stock
                total_liability += liability
                total_uncovered += uncovered
                total_equity += state["cash"] + stock - liability
            curve.append({"session": session, "equity": total_equity,
                          "cash": total_cash, "shares": total_stock,
                          "option_liability": total_liability,
                          "uncovered_notional": total_uncovered,
                          "positions": sum(s["shares"] > 0 for s in states.values()),
                          "open_calls": sum(s.get("strike") is not None
                                            for s in states.values())})
            last_session = session

    result = pd.DataFrame(curve).drop_duplicates("session", keep="last")
    result["funding_pct"] = result["cash"].clip(upper=0) / cfg.starting_capital
    result["uncovered_pct"] = result["uncovered_notional"] / cfg.starting_capital
    result["uncovered_pct_equity"] = (
        result["uncovered_notional"] / result["equity"])
    return {"curve": result.reset_index(drop=True),
            "trades": pd.DataFrame(trades)}


__all__ = ["TrancheConfig", "run"]
