"""Mechanics of the wheel engine, on a chain small enough to check by hand.

These are not performance tests. They pin the four things that would silently
turn a wheel backtest into a different strategy: that assignment happens on the
underlying's expiry close and not on an option mark, that a physically settled
leg pays the physical-settlement fee on notional, that collateral is genuinely
secured, and that a name leaving the chain is sold rather than held forever.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.research.families.wheel import report
from src.research.families.covered_call import blackscholes as bs
from src.research.families.wheel.engine import (CostModel, STT_OPTION_SALE,
                                                WheelConfig, _pick_lagged_delta,
                                                _step, run)
from src.research_data.sources import nse_index_close

EXPIRIES = [pd.Timestamp("2020-01-30"), pd.Timestamp("2020-02-27"),
            pd.Timestamp("2020-03-26")]


def chain_row(session, symbol, expiry, strike, option_type, settle,
              underlying, contracts=500.0, lot=100.0):
    return {"session": session, "symbol": symbol, "expiry": expiry,
            "strike": float(strike), "option_type": option_type,
            "days_to_expiry": (expiry - session).days, "settle": float(settle),
            "close": float(settle), "contracts": float(contracts),
            "traded_value": contracts * lot * strike, "open_interest": 10_000.0,
            "lot_size": lot, "lot_size_source": "reported",
            "underlying": float(underlying), "adj_factor": 1.0,
            "moneyness": float(np.log(strike / underlying)),
            "source_era": "test"}


def build_chain(spec):
    """spec: list of (session, symbol, expiry, strike, type, settle, spot).

    Each entry session also gets a row for a contract expiring *that day*: on a
    real expiry day the dying contract is still quoted, and that is what marks
    the session as an expiry day.
    """
    rows = [chain_row(*row) for row in spec]
    for session, symbol, _expiry, strike, kind, _settle, spot in spec:
        rows.append(chain_row(session, symbol, session, strike, kind, 0.05, spot))
    # A completed contract remains in the bhavcopy through its last trading
    # session. The engine uses that final appearance to distinguish a completed
    # expiry from the still-open tail of the stored archive.
    for session, symbol, expiry, strike, kind, settle, spot in spec:
        rows.append(chain_row(expiry, symbol, expiry, strike, kind,
                              settle, spot))
    return pd.DataFrame(rows)


def prices(rows):
    return pd.DataFrame(rows, columns=["symbol", "session", "price"])


FREE = CostModel(stt_option_path=(("2000-01-01", 0.0),),
                 exchange_option=0.0, sebi_fee=0.0, gst=0.0,
                 premium_haircut=0.0, stamp_option_buy=0.0,
                 stt_delivery=0.0, exchange_delivery=0.0,
                 stamp_on_buy=0.0, physical_settlement_fee=0.0)
BARE = WheelConfig(slots=1, costs=FREE, cash_yield=0.0, starting_capital=100_000.0)


def test_put_expiring_worthless_keeps_the_whole_premium():
    chain = build_chain([
        (EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 2.0, 100.0),
        (EXPIRIES[0], "AAA", EXPIRIES[1], 105.0, "CE", 2.0, 100.0),
    ])
    # Settles above the strike: no assignment.
    out = run(chain, prices([("AAA", EXPIRIES[1], 110.0)]), BARE)
    trade = out["trades"].iloc[0]
    assert trade["kind"] == "put" and not trade["assigned"]
    qty = 100_000.0 / 95.0
    assert out["curve"]["equity"].iloc[-1] == pytest.approx(100_000.0 + 2.0 * qty)
    assert out["curve"]["positions"].iloc[-1] == 0


def test_assignment_uses_the_cash_close_and_delivers_shares():
    chain = build_chain([
        (EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 2.0, 100.0),
    ])
    out = run(chain, prices([("AAA", EXPIRIES[1], 90.0)]), BARE)
    trade = out["trades"].iloc[0]
    assert trade["assigned"]
    qty = 100_000.0 / 95.0
    row = out["curve"].iloc[-1]
    # Paid 95 for something worth 90, kept 2 of premium.
    assert row["equity"] == pytest.approx(100_000.0 + qty * (90.0 - 95.0 + 2.0))
    assert row["shares"] == pytest.approx(qty * 90.0)
    assert row["positions"] == 1


def test_covered_call_caps_the_upside_and_returns_to_cash():
    chain = build_chain([
        (EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 2.0, 100.0),
        (EXPIRIES[1], "AAA", EXPIRIES[2], 99.0, "CE", 1.0, 90.0),
    ])
    out = run(chain, prices([("AAA", EXPIRIES[1], 90.0),
                             ("AAA", EXPIRIES[2], 120.0)]), BARE)
    call = out["trades"].loc[out["trades"]["kind"] == "call"].iloc[0]
    assert call["assigned"]                       # 120 > 99, called away
    qty = 100_000.0 / 95.0
    # 95 paid, 2 + 1 of premium, sold at 99 — the run to 120 is not ours.
    expected = 100_000.0 + qty * (99.0 - 95.0 + 2.0 + 1.0)
    assert out["curve"]["equity"].iloc[-1] == pytest.approx(expected)
    assert out["curve"]["positions"].iloc[-1] == 0


def test_physical_settlement_fee_is_charged_on_notional_not_premium():
    chain = build_chain([(EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 2.0, 100.0)])
    settle = prices([("AAA", EXPIRIES[1], 90.0)])
    free = run(chain, settle, BARE)["curve"]["equity"].iloc[-1]
    fee = 0.004
    charged = run(chain, settle,
                  WheelConfig(slots=1, cash_yield=0.0, starting_capital=100_000.0,
                              costs=CostModel(
                                  stt_option_path=(("2000-01-01", 0.0),),
                                  exchange_option=0.0, sebi_fee=0.0, gst=0.0,
                                  premium_haircut=0.0, stt_delivery=0.0,
                                  exchange_delivery=0.0, stamp_on_buy=0.0,
                                  physical_settlement_fee=fee))
                  )["curve"]["equity"].iloc[-1]
    qty = 100_000.0 / 95.0
    assert free - charged == pytest.approx(fee * 95.0 * qty)


def test_untraded_strikes_are_never_selected():
    """A strike with a settlement mark but no prints is not a fill."""
    chain = build_chain([
        (EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 9.0, 100.0),   # untraded
        (EXPIRIES[0], "AAA", EXPIRIES[1], 90.0, "PE", 1.0, 100.0),   # traded
    ])
    chain.loc[chain["strike"] == 95.0, "contracts"] = 0.0
    out = run(chain, prices([("AAA", EXPIRIES[1], 110.0)]),
              WheelConfig(slots=1, costs=FREE, cash_yield=0.0,
                          starting_capital=100_000.0, min_strike_contracts=50.0,
                          min_chain_contracts=100.0))
    assert out["trades"]["strike"].iloc[0] == 90.0


def test_collateral_is_secured_so_slots_cannot_exceed_cash():
    """Ten slots on one rupee of capital must not write ten puts."""
    spec = []
    for name in "ABCDEFGHIJ":
        spec.append((EXPIRIES[0], name * 3, EXPIRIES[1], 95.0, "PE", 2.0, 100.0))
    out = run(build_chain(spec), prices(
        [(n * 3, EXPIRIES[1], 110.0) for n in "ABCDEFGHIJ"]),
        WheelConfig(slots=10, costs=FREE, cash_yield=0.0,
                    starting_capital=100_000.0))
    written = out["trades"]
    assert len(written) == 10
    assert (written["strike"] * written["qty"]).sum() <= 100_000.0 + 1e-6


def test_symbol_leaving_the_chain_is_sold_not_held():
    chain = build_chain([
        (EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 2.0, 100.0),
        # AAA is gone from the 2020-02-27 book; only BBB is quoted.
        (EXPIRIES[1], "BBB", EXPIRIES[2], 95.0, "PE", 2.0, 100.0),
    ])
    out = run(chain, prices([("AAA", EXPIRIES[1], 90.0),
                             ("AAA", EXPIRIES[2], 80.0),
                             ("BBB", EXPIRIES[2], 110.0)]),
              WheelConfig(slots=2, costs=FREE, cash_yield=0.0,
                          starting_capital=100_000.0))
    assert (out["trades"]["kind"] == "exit").sum() == 1
    assert out["curve"]["positions"].iloc[-1] == 0


def test_cash_yield_accrues_on_the_whole_book():
    chain = build_chain([(EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 0.0, 100.0)])
    chain.loc[:, "settle"] = 1e-9      # premium ~ 0, so only interest moves it
    out = run(chain, prices([("AAA", EXPIRIES[1], 110.0)]),
              WheelConfig(slots=1, costs=FREE, cash_yield=0.06,
                          starting_capital=100_000.0))
    days = (EXPIRIES[1] - EXPIRIES[0]).days
    assert out["curve"]["equity"].iloc[-1] == pytest.approx(
        100_000.0 * (1 + 0.06 * days / 365.0), rel=1e-6)


def test_split_inside_a_cycle_restrikes_instead_of_faking_a_loss():
    """A 1:10 split must move strike and quantity, not the P&L."""
    chain = build_chain([(EXPIRIES[0], "AAA", EXPIRIES[1], 950.0, "PE", 20.0, 1000.0)])
    # adj_factor jumps by 10 across the action; the raw close divides by 10.
    settle = pd.DataFrame([
        ("AAA", EXPIRIES[0], 1000.0, 0.1),
        ("AAA", EXPIRIES[1], 96.0, 1.0),
    ], columns=["symbol", "session", "price", "adj_factor"])
    out = run(chain, settle, BARE)
    trade = out["trades"].iloc[0]
    assert trade["adj_ratio"] == pytest.approx(10.0)
    assert trade["strike"] == pytest.approx(95.0)      # 950 / 10
    # 96 > 95 post-split, so this is *not* assigned — the pre-split comparison
    # (96 < 950) would have called it a 90% loss.
    assert not trade["assigned"]
    qty = 100_000.0 / 950.0
    assert out["curve"]["equity"].iloc[-1] == pytest.approx(100_000.0 + 20.0 * qty)


def test_split_while_holding_shares_preserves_position_value():
    chain = build_chain([
        (EXPIRIES[0], "AAA", EXPIRIES[1], 950.0, "PE", 20.0, 1000.0),
        (EXPIRIES[1], "AAA", EXPIRIES[2], 1000.0, "CE", 5.0, 900.0),
    ])
    settle = pd.DataFrame([
        ("AAA", EXPIRIES[0], 1000.0, 1.0),
        ("AAA", EXPIRIES[1], 900.0, 1.0),     # assigned at 950
        ("AAA", EXPIRIES[2], 95.0, 10.0),     # 1:10 split, worth 950 pre-split
    ], columns=["symbol", "session", "price", "adj_factor"])
    out = run(chain, settle, BARE)
    qty = 100_000.0 / 950.0
    row = out["curve"].iloc[-1]
    assert row["positions"] == 1
    # 10x the shares at a tenth of the price: the holding is worth what a
    # 1000 -> 950 move says it is, not a tenth of it.
    assert row["shares"] == pytest.approx(qty * 10 * 95.0)


def test_holiday_shift_settles_on_the_contracts_last_trading_session():
    entry = pd.Timestamp("2023-05-25")
    nominal = pd.Timestamp("2023-06-29")
    actual = pd.Timestamp("2023-06-28")
    chain = build_chain([(entry, "AAA", nominal, 95.0, "PE", 2.0, 100.0)])
    # Make the nominal-expiry row look like the archive: last quoted on the
    # preceding session, because the nominal Thursday was a holiday.
    chain.loc[chain["session"] == nominal, "session"] = actual
    # A later tape session proves the nominal expiry is behind us rather than
    # the still-open contract at the end of an incomplete archive.
    later = pd.Timestamp("2023-07-03")
    chain = pd.concat([chain, pd.DataFrame([
        chain_row(later, "BBB", later, 100.0, "PE", 1.0, 100.0)
    ])], ignore_index=True)
    out = run(chain, prices([("AAA", actual, 90.0)]), BARE)
    trade = out["trades"].iloc[0]
    assert trade["contract_expiry"] == nominal
    assert trade["expiry"] == actual
    assert trade["assigned"]


def test_incomplete_final_contract_is_not_treated_as_free_premium():
    future = pd.Timestamp("2020-04-30")
    chain = build_chain([(EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 2.0, 100.0)])
    chain = pd.concat([chain, pd.DataFrame([
        chain_row(EXPIRIES[1], "AAA", future, 95.0, "PE", 2.0, 100.0)
    ])], ignore_index=True)
    out = run(chain, prices([("AAA", EXPIRIES[1], 110.0)]), BARE)
    assert out["curve"]["session"].max() == EXPIRIES[1]
    assert future not in set(out["curve"]["session"])


def test_missing_cash_settlement_fails_closed():
    chain = build_chain([(EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 2.0, 100.0)])
    with pytest.raises(RuntimeError, match="missing cash settlement"):
        run(chain, prices([]), BARE)


def test_symbol_with_forced_early_expiry_is_not_written():
    entry = pd.Timestamp("2023-06-28")
    nominal = pd.Timestamp("2023-07-27")
    forced = pd.Timestamp("2023-07-12")
    normal = pd.Timestamp("2023-07-27")
    chain = build_chain([
        (entry, "HDFC", nominal, 2600.0, "PE", 20.0, 2700.0),
        (entry, "AAA", nominal, 95.0, "PE", 2.0, 100.0),
    ])
    chain.loc[(chain["symbol"] == "HDFC")
              & (chain["session"] == nominal), "session"] = forced
    out = run(chain, prices([("HDFC", forced, 2700.0),
                             ("AAA", normal, 110.0)]), BARE)
    assert set(out["trades"]["symbol"]) == {"AAA"}
    assert out["curve"]["early_expiry_exclusions"].sum() == 1


def test_stationary_bootstrap_restarts_blocks_and_has_a_real_interval():
    sessions = pd.date_range("2020-01-31", periods=25, freq="ME")
    wheel_returns = np.array([
        .03, -.01, .02, -.04, .01, .05, -.02, .00, .04, -.03, .01, .02,
        -.01, .03, -.05, .02, .01, -.02, .04, .00, .03, -.01, .02, -.03,
    ])
    curve = pd.DataFrame({"session": sessions,
                          "equity": np.r_[1.0, np.cumprod(1.0 + wheel_returns)]})
    benchmark = pd.DataFrame({"session": sessions,
                              "price_level": np.r_[1.0, np.cumprod(1.0 + wheel_returns / 2)],
                              "total_level": np.r_[1.0, np.cumprod(1.0 + wheel_returns / 2)]})
    edge = report.edge_test(curve, benchmark, draws=500)
    assert (edge["boot_hi_annual"] > edge["boot_lo_annual"]).all()


def test_2026_option_stt_rate_is_in_the_path():
    stamps = pd.Series(pd.to_datetime(["2026-03-31", "2026-04-01"]))
    assert _step(STT_OPTION_SALE, stamps).tolist() == pytest.approx([.001, .0015])


def test_lagged_selection_uses_prior_session_liquidity():
    prior = EXPIRIES[0] - pd.Timedelta(days=1)
    rows = []
    for symbol, prior_contracts, entry_contracts in (
            ("AAA", 60.0, 1000.0), ("BBB", 1000.0, 60.0)):
        rows.extend([
            chain_row(prior, symbol, EXPIRIES[1], 95.0, "PE", 2.0, 100.0,
                      contracts=prior_contracts),
            chain_row(EXPIRIES[0], symbol, EXPIRIES[1], 95.0, "PE", 2.0, 100.0,
                      contracts=entry_contracts),
            chain_row(EXPIRIES[0], symbol, EXPIRIES[0], 95.0, "PE", .05, 100.0),
            chain_row(EXPIRIES[1], symbol, EXPIRIES[1], 95.0, "PE", .05, 100.0),
        ])
    out = run(pd.DataFrame(rows),
              prices([("AAA", EXPIRIES[1], 110.0),
                      ("BBB", EXPIRIES[1], 110.0)]),
              replace(BARE, lag_selection=True))
    assert out["trades"]["symbol"].iloc[0] == "BBB"


def test_delta_selector_labels_observed_prices_and_requires_execution_print():
    strikes = np.array([85.0, 90.0, 95.0, 97.0])
    premiums = np.array([
        bs.put_price(100.0, strike, 0.0, 0.0, .25, 30 / 365)
        for strike in strikes
    ])
    selection = pd.DataFrame({
        "strike": strikes, "option_type": "PE", "contracts": 500.0,
        "close": premiums,
    })
    execution = selection.copy()
    picked = _pick_lagged_delta(
        selection, execution, "PE", .30, 250.0, "close", 100.0,
        0.0, 0.0, 30 / 365)
    assert picked is not None
    assert abs(abs(picked["_selected_delta"]) - .30) == pytest.approx(
        min(abs(abs(bs.delta(
            100.0, strike, 0.0, 0.0, .25, 30 / 365, "PE")) - .30)
            for strike in strikes), abs=1e-6)
    execution.loc[execution["strike"] == picked["strike"], "contracts"] = 0.0
    assert _pick_lagged_delta(
        selection, execution, "PE", .30, 250.0, "close", 100.0,
        0.0, 0.0, 30 / 365) is None


def test_entry_eligibility_filters_new_puts_but_not_existing_calls():
    chain = build_chain([
        (EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 2.0, 100.0),
        (EXPIRIES[1], "AAA", EXPIRIES[2], 105.0, "CE", 2.0, 100.0),
    ])
    settle = prices([
        ("AAA", EXPIRIES[1], 90.0),
        ("AAA", EXPIRIES[2], 100.0),
    ])
    allowed = {EXPIRIES[0]: {"AAA"}, EXPIRIES[1]: set()}
    out = run(chain, settle, BARE, eligible_by_entry=allowed)
    assert out["trades"]["kind"].tolist() == ["put", "call"]


def test_entry_eligibility_can_leave_the_book_in_cash():
    chain = build_chain([
        (EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 2.0, 100.0),
    ])
    out = run(chain, prices([("AAA", EXPIRIES[1], 110.0)]), BARE,
              eligible_by_entry={EXPIRIES[0]: set()})
    assert out["trades"].empty
    assert out["curve"]["equity"].iloc[-1] == pytest.approx(100_000.0)


def test_bull_put_spread_keeps_only_the_net_credit_when_both_legs_expire():
    chain = build_chain([
        (EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 2.0, 100.0),
        (EXPIRIES[0], "AAA", EXPIRIES[1], 90.0, "PE", 0.5, 100.0),
    ])
    cfg = replace(BARE, put_hedge_width=0.05, min_chain_contracts=100.0)
    out = run(chain, prices([("AAA", EXPIRIES[1], 110.0)]), cfg)
    qty = 100_000.0 / 95.0
    trade = out["trades"].iloc[0]
    assert trade["hedge_strike"] == 90.0
    assert not trade["assigned"] and not trade["hedge_exercised"]
    assert trade["premium_net"] == pytest.approx((2.0 - 0.5) * qty)
    assert out["curve"]["equity"].iloc[-1] == pytest.approx(
        100_000.0 + (2.0 - 0.5) * qty)


def test_bull_put_spread_caps_a_crash_and_returns_the_slot_to_cash():
    chain = build_chain([
        (EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 2.0, 100.0),
        (EXPIRIES[0], "AAA", EXPIRIES[1], 90.0, "PE", 0.5, 100.0),
    ])
    cfg = replace(BARE, put_hedge_width=0.05, min_chain_contracts=100.0)
    out = run(chain, prices([("AAA", EXPIRIES[1], 70.0)]), cfg)
    qty = 100_000.0 / 95.0
    trade = out["trades"].iloc[0]
    assert trade["assigned"] and trade["hedge_exercised"]
    # Bought at 95, delivered at 90, and retained 2 - 0.5 of premium.
    assert out["curve"]["equity"].iloc[-1] == pytest.approx(
        100_000.0 + qty * (90.0 - 95.0 + 2.0 - 0.5))
    assert out["curve"]["positions"].iloc[-1] == 0


def test_bull_put_spread_between_strikes_enters_the_ordinary_wheel():
    chain = build_chain([
        (EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 2.0, 100.0),
        (EXPIRIES[0], "AAA", EXPIRIES[1], 90.0, "PE", 0.5, 100.0),
    ])
    cfg = replace(BARE, put_hedge_width=0.05, min_chain_contracts=100.0)
    out = run(chain, prices([("AAA", EXPIRIES[1], 92.0)]), cfg)
    qty = 100_000.0 / 95.0
    trade = out["trades"].iloc[0]
    assert trade["assigned"] and not trade["hedge_exercised"]
    assert out["curve"]["positions"].iloc[-1] == 1
    assert out["curve"]["equity"].iloc[-1] == pytest.approx(
        100_000.0 + qty * (92.0 - 95.0 + 2.0 - 0.5))


def test_bull_put_spread_skips_a_short_leg_when_no_hedge_print_exists():
    chain = build_chain([
        (EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 2.0, 100.0),
        (EXPIRIES[0], "AAA", EXPIRIES[1], 90.0, "PE", 0.5, 100.0),
    ])
    chain.loc[chain["strike"] == 90.0, "contracts"] = 0.0
    cfg = replace(BARE, put_hedge_width=0.05, min_chain_contracts=100.0)
    out = run(chain, prices([("AAA", EXPIRIES[1], 110.0)]), cfg)
    assert out["trades"].empty
    assert out["curve"]["equity"].iloc[-1] == pytest.approx(100_000.0)


def test_bull_put_spread_applies_adverse_execution_to_both_legs():
    chain = build_chain([
        (EXPIRIES[0], "AAA", EXPIRIES[1], 95.0, "PE", 2.0, 100.0),
        (EXPIRIES[0], "AAA", EXPIRIES[1], 90.0, "PE", 0.5, 100.0),
    ])
    costs = replace(FREE, premium_haircut=0.10)
    cfg = replace(BARE, costs=costs, put_hedge_width=0.05,
                  min_chain_contracts=100.0)
    out = run(chain, prices([("AAA", EXPIRIES[1], 110.0)]), cfg)
    qty = 100_000.0 / 95.0
    # Receive 90% of the short quote and pay 110% of the long quote.
    assert out["trades"]["premium_net"].iloc[0] == pytest.approx(
        qty * (2.0 * 0.9 - 0.5 * 1.1))


def test_index_archive_parser_uses_the_date_inside_the_file():
    text = ("Index Name,Index Date,Open Index Value,High Index Value,"
            "Low Index Value,Closing Index Value,Turnover (Rs. Cr.),P/E,P/B,"
            "Div Yield\n"
            "Nifty 50,17-06-2025,23000,23200,22900,23100,12000,22.5,3.4,1.25\n")
    parsed = nse_index_close.parse(text)
    assert parsed["session"].iloc[0] == pd.Timestamp("2025-06-17")
    assert parsed["div_yield"].iloc[0] == pytest.approx(1.25)


def test_index_total_return_accrues_the_previous_sessions_yield(tmp_path):
    path = tmp_path / "index.parquet"
    pd.DataFrame({
        "session": pd.to_datetime(["2025-01-01", "2025-01-11"]),
        "index_name": ["Nifty 50", "Nifty 50"],
        "close": [100.0, 100.0],
        "div_yield": [3.65, 99.0],
        "pe": [20.0, 20.0],
        "pb": [3.0, 3.0],
    }).to_parquet(path, index=False)
    out = nse_index_close.series("Nifty 50", path)
    assert out["price_level"].iloc[-1] == pytest.approx(1.0)
    assert out["total_level"].iloc[-1] == pytest.approx(1.001)
