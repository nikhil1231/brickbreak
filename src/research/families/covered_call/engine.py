"""Weekly (or monthly) covered calls on Nifty, held through a real ETF.

THE STRATEGY UNDER TEST
Hold Nifty exposure. Every week, at the close of the expiry session, write one
out-of-the-money NIFTY call against it and hold that call to its expiry. If the
index settles below the strike the call expires worthless and the premium is
kept; if it settles above, the difference is paid in cash and the equity leg's
gain above the strike is handed over. Repeat.

WHY THIS IS *NOT* THE WHEEL, AND WHY THAT SIMPLIFIES THE EVIDENCE
NIFTY options are **cash-settled**. Nothing is ever delivered, so there is no
assignment, no share position to inherit, and none of the 0.25%-of-notional
physical-settlement brokerage that dominated the stock-option version of this
question. A covered call here is a long position plus a short option, and it
stays that way all the way through. The consequence for a backtest is unusually
good: the only modelled price is the premium received on the day the call is
written. The terminal value of every option is `max(0, index_close - strike)`,
computed from the index, which cannot fail to trade.

THE EQUITY LEG IS AN ETF, AND THAT IS A MEASUREMENT, NOT A DETAIL
You cannot buy the Nifty 50. The strategy as posed holds Nifty BeES, so the
equity leg here is the **actual traded close of NIFTYBEES**, unadjusted, and the
option settles on the **index**. The gap between them is therefore inside the
result rather than assumed away — which matters, because it is not always small.
On 2020-03-18 NIFTYBEES closed 5.5% away from its own trailing relationship to
the index, and on 2024-06-04 (election day) 3.0% away. A backtest that holds
"the index" and settles on "the index" would show neither.

`proxy="index_tr"` runs the same strategy against a frictionless total-return
index instead, so the ETF's contribution can be read off as the difference.

AN EXPIRY DATE IS NOT ALWAYS A TRADING SESSION
Five of the 380 expiries in this sample fall on days the market never opened —
2023-03-30 and 2023-04-06 among them — because NSE lists a contract for a
Thursday and then a holiday is declared, moving the last trading day to the
Wednesday without renaming the contract. Settling on `session == expiry` means
those contracts never settle: the position freezes, blocks every subsequent
write, and the backtest silently becomes buy-and-hold-plus-a-stuck-short-call
from that day on. It is a quiet failure — the equity curve keeps moving, the
metrics keep computing, and only the count of contracts written gives it away.

So the settlement session is taken from the tape: for each expiry, the last
session on which that contract is still quoted. When the expiry is a session
that *is* the expiry; when it is not, it is the Wednesday the contract really
died. A contract whose last quote is the final session of the archive has not
expired at all and is left open and marked, not settled early.

WHAT THE DAILY GRID BUYS
The chain carries a settlement mark for every listed strike on every session, so
the short call is marked daily and the equity curve is daily. Two things follow
that a weekly-close simulation cannot say:

  * **Drawdown is honest.** A weekly grid cannot see a mid-week fall.
  * **Margin is visible.** A covered call is never *insolvent* when the market
    rallies — the equity leg gains more than the short call loses, as long as
    the strike is above the entry level — but the option loss is a daily cash
    debit while the ETF gain is unrealised. So cash goes negative and has to be
    funded. `peak_funding` reports how deep, as a fraction of equity, which is
    the buffer an operator actually has to hold and the number most descriptions
    of this strategy omit.

WHAT IS DELIBERATELY NOT MODELLED, AND WHY
  * **SPAN margin.** Exchange margin on a short index call is a risk-array
    computation this project cannot reproduce from daily files. What is modelled
    instead is the cash it costs — the daily mark-to-market — which is the part
    that actually binds. A short call against an ETF is *not* recognised as a
    hedged position by the exchange: the ETF cannot be given up as the deliverable
    for an index contract, so the position attracts naked short-call margin and
    the ETF only helps as pledged collateral.
  * **Tax.** Option writing is non-speculative business income and ETF sales are
    capital gains, at rates that depend on the operator. Nothing here is
    after-tax; the comparison is pre-tax on both sides, which is the neutral
    choice because buy-and-hold defers its tax while this strategy realises
    income every week. That asymmetry is real and is stated in the findings
    rather than guessed at with a made-up rate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from . import blackscholes as bs

# RBI repo, hand-entered from the published decision dates. It is what pledged
# collateral or a liquid fund earns, and what unfunded cash costs before the
# broker's spread.
RBI_REPO_PATH: tuple[tuple[str, float], ...] = (
    ("2020-01-01", 0.0515), ("2020-03-27", 0.0440), ("2020-05-22", 0.0400),
    ("2022-05-04", 0.0440), ("2022-06-08", 0.0490), ("2022-08-05", 0.0540),
    ("2022-09-30", 0.0590), ("2022-12-07", 0.0625), ("2023-02-08", 0.0650),
    ("2025-02-07", 0.0625), ("2025-04-09", 0.0600), ("2025-06-06", 0.0550),
    ("2025-12-05", 0.0525),
)

# STT on the *sale* of an option, as a fraction of premium. Note what is absent:
# STT on an exercised option (0.125%, and 0.15% from April 2026) is charged on
# intrinsic value to the *purchaser*. The writer of a covered call never pays
# it, which is a real and frequently mis-stated asymmetry.
STT_OPTION_SALE: tuple[tuple[str, float], ...] = (
    ("2020-01-01", 0.000500), ("2023-04-01", 0.000625), ("2024-10-01", 0.001000),
)

# NSE transaction charge on options, on premium.
EXCHANGE_OPTION: tuple[tuple[str, float], ...] = (
    ("2020-01-01", 0.000500), ("2024-10-01", 0.000495),
)


def _step(path: tuple[tuple[str, float], ...], stamp) -> float:
    edges = [pd.Timestamp(d) for d, _ in path]
    values = [v for _, v in path]
    stamp = pd.Timestamp(stamp)
    out = values[0]
    for edge, value in zip(edges, values):
        if stamp >= edge:
            out = value
    return out


@dataclass(frozen=True)
class CostModel:
    """Frictions, each on its own base. Defaults are a discount broker's."""

    # Both of these are step functions of date, not constants — STT on option
    # premium doubled inside this sample. They live here rather than as module
    # constants so a sensitivity run, or a test, can turn them off.
    stt_option_path: tuple[tuple[str, float], ...] = STT_OPTION_SALE
    exchange_option_path: tuple[tuple[str, float], ...] = EXCHANGE_OPTION
    sebi_fee: float = 0.000001              # ₹10 per crore
    gst: float = 0.18
    stamp_option_buy: float = 0.00003       # buyer only; bites on a buy-back
    brokerage_per_order: float = 0.0        # ₹ flat, per order

    # The spread, which no archive records. NIFTY weeklies near the money are
    # among the tightest contracts anywhere — a tick or two on a premium of tens
    # of rupees — so 1% of premium is the base rather than the 5% a stock chain
    # would need. The whole result is re-run across a grid of it regardless.
    premium_haircut: float = 0.01

    # Equity-leg frictions. An ETF is a unit of an equity-oriented fund, so STT
    # on purchase is nil and on sale 0.001% — not the 0.1% a share pays.
    etf_stt_sale: float = 0.00001
    etf_exchange: float = 0.0000297
    etf_stamp_buy: float = 0.00015

    def write_option(self, premium_value: float, stamp) -> float:
        variable = _step(self.exchange_option_path, stamp) + self.sebi_fee
        return premium_value * (_step(self.stt_option_path, stamp) + variable
                                + self.gst * variable) + self.brokerage_per_order

    def buy_back_option(self, premium_value: float, stamp) -> float:
        variable = _step(self.exchange_option_path, stamp) + self.sebi_fee
        return premium_value * (variable + self.gst * variable
                                + self.stamp_option_buy) + self.brokerage_per_order

    def trade_etf(self, value: float, side: str) -> float:
        variable = self.etf_exchange + self.sebi_fee
        rate = variable + self.gst * variable
        rate += self.etf_stamp_buy if side == "buy" else self.etf_stt_sale
        return value * rate


