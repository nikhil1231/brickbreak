from types import SimpleNamespace

import pandas as pd

from src.research.families.wheel.engine import CostModel
from src.research.families.wheel.mohanty import TrancheConfig, run


ENTRY = pd.Timestamp("2024-01-01")
MID = pd.Timestamp("2024-01-10")
EXPIRY = pd.Timestamp("2024-01-31")

FREE = CostModel(stt_option_path=(("2000-01-01", 0.0),),
                 exchange_option=0.0, sebi_fee=0.0, gst=0.0,
                 stamp_option_buy=0.0, premium_haircut=0.0,
                 stt_delivery=0.0, exchange_delivery=0.0,
                 stamp_on_buy=0.0, physical_settlement_fee=0.0)


def option_day(session, settle=2.0):
    return pd.DataFrame({
        "session": [session], "symbol": ["AAA"], "expiry": [EXPIRY],
        "strike": [110.0], "option_type": ["CE"], "close": [2.0],
        "settle": [settle], "contracts": [300.0], "underlying": [100.0],
    })


def fixture(spots):
    chain = pd.concat([option_day(day) for day, _ in spots], ignore_index=True)
    tape = SimpleNamespace(
        pairs=[(ENTRY, EXPIRY, EXPIRY)],
        by_session={ENTRY: option_day(ENTRY)},
        prior_by_session={ENTRY: option_day(ENTRY)},
    )
    prices = pd.DataFrame({
        "symbol": "AAA", "session": [day for day, _ in spots],
        "price": [price for _, price in spots], "adj_factor": 1.0,
    })
    cfg = TrancheConfig(symbols=("AAA",), costs=FREE, cash_yield=0.0,
                        starting_capital=100_000.0)
    return chain, prices, tape, cfg


def test_gap_through_both_triggers_buys_both_at_the_observed_close():
    args = fixture([(ENTRY, 100.0), (MID, 112.0), (EXPIRY, 112.0)])
    out = run(*args)
    buys = out["trades"].loc[out["trades"]["kind"] == "stock_buy"]
    assert buys["reason"].tolist() == ["initial", "midpoint", "strike"]
    assert buys["price"].tolist() == [100.0, 112.0, 112.0]
    assert "call_assignment" in set(out["trades"]["kind"])
    assert out["curve"]["positions"].iloc[-1] == 0


def test_otm_expiry_retains_only_the_initial_tranche():
    args = fixture([(ENTRY, 100.0), (MID, 103.0), (EXPIRY, 104.0)])
    out = run(*args)
    buys = out["trades"].loc[out["trades"]["kind"] == "stock_buy"]
    assert buys["reason"].tolist() == ["initial"]
    assert out["curve"]["positions"].iloc[-1] == 1
    assert out["curve"]["shares"].iloc[-1] == 33_000.0 * 1.04


def test_fully_funded_control_buys_once_and_has_no_uncovered_call():
    args = fixture([(ENTRY, 100.0), (MID, 103.0), (EXPIRY, 104.0)])
    out = run(*args, staged=False)
    buys = out["trades"].loc[out["trades"]["kind"] == "stock_buy"]
    assert buys["reason"].tolist() == ["initial"]
    assert buys["qty"].iloc[0] == 1_000.0
    assert out["curve"]["uncovered_pct"].max() == 0.0
    assert out["curve"]["uncovered_pct_equity"].max() == 0.0
