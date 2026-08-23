import pandas as pd
import pytest

from src.research.families.bulk_deals.entry_timing import (
    EntryTimingError,
    _full_next_intraday,
    _paired_spreads,
    h046_train,
    h046_verdict,
)


def test_next_intraday_is_immediate_row_before_any_filter():
    bars = pd.DataFrame({
        "symbol": ["A", "A", "A", "B", "B"],
        "date": pd.to_datetime([
            "2024-01-01", "2024-01-02", "2024-01-03",
            "2024-01-01", "2024-01-02",
        ]),
        "open": [100, 110, 500, 200, 210],
        "close": [105, 121, 510, 202, 231],
        "close_raw": [105, 121, 510, 202, 231],
        "vwap_raw": [102, 115, 505, 201, 220],
        "adj_factor": [1, 1, 1, 1, 1],
    })
    out = _full_next_intraday(bars)
    row = out[(out.symbol == "A") & (out.date == pd.Timestamp("2024-01-01"))].iloc[0]
    assert row.next_date == pd.Timestamp("2024-01-02")
    assert row.fwd == pytest.approx(0.10)
    assert row.close_raw == 105


def test_paired_spread_uses_entry_session_and_frozen_event_cuts():
    event = pd.DataFrame({
        "entry_date": pd.to_datetime(["2024-01-02"] * 4),
        "premium_pct": [-2, -1, 1, 2],
        "excess_pct": [2, 1, -1, -2],
    })
    twin = pd.DataFrame({
        "entry_date": pd.to_datetime(["2024-01-02"] * 4),
        "analogue_pct": [-3, -1, 1, 3],
        "excess_pct": [1, 0, 0, -1],
    })
    out = _paired_spreads(event, twin, -0.5, 0.5).iloc[0]
    assert out.event_spread_pct == pytest.approx(-3.0)
    assert out.twin_spread_pct == pytest.approx(-1.0)
    assert out.increment_pct == pytest.approx(-2.0)


def test_next_intraday_exposes_date_needed_to_reject_a_late_twin():
    bars = pd.DataFrame({
        "symbol": ["A", "A"],
        "date": pd.to_datetime(["2024-01-01", "2024-01-03"]),
        "open": [100, 110], "close": [105, 121],
        "close_raw": [105, 121], "vwap_raw": [102, 115],
        "adj_factor": [1, 1],
    })
    row = _full_next_intraday(bars).iloc[0]
    assert row.next_date == pd.Timestamp("2024-01-03")
    assert row.next_date != pd.Timestamp("2024-01-02")


def test_next_intraday_quarantines_implausible_return_from_market_leg():
    bars = pd.DataFrame({
        "symbol": ["A", "A"],
        "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
        "open": [100, 100], "close": [100, 170],
        "close_raw": [100, 170], "vwap_raw": [100, 130],
        "adj_factor": [1, 1],
    })
    row = _full_next_intraday(bars).iloc[0]
    assert pd.isna(row.market_fwd)
    assert pd.isna(row.excess_pct)


def test_h046_cannot_open_an_unfrozen_partition():
    with pytest.raises(EntryTimingError, match="train-only"):
        h046_train(partition="validation")


def test_h046_verdict_uses_excess_after_cost_not_raw_profit():
    rows = []
    for floor in (1.0, 0.25, 0.10):
        for cap in (None, 10.0):
            rows.append({
                "floor_cr": floor, "extreme_cap_pct": cap,
                "increment_bps": -50.0, "t_dk": -3.0,
                "long_net_bps": -20.0, "short_net_bps": 30.0,
                "long_excess_net_bps": -10.0,
                "short_excess_net_bps": -5.0,
                "long_short_net_bps": -8.0,
            })
    assert h046_verdict(pd.DataFrame(rows)) == "REJECT"