@dataclass(frozen=True)
class CoveredCallConfig:
    cadence: str = "weekly"                 # "weekly" | "monthly"
    strike_rule: str = "delta"              # "delta" | "otm"
    target_delta: float = 0.15
    otm: float = 0.02                       # log-moneyness when strike_rule="otm"

    premium_column: str = "settle"
    min_contracts: float = 1.0

    # Close the short call early once this fraction of the premium has decayed,
    # then write the next expiry. None holds every call to expiry.
    profit_take: float | None = None

    proxy: str = "NIFTYBEES"                # "NIFTYBEES" | "index_tr"
    cash_yield: str | float = "repo"
    funding_spread: float = 0.02            # paid on negative cash

    # Whole lots against a real book, or fractional to measure the overlay
    # cleanly. Lot size cancels out of the return either way; it only decides
    # whether a book of this size can hold the position at all.
    starting_capital: float = 1.0
    quantise_lots: bool = False

    costs: CostModel = field(default_factory=CostModel)
    start: date | None = None
    end: date | None = None

    def dte_band(self) -> tuple[int, int]:
        return (3, 10) if self.cadence == "weekly" else (21, 40)


def settlement_map(chain: pd.DataFrame, sessions) -> dict:
    """When each contract actually dies.

    See the module docstring: an expiry date is not always a session, and
    settling on `session == expiry` freezes the book the first time NSE moves an
    expiry off a holiday. A contract still quoted on the final session of the
    archive has not expired and is deliberately absent from this map.
    """
    session_set = set(sessions)
    data_end = max(sessions)
    out: dict = {}
    for expiry_date, last in chain.groupby("expiry")["session"].max().items():
        expiry_date = pd.Timestamp(expiry_date)
        if expiry_date in session_set:
            out[expiry_date] = expiry_date
        elif expiry_date < data_end:
            out[expiry_date] = pd.Timestamp(last)
    return out


