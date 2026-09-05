"""Mechanics of the covered-call engine, on a chain small enough to check by hand.

The load-bearing test is `test_capped_upside_identity`: when the equity leg
tracks the index exactly and the call finishes in the money, the terminal equity
of a covered call has a closed form —

    capital * (strike / spot_at_write) + premium

— because the ETF's gain above the strike is exactly the call's payoff. If the
simulator disagrees with that by more than rounding, its sizing or its
settlement is wrong, and every CAGR it produces is wrong with it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.families.covered_call import blackscholes as bs
from src.research.families.covered_call.engine import (CostModel,
                                                       CoveredCallConfig, run)

SESSIONS = pd.date_range("2024-01-04", periods=15, freq="B")
EXPIRY = SESSIONS[7]


def chain_row(session, expiry, strike, option_type, settle, spot, contracts=1e6):
    return {"session": session, "symbol": "NIFTY", "expiry": expiry,
            "expiry_kind": "weekly", "strike": float(strike),
            "option_type": option_type,
            "days_to_expiry": (expiry - session).days, "settle": float(settle),
            "close": float(settle), "contracts": float(contracts),
            "open_interest": 1e6, "lot_size": 25.0, "underlying": float(spot),
            "moneyness": float(np.log(strike / spot)), "source_era": "test"}


def market(index_path, proxy_path=None):
    return pd.DataFrame({
        "session": SESSIONS, "index": index_path,
        "proxy": index_path if proxy_path is None else proxy_path,
        "div_yield": 1.25})


ZERO = (("2000-01-01", 0.0),)
FREE = CostModel(stt_option_path=ZERO, exchange_option_path=ZERO, sebi_fee=0.0,
                 gst=0.0, premium_haircut=0.0, etf_stt_sale=0.0,
                 etf_exchange=0.0, etf_stamp_buy=0.0, stamp_option_buy=0.0)
BARE = CoveredCallConfig(strike_rule="otm", otm=0.02, costs=FREE,
                         cash_yield=0.0, starting_capital=1_000_000.0)


def flat_chain(strikes, settles, spot=20_000.0):
    """One expiry, quoted on every session before it, at a constant mark."""
    rows = []
    for session in SESSIONS[SESSIONS <= EXPIRY]:
        for strike, settle in zip(strikes, settles):
            rows.append(chain_row(session, EXPIRY, strike, "CE", settle, spot))
    return pd.DataFrame(rows)


def test_call_expiring_out_of_the_money_keeps_the_whole_premium():
    chain = flat_chain([20_400.0], [100.0])
    path = np.full(len(SESSIONS), 20_000.0)
    out = run(chain, market(path), BARE)
    trade = out["trades"].iloc[0]
    assert not trade["itm"] and trade["payoff"] == 0.0
    qty = 1_000_000.0 / 20_000.0
    assert out["curve"]["equity"].iloc[-1] == pytest.approx(
        1_000_000.0 + 100.0 * qty)


def test_capped_upside_identity():
    """ETF gain above the strike is exactly handed to the call buyer."""
    strike, premium = 20_400.0, 100.0
    chain = flat_chain([strike], [premium])
    path = np.full(len(SESSIONS), 20_000.0)
    path[SESSIONS.get_loc(EXPIRY):] = 23_000.0        # a 15% rip past the strike
    out = run(chain, market(path), BARE)
    trade = out["trades"].iloc[0]
    assert trade["itm"]
    capital, spot = 1_000_000.0, 20_000.0
    expected = capital * (strike / spot) + premium * (capital / spot)
    # Equity right after settlement, before any further writing.
    at_expiry = out["curve"].loc[
        out["curve"]["session"] == EXPIRY, "equity"].iloc[0]
    assert at_expiry == pytest.approx(expected, rel=1e-9)


def test_cash_settlement_never_touches_the_etf():
    chain = flat_chain([20_400.0], [100.0])
    path = np.full(len(SESSIONS), 20_000.0)
    path[SESSIONS.get_loc(EXPIRY):] = 23_000.0
    out = run(chain, market(path), BARE)
    units_value = out["curve"]["shares"]
    # Share leg only ever moves with the price, never with a settlement.
    ratio = units_value / out["curve"]["proxy"]
    assert ratio.nunique() == 1


def test_short_call_is_marked_daily_not_only_at_expiry():
    chain = flat_chain([20_400.0], [100.0])
    # Make the mark rise mid-life so the liability has to move with it.
    chain.loc[chain["session"] == SESSIONS[3], "settle"] = 500.0
    path = np.full(len(SESSIONS), 20_000.0)
    out = run(chain, market(path), BARE)
    row = out["curve"].loc[out["curve"]["session"] == SESSIONS[3]].iloc[0]
    qty = 1_000_000.0 / 20_000.0
    assert row["option_liability"] == pytest.approx(500.0 * qty)
    assert row["equity"] < out["curve"]["equity"].iloc[0]


def test_negative_cash_is_funded_at_a_spread():
    """A deep mark-to-market debit costs money to carry."""
    strike = 20_400.0
    chain = flat_chain([strike], [100.0])
    # The index gaps up the session after the call is written, and the mark
    # follows it, so the short leg is a large daily cash debit for a week.
    chain.loc[chain["session"] > SESSIONS[1], "settle"] = 4_600.0
    path = np.full(len(SESSIONS), 20_000.0)
    path[2:] = 25_000.0
    cheap = run(chain, market(path),
                CoveredCallConfig(strike_rule="otm", otm=0.02, costs=FREE,
                                  cash_yield=0.0, funding_spread=0.0,
                                  starting_capital=1_000_000.0))
    dear = run(chain, market(path),
               CoveredCallConfig(strike_rule="otm", otm=0.02, costs=FREE,
                                 cash_yield=0.0, funding_spread=0.50,
                                 starting_capital=1_000_000.0))
    assert dear["curve"]["equity"].iloc[-1] < cheap["curve"]["equity"].iloc[-1]
    assert dear["curve"]["funding"].min() < 0


def test_delta_rule_picks_the_strike_the_market_prices_at_that_delta():
    spot, years, rate, q = 20_000.0, 7 / 365.0, 0.065, 0.0125
    strikes = np.arange(20_100.0, 21_200.0, 100.0)
    prices = [bs.call_price(spot, k, rate, q, 0.12, years) for k in strikes]
    chain = flat_chain(strikes, prices)
    deltas = bs.chain_delta(strikes, prices, spot, rate, q, years, "CE")
    wanted = strikes[np.nanargmin(np.abs(deltas - 0.15))]
    path = np.full(len(SESSIONS), spot)
    out = run(chain, market(path),
              CoveredCallConfig(strike_rule="delta", target_delta=0.15,
                                costs=FREE, cash_yield=0.0,
                                starting_capital=1_000_000.0))
    assert out["trades"]["strike"].iloc[0] == pytest.approx(wanted)
    assert abs(out["trades"]["delta"].iloc[0] - 0.15) < 0.05


def test_untraded_strikes_are_never_written():
    chain = flat_chain([20_400.0, 20_800.0], [100.0, 60.0])
    chain.loc[chain["strike"] == 20_400.0, "contracts"] = 0.0
    path = np.full(len(SESSIONS), 20_000.0)
    out = run(chain, market(path),
              CoveredCallConfig(strike_rule="otm", otm=0.02, costs=FREE,
                                cash_yield=0.0, starting_capital=1_000_000.0,
                                min_contracts=1.0))
    assert out["trades"]["strike"].iloc[0] == 20_800.0


def test_etf_basis_shows_up_in_the_result():
    """Settling on the index while holding an ETF that lags is a real loss."""
    strike = 20_400.0
    chain = flat_chain([strike], [100.0])
    index_path = np.full(len(SESSIONS), 20_000.0)
    index_path[SESSIONS.get_loc(EXPIRY):] = 23_000.0
    # A constant discount is not a basis — it cancels out of the ETF's return.
    # What costs money is the discount *widening* while the option settles on
    # the index regardless.
    lagging = index_path.copy()
    lagging[SESSIONS.get_loc(EXPIRY):] = 23_000.0 * 0.98
    matched = run(chain, market(index_path), BARE)["curve"]["equity"].iloc[-1]
    basis = run(chain, market(index_path, lagging),
                BARE)["curve"]["equity"].iloc[-1]
    assert basis < matched


def test_profit_take_closes_early_and_rewrites():
    chain = flat_chain([20_400.0], [100.0])
    chain.loc[chain["session"] >= SESSIONS[3], "settle"] = 10.0
    path = np.full(len(SESSIONS), 20_000.0)
    out = run(chain, market(path),
              CoveredCallConfig(strike_rule="otm", otm=0.02, costs=FREE,
                                cash_yield=0.0, starting_capital=1_000_000.0,
                                profit_take=0.5))
    assert (out["trades"]["closed"] == "profit_take").any()
    assert out["trades"]["settled"].iloc[0] == SESSIONS[3]


def test_expiry_on_a_non_session_still_settles():
    """NSE lists a Thursday contract, a holiday moves it to Wednesday.

    The contract keeps its Thursday name and simply stops being quoted a day
    early. Settling on `session == expiry` would leave it open forever, freeze
    the book, and turn every later result into buy-and-hold plus a stuck short
    call — while the equity curve kept moving and the metrics kept computing.
    This is the bug that invalidated the first run of this study.
    """
    # 2024-01-13 is a Saturday: a plausible contract name, never a session.
    ghost = pd.Timestamp("2024-01-13")
    last_quote = pd.Timestamp("2024-01-12")          # the Friday before it
    rows = [chain_row(s, ghost, 20_400.0, "CE", 100.0, 20_000.0)
            for s in SESSIONS[SESSIONS <= last_quote]]
    # A later contract the engine must be free to write once the ghost settles.
    later = pd.Timestamp("2024-01-19")
    rows += [chain_row(s, later, 20_800.0, "CE", 80.0, 20_000.0)
             for s in SESSIONS[(SESSIONS >= last_quote) & (SESSIONS <= later)]]
    chain = pd.DataFrame(rows)
    path = np.full(len(SESSIONS), 20_000.0)
    out = run(chain, market(path), BARE)

    assert ghost not in set(SESSIONS), "fixture must use a genuine non-session"
    trades = out["trades"]
    assert len(trades) == 2, "the book froze on the holiday-shifted expiry"
    # It died on its last quoted session, not on its nominal expiry date.
    assert trades["expiry"].iloc[0] == ghost
    assert trades["settled"].iloc[0] == last_quote
    assert trades["settled"].iloc[1] == later


def test_a_contract_open_at_the_end_of_the_archive_is_not_settled_early():
    """The tail is genuinely open, and must be marked rather than closed."""
    far = SESSIONS[-1] + pd.Timedelta(days=5)
    rows = [chain_row(s, far, 20_400.0, "CE", 100.0, 20_000.0)
            for s in SESSIONS[8:]]
    chain = pd.DataFrame(rows)
    path = np.full(len(SESSIONS), 20_000.0)
    out = run(chain, market(path), BARE)
    assert out["trades"].empty or (out["trades"]["settled"] < far).all()
    assert np.isfinite(out["curve"]["option_liability"].iloc[-1])


# --------------------------------------------------------------------------
# The wheel variant: cash-secured puts, then covered calls, on a cash-settled
# index. The mechanic that has to be right is that assignment delivers nothing
# and the index has to be bought in the market afterwards.
# --------------------------------------------------------------------------
from src.research.families.covered_call.wheel import WheelConfig
from src.research.families.covered_call.wheel import run as wheel_run

WHEEL_BARE = WheelConfig(strike_rule="otm", put_otm=0.02, call_otm=0.02,
                         costs=FREE, cash_yield=0.0, starting_capital=1_000_000.0)


def put_chain(strikes, settles, option_type="PE", spot=20_000.0):
    rows = []
    for session in SESSIONS[SESSIONS <= EXPIRY]:
        for strike, settle in zip(strikes, settles):
            rows.append(chain_row(session, EXPIRY, strike, option_type, settle,
                                  spot))
    return pd.DataFrame(rows)


def test_put_expiring_out_of_the_money_stays_in_cash():
    chain = put_chain([19_600.0], [80.0])
    path = np.full(len(SESSIONS), 20_000.0)
    out = wheel_run(chain, market(path), WHEEL_BARE)
    trade = out["trades"].iloc[0]
    assert trade["kind"] == "PE" and not trade["assigned"]
    assert out["curve"]["in_market"].sum() == 0
    qty = 1_000_000.0 / 19_600.0
    assert out["curve"]["equity"].iloc[-1] == pytest.approx(
        1_000_000.0 + 80.0 * qty)


def test_assignment_pays_cash_and_then_buys_the_etf():
    """The combined outlay is the strike, and the ETF is actually acquired."""
    strike, premium = 19_600.0, 80.0
    chain = put_chain([strike], [premium])
    path = np.full(len(SESSIONS), 20_000.0)
    path[SESSIONS.get_loc(EXPIRY):] = 18_000.0        # settles below the strike
    out = wheel_run(chain, market(path), WHEEL_BARE)
    trade = out["trades"].iloc[0]
    assert trade["assigned"]
    row = out["curve"].loc[out["curve"]["session"] == EXPIRY].iloc[0]
    assert row["in_market"] == 1.0
    qty = 1_000_000.0 / strike
    # Paid the strike for something now worth 18,000, kept the premium.
    expected = 1_000_000.0 + qty * (18_000.0 - strike + premium)
    assert row["equity"] == pytest.approx(expected, rel=1e-9)
    assert row["shares"] == pytest.approx(qty * 18_000.0)


def test_the_wheel_is_out_of_the_market_while_it_holds_puts():
    chain = put_chain([19_600.0], [80.0])
    path = np.full(len(SESSIONS), 20_000.0)
    out = wheel_run(chain, market(path), WHEEL_BARE)
    # Never assigned, so never long the index — the out-of-market drag is real
    # and has to be visible in the curve rather than assumed away.
    assert out["curve"]["in_market"].max() == 0.0
