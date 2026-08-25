import pandas as pd

from src.research.families.machine_geometry import (
    RetestPrior,
    development_fold_manifest,
    exit_policy_grid,
    generate_retest_population,
)


def feature_row(**updates):
    row = {
        "symbol_asof": "TEST", "session": pd.Timestamp("2025-01-02"),
        "bar_end": pd.Timestamp("2025-01-02 11:00"),
        "available_at": pd.Timestamp("2025-01-02 11:00"),
        "close_raw": 102.0, "atr_20": 1.0,
        "htf_ema_20": 101.0, "htf_ema_50": 100.0,
        "htf_ema_20_slope_pct": 0.1,
        "support_zone_kind": "flip_support", "support_zone_lower": 99.8,
        "support_zone_upper": 100.2, "support_known_at": pd.Timestamp("2025-01-02 09:30"),
        "support_age_bars": 20, "support_break_age_bars": 4,
        "support_bleed_bars": 0, "support_cumulative_bleed_atr": 0.0,
        "resistance_zone_kind": "resistance", "resistance_zone_lower": 106.0,
        "resistance_zone_upper": 106.4,
        "resistance_known_at": pd.Timestamp("2025-01-02 10:00"),
        "resistance_age_bars": 10, "resistance_break_age_bars": float("nan"),
        "resistance_bleed_bars": 0, "resistance_cumulative_bleed_atr": 0.0,
        "bullish_flip_retest": True, "bearish_flip_retest": False,
        "quality_flags": "", "partition": "train",
    }
    row.update(updates)
    return row


def test_structural_long_retest_can_pass_every_manual_prior():
    result = generate_retest_population(pd.DataFrame([feature_row()]))
    assert len(result) == 1
    assert bool(result.loc[0, "eligible"])
    assert result.loc[0, "direction"] == "long"
    assert result.loc[0, "target_price_at_decision"] == 106.0
    assert result.loc[0, "rejection_reasons"] == ""


def test_bleeding_level_is_retained_but_not_eligible():
    result = generate_retest_population(pd.DataFrame([
        feature_row(support_bleed_bars=2, support_cumulative_bleed_atr=0.4)
    ]))
    assert not bool(result.loc[0, "eligible"])
    assert "level_not_bleeding" in result.loc[0, "rejection_reasons"]


def test_exit_grid_declares_each_time_cut():
    policies = exit_policy_grid(RetestPrior(stagnation_bars=(6, 12, 24)))
    assert [row["stagnation_cut_after_completed_bars"] for row in policies] == [6, 12, 24]


def test_fold_manifest_is_leave_one_market_out_and_walk_forward():
    rows = []
    for market in ("NSE", "NYSE", "LSE"):
        for quarter in pd.period_range("2020Q1", "2022Q4", freq="Q"):
            rows.append({"market": market, "session": quarter.start_time})
    folds = development_fold_manifest(pd.DataFrame(rows), minimum_train_quarters=8)
    assert set(folds["held_out_market"]) == {"NSE", "NYSE", "LSE"}
    assert all(
        row.held_out_market not in row.development_markets
        for row in folds.itertuples())
    assert all(len(row.train_quarters) >= 8 for row in folds.itertuples())