def pick_strike(book: pd.DataFrame, option_type: str, spot: float, rate: float,
                div_yield: float, years: float, strike_rule: str,
                target_delta: float, otm: float, premium_column: str,
                min_contracts: float):
    """The listed strike nearest the target that actually traded that session.

    `target_delta` is a magnitude: a put's delta is negative, and matching on
    the absolute value is what "the 0.15-delta put" means everywhere it is said.
    """
    side = book.loc[(book["option_type"] == option_type)
                    & (book["contracts"] >= min_contracts)
                    & (book[premium_column] > 0)]
    side = (side.loc[side["strike"] > spot] if option_type == "CE"
            else side.loc[side["strike"] < spot])
    if side.empty:
        return None
    if strike_rule == "otm":
        sign = 1.0 if option_type == "CE" else -1.0
        target = spot * np.exp(sign * otm)
        return side.iloc[(side["strike"] - target).abs().argmin()]
    deltas = bs.chain_delta(side["strike"].to_numpy(),
                            side[premium_column].to_numpy(),
                            spot, rate, div_yield, years, option_type)
    valid = np.isfinite(deltas)
    if not valid.any():
        return None
    candidates = side.loc[valid].copy()
    candidates["delta"] = deltas[valid]
    order = (np.abs(candidates["delta"]) - abs(target_delta)).abs()
    return candidates.iloc[int(np.argmin(order.to_numpy()))]


def _pick_strike(book: pd.DataFrame, cfg: CoveredCallConfig, spot: float,
                 rate: float, div_yield: float, years: float):
    return pick_strike(book, "CE", spot, rate, div_yield, years,
                       cfg.strike_rule, cfg.target_delta, cfg.otm,
                       cfg.premium_column, cfg.min_contracts)


