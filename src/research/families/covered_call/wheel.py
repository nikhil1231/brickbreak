"""The wheel on Nifty: cash-secured puts, then covered calls, through an ETF.

THE STRATEGY, AND THE THING THAT MAKES IT AWKWARD ON THIS EXCHANGE
Hold cash. Sell an out-of-the-money NIFTY put against it. If the index settles
above the strike, keep the premium and sell another. If it settles below, you
are "assigned" — and here the Indian mechanics diverge from the American story
the wheel is usually told in.

NIFTY options are **cash-settled**. Assignment does not deliver anything. What
actually happens is that the exchange debits `(strike - settlement) x quantity`
from your account and the position vanishes. If you want to be long the index
afterwards, you have to go and buy it yourself, in the cash market, at whatever
price is available. The economics only match a delivered wheel if you do buy,
immediately, at the same close the option settled on.

So this simulator does exactly that: on an in-the-money put it pays the cash
difference and buys NIFTYBEES with the freed collateral at the same session's
ETF close. The combined outlay is the strike — the delivered-wheel answer —
except that the fill is an ETF price and the settlement was an index price, and
those two are not the same number. That basis is a real cost of running a wheel
on a cash-settled index, it is invisible in any description of the strategy, and
it is inside this result.

Coming back the other way is the same story in reverse: a called-away covered
call debits `(settlement - strike) x quantity` and leaves you still holding the
ETF, so the simulator sells it at that session's close to return to cash.

WHY THE OUT-OF-MARKET DRAG IS THE WHOLE ARGUMENT
Holding a cash-secured put is not holding the index. The collateral earns the
short rate; the position earns a premium; and the index's return over that week
belongs to somebody else. On an asset that drifts upward, being in cash by
construction for the periods after a rally has begun — you are put back into
cash precisely by the *call* being breached, which happens when the market rises
— is a structural cost that no amount of premium collection is guaranteed to
cover. `time_in_market` measures it directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from .engine import (CostModel, RBI_REPO_PATH, _step, pick_strike,
                     settlement_map)


@dataclass(frozen=True)
class WheelConfig:
    cadence: str = "weekly"                 # "weekly" | "monthly"
    strike_rule: str = "delta"              # "delta" | "otm"
    put_delta: float = 0.15
    call_delta: float = 0.15
    put_otm: float = 0.02
    call_otm: float = 0.02

    premium_column: str = "settle"
    min_contracts: float = 1.0

    cash_yield: str | float = "repo"
    funding_spread: float = 0.02

    starting_capital: float = 1.0
    costs: CostModel = field(default_factory=CostModel)
    start: date | None = None
    end: date | None = None

    def dte_band(self) -> tuple[int, int]:
        return (3, 10) if self.cadence == "weekly" else (21, 40)


def run(chain: pd.DataFrame, market: pd.DataFrame,
        cfg: WheelConfig | None = None) -> dict[str, pd.DataFrame]:
    """Simulate the wheel on a daily grid. `market` as in `engine.run`."""
    cfg = cfg or WheelConfig()
    if cfg.start is not None:
        chain = chain.loc[chain["session"] >= pd.Timestamp(cfg.start)]
        market = market.loc[market["session"] >= pd.Timestamp(cfg.start)]
    if cfg.end is not None:
        chain = chain.loc[chain["session"] <= pd.Timestamp(cfg.end)]
        market = market.loc[market["session"] <= pd.Timestamp(cfg.end)]

    market = market.dropna(subset=["proxy", "index"]).sort_values("session")
    sessions = market["session"].tolist()
    proxy = dict(zip(market["session"], market["proxy"]))
    index = dict(zip(market["session"], market["index"]))
    dividend = dict(zip(market["session"], market["div_yield"].fillna(1.25) / 100.0))

    low, high = cfg.dte_band()
    wanted = chain.loc[chain["days_to_expiry"].between(0, high + 5)]
    if cfg.cadence == "monthly":
        wanted = wanted.loc[(wanted["expiry_kind"] == "monthly")
                            | (wanted["days_to_expiry"] == 0)]
    by_session = {s: g for s, g in wanted.groupby("session", sort=False)}
    marks = chain.set_index(["session", "expiry", "strike", "option_type"])[
        "settle"].to_dict()
    settle_on = settlement_map(chain, sessions)
    data_end = max(sessions)

    cash = float(cfg.starting_capital)
    units = 0.0
    position: dict | None = None
    curve: list[dict] = []
    trades: list[dict] = []

    for i, session in enumerate(sessions):
        spot = index[session]
        if i > 0:
            days = (session - sessions[i - 1]).days
            rate = (_step(RBI_REPO_PATH, session)
                    if cfg.cash_yield == "repo" else float(cfg.cash_yield))
            if cash < 0:
                rate += cfg.funding_spread
            cash += cash * rate * days / 365.0

        # ---------- settle ----------
        if position is not None and session >= position["settles_on"]:
            kind = position["kind"]
            strike, qty = position["strike"], position["qty"]
            if kind == "PE":
                payoff = max(0.0, strike - spot) * qty
                cash -= payoff
                assigned = spot < strike
                if assigned:
                    # Cash settlement delivered nothing. Buy the index now, at
                    # the ETF's price, with the collateral that just came free.
                    value = spot * qty
                    cash -= value + cfg.costs.trade_etf(value, "buy")
                    units += value / proxy[session]
            else:
                payoff = max(0.0, spot - strike) * qty
                cash -= payoff
                assigned = spot > strike
                if assigned and units > 0:
                    value = units * proxy[session]
                    cash += value - cfg.costs.trade_etf(value, "sell")
                    units = 0.0
            trades.append({**position, "settled": session, "terminal": spot,
                           "payoff": payoff, "assigned": assigned})
            position = None

        # ---------- write ----------
        if position is None:
            book = by_session.get(session)
            if book is not None:
                book = book.loc[book["days_to_expiry"].between(low, high)]
                live = [e for e in sorted(book["expiry"].unique())
                        if pd.Timestamp(e) in settle_on
                        or pd.Timestamp(e) > data_end]
                if live:
                    expiry = pd.Timestamp(live[0])
                    book = book.loc[book["expiry"] == expiry]
                    years = max((expiry - session).days, 1) / 365.0
                    holding = units > 0
                    side = "CE" if holding else "PE"
                    leg = pick_strike(
                        book, side, spot, _step(RBI_REPO_PATH, session),
                        dividend.get(session, 0.0125), years, cfg.strike_rule,
                        cfg.call_delta if holding else cfg.put_delta,
                        cfg.call_otm if holding else cfg.put_otm,
                        cfg.premium_column, cfg.min_contracts)
                    if leg is not None:
                        strike = float(leg["strike"])
                        if holding:
                            qty = units * proxy[session] / spot
                        else:
                            # Cash-secured: the strike notional has to be there.
                            qty = max(cash, 0.0) / strike
                        if qty > 0:
                            gross = float(leg[cfg.premium_column])
                            net = gross * (1.0 - cfg.costs.premium_haircut) * qty
                            fee = cfg.costs.write_option(net, session)
                            cash += net - fee
                            position = {
                                "written": session, "expiry": expiry,
                                "settles_on": settle_on.get(expiry, expiry),
                                "kind": side, "strike": strike, "qty": qty,
                                "premium_gross": gross, "premium_net": net - fee,
                                "spot_at_write": spot,
                                "delta": float(leg.get("delta", np.nan)),
                                "dte": (expiry - session).days,
                            }

        # ---------- mark ----------
        liability = 0.0
        if position is not None:
            mark = marks.get((session, position["expiry"], position["strike"],
                              position["kind"]))
            if mark is None or not np.isfinite(mark):
                mark = (max(0.0, spot - position["strike"])
                        if position["kind"] == "CE"
                        else max(0.0, position["strike"] - spot))
            liability = mark * position["qty"]

        equity = cash + units * proxy[session] - liability
        curve.append({"session": session, "equity": equity, "cash": cash,
                      "shares": units * proxy[session],
                      "option_liability": liability, "index": spot,
                      "proxy": proxy[session], "in_market": float(units > 0),
                      "leg": position["kind"] if position else "",
                      "funding": min(cash, 0.0) / equity if equity > 0 else np.nan})

    return {"curve": pd.DataFrame(curve), "trades": pd.DataFrame(trades)}


def wheel_stats(trades: pd.DataFrame, curve: pd.DataFrame) -> dict:
    if trades.empty:
        return {}
    puts = trades.loc[trades["kind"] == "PE"]
    calls = trades.loc[trades["kind"] == "CE"]
    notional = trades["qty"] * trades["spot_at_write"]
    years = ((pd.to_datetime(curve["session"]).iloc[-1]
              - pd.to_datetime(curve["session"]).iloc[0]).days / 365.25)
    return {
        "legs": int(len(trades)),
        "puts_written": int(len(puts)),
        "calls_written": int(len(calls)),
        "put_assignment_rate": float(puts["assigned"].mean()) if len(puts) else float("nan"),
        "call_assignment_rate": float(calls["assigned"].mean()) if len(calls) else float("nan"),
        "time_in_market": float(curve["in_market"].mean()),
        "annualised_premium_pct": float((trades["premium_net"] / notional).sum() / years),
        "etf_round_trips": int(calls["assigned"].sum()),
        "peak_funding_pct_of_equity": float(curve["funding"].min()),
    }


__all__ = ["WheelConfig", "run", "wheel_stats"]
