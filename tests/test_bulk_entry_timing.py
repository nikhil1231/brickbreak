import pandas as pd
import pytest

from src.research.families.bulk_deals.entry_timing import (
    EntryTimingError,
    _full_next_intraday,
    _match_h047,
    _h047_1515_prices,
    _paired_spreads,
    h046_train,
    h046_verdict,
    h047_verdict,
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


def test_h047_match_is_same_date_stratum_and_without_replacement():
    event = pd.DataFrame({
        "symbol": ["E1", "E2"], "date": pd.to_datetime(["2024-01-01"] * 2),
        "entry_date": pd.to_datetime(["2024-01-02"] * 2),
        "all_vwap": [10.0, 20.0], "vol_q": [1, 1], "liq_q": [2, 2],
        "volx_q": [3, 3],
    })
    controls = pd.DataFrame({
        "symbol": ["C1", "C2"], "date": pd.to_datetime(["2024-01-01"] * 2),
        "vwap_raw": [11.0, 21.0], "vol_q": [1, 1], "liq_q": [2, 2],
        "volx_q": [3, 3],
    })
    out = _match_h047(event, controls)
    assert len(out) == 2
    assert out.control_symbol.nunique() == 2
    assert set(out.entry_date) == {pd.Timestamp("2024-01-02")}


def test_h047_price_quarantines_adjusted_minute_against_raw_tape():
    windows = pd.DataFrame({
        "symbol": ["OK", "BAD"],
        "timestamp": pd.to_datetime(["2024-01-02 15:15", "2024-01-02 15:15"]),
        "open": [101.0, 50.0],
    })
    bars = pd.DataFrame({
        "symbol": ["OK", "BAD"], "date": pd.to_datetime(["2024-01-02"] * 2),
        "low_raw": [95.0, 95.0], "high_raw": [105.0, 105.0],
    })
    out = _h047_1515_prices(windows, bars).set_index("symbol")
    assert out.loc["OK", "entry_px"] == 101.0
    assert pd.isna(out.loc["BAD", "entry_px"])


def test_h047_verdict_enforces_coverage_before_a_good_score():
    table = pd.DataFrame([
        {"outcome": "primary", "extreme_cap_pct": None,
         "increment_bps": -60.0, "t_dk": -3.0,
         "long_excess_net_bps": 10.0, "short_excess_net_bps": -10.0,
         "long_short_net_bps": 1.0},
        {"outcome": "primary", "extreme_cap_pct": 10.0,
         "increment_bps": -50.0, "t_dk": -2.5,
         "long_excess_net_bps": 10.0, "short_excess_net_bps": -10.0,
         "long_short_net_bps": 1.0},
    ])
    coverage = {"event_price_coverage": 0.69, "control_price_coverage": 0.90,
                "complete_feature_sessions": 500}
    assert h047_verdict(table, coverage) == "REJECT"