def run(chain: pd.DataFrame, market: pd.DataFrame,
        cfg: CoveredCallConfig | None = None) -> dict[str, pd.DataFrame]:
    """Simulate the overlay on a daily grid.

    `chain`  — `index_option_chain.load()` output for one index.
    `market` — one row per session with `session`, `proxy` (the tradable price
               of the equity leg), `index` (the level options settle on) and
               `div_yield` (per cent, for the delta label).
    """
    cfg = cfg or CoveredCallConfig()
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

    settle_on = settlement_map(chain, sessions)
    data_end = max(sessions)
    # Daily settlement mark for the specific contract we are short.
    marks = chain.set_index(["session", "expiry", "strike", "option_type"])[
        "settle"].to_dict()
    lot_by_session = dict(zip(chain["session"], chain["lot_size"]))

    capital = float(cfg.starting_capital)
    first = sessions[0]
    units = capital / proxy[first]
    entry_cost = cfg.costs.trade_etf(capital, "buy")
    cash = -entry_cost
    position: dict | None = None
    last_mark = 0.0

    curve: list[dict] = []
    trades: list[dict] = []

    for i, session in enumerate(sessions):
        spot = index[session]
        # --- accrue interest on the ledger for the calendar gap ---
        if i > 0:
            days = (session - sessions[i - 1]).days
            rate = (_step(RBI_REPO_PATH, session)
                    if cfg.cash_yield == "repo" else float(cfg.cash_yield))
            if cash < 0:
                rate += cfg.funding_spread
            cash += cash * rate * days / 365.0

        # --- settle an expiring call on the index close ---
        if position is not None and session >= position["settles_on"]:
            payoff = max(0.0, spot - position["strike"]) * position["qty"]
            cash -= payoff
            trades.append({**position, "settled": session, "terminal": spot,
                           "payoff": payoff, "closed": "expiry",
                           "itm": spot > position["strike"]})
            position = None
            last_mark = 0.0

        # --- optional early close once the premium has decayed ---
        elif position is not None and cfg.profit_take is not None:
            mark = marks.get((session, position["expiry"], position["strike"],
                              "CE"))
            if mark is not None and np.isfinite(mark):
                if mark <= (1.0 - cfg.profit_take) * position["premium_gross"]:
                    value = mark * (1.0 + cfg.costs.premium_haircut) * position["qty"]
                    cash -= value + cfg.costs.buy_back_option(value, session)
                    trades.append({**position, "settled": session,
                                   "terminal": spot, "payoff": value,
                                   "closed": "profit_take",
                                   "itm": spot > position["strike"]})
                    position = None
                    last_mark = 0.0

        # --- write, whenever flat and a contract of the right tenor exists ---
        if position is None:
            book = by_session.get(session)
            if book is not None:
                book = book.loc[book["days_to_expiry"].between(low, high)]
                if not book.empty:
                    live = [e for e in sorted(book["expiry"].unique())
                            if pd.Timestamp(e) in settle_on
                            or pd.Timestamp(e) > data_end]
                    if not live:
                        curve.append({"session": session, "equity": cash
                                      + units * proxy[session], "cash": cash,
                                      "shares": units * proxy[session],
                                      "option_liability": 0.0, "index": spot,
                                      "proxy": proxy[session],
                                      "short_strike": np.nan, "funding": 0.0})
                        continue
                    expiry = pd.Timestamp(live[0])
                    book = book.loc[book["expiry"] == expiry]
                    years = max((expiry - session).days, 1) / 365.0
                    leg = _pick_strike(book, cfg, spot,
                                       _step(RBI_REPO_PATH, session),
                                       dividend.get(session, 0.0125), years)
                    if leg is not None:
                        exposure = units * proxy[session]
                        lot = lot_by_session.get(session, 75.0)
                        if cfg.quantise_lots:
                            lots = np.floor(exposure / (lot * spot))
                            qty = lots * lot
                        else:
                            qty = exposure / spot
                        if qty > 0:
                            gross = float(leg[cfg.premium_column])
                            net = gross * (1.0 - cfg.costs.premium_haircut) * qty
                            fee = cfg.costs.write_option(net, session)
                            cash += net - fee
                            position = {
                                "written": session, "expiry": expiry,
                                "settles_on": settle_on.get(expiry, expiry),
                                "strike": float(leg["strike"]), "qty": qty,
                                "premium_gross": gross,
                                "premium_net": net - fee,
                                "spot_at_write": spot,
                                "delta": float(leg.get("delta", np.nan)),
                                "moneyness": float(np.log(leg["strike"] / spot)),
                                "dte": (expiry - session).days,
                            }
                            last_mark = gross

        # --- mark the book ---
        if position is not None:
            mark = marks.get((session, position["expiry"], position["strike"],
                              "CE"))
            if mark is None or not np.isfinite(mark):
                mark = max(0.0, spot - position["strike"])   # stale: use intrinsic
            last_mark = mark
            liability = last_mark * position["qty"]
        else:
            liability = 0.0

        equity = cash + units * proxy[session] - liability
        curve.append({"session": session, "equity": equity, "cash": cash,
                      "shares": units * proxy[session],
                      "option_liability": liability,
                      "index": spot, "proxy": proxy[session],
                      "short_strike": position["strike"] if position else np.nan,
                      "funding": min(cash, 0.0) / equity if equity > 0 else np.nan})

    return {"curve": pd.DataFrame(curve), "trades": pd.DataFrame(trades)}


__all__ = ["CostModel", "CoveredCallConfig", "EXCHANGE_OPTION",
           "RBI_REPO_PATH", "STT_OPTION_SALE", "pick_strike", "run",
           "settlement_map"]
