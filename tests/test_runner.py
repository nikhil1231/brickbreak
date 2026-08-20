"""Unit and integration tests for research runner, spec validation, classifier, and signal comparison (PLAN.md §5.5, §5.7, §5.11, §5.12)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.persistence import store
from src.runner import (
    ExperimentSpec,
    SpecValidationError,
    classify_result,
    compare_signals,
    run_exploration,
    validate_spec,
)


class TestSpecValidation:
    def test_valid_spec_passes(self):
        spec = ExperimentSpec(
            hypothesis_id="H026",
            question="Does relative strength predict returns?",
            signal_name="rs_signal_test",
            partition="train",
            role="exploratory",
        )
        validate_spec(spec)

    def test_invalid_partition_fails(self):
        spec = ExperimentSpec(
            hypothesis_id="H026",
            question="Invalid date range test",
            signal_name="test_sig",
            partition="2021-01-01:2022-01-01",  # Hand-written date range forbidden
            role="exploratory",
        )
        with pytest.raises(SpecValidationError, match="Invalid partition"):
            validate_spec(spec)


class TestFailureClassifier:
    def test_classify_no_signal(self):
        report = {
            "n_total_rows": 1000,
            "predictive_content": {"primary_ic": {"mean_ic": 0.001, "t_stat": 0.2, "n_sessions": 50}},
            "quantiles": {"q5_spread_pct": -0.05, "q5_spread_bps": -5.0},
        }
        cls, interp, next_moves = classify_result(report)
        assert cls == "NO_SIGNAL"
        assert len(next_moves) > 0

    def test_classify_signal_but_beta(self):
        report = {
            "n_total_rows": 1000,
            "predictive_content": {"primary_ic": {"mean_ic": 0.045, "t_stat": 3.2, "n_sessions": 50}},
            "quantiles": {"q5_spread_pct": 0.85, "q5_spread_bps": 85.0, "q5_monotonicity": 0.9},
            "neutralisation": {"ic_retention_pct": 18.0, "neutralized_mean_ic": 0.008},
        }
        cls, interp, next_moves = classify_result(report)
        assert cls == "SIGNAL_BUT_BETA"
        assert "beta" in interp.lower()

    def test_classify_high_turnover(self):
        report = {
            "n_total_rows": 1000,
            "predictive_content": {"primary_ic": {"mean_ic": 0.035, "t_stat": 2.5, "n_sessions": 50}},
            "quantiles": {"q5_spread_pct": 0.70, "q5_spread_bps": 70.0, "q5_monotonicity": 0.8},
            "signal_mechanics": {"mean_turnover": 0.55},
            "neutralisation": {"ic_retention_pct": 80.0},
        }
        cls, interp, next_moves = classify_result(report)
        assert cls == "HIGH_TURNOVER"

    def test_classify_success(self):
        report = {
            "n_total_rows": 1000,
            "predictive_content": {"primary_ic": {"mean_ic": 0.042, "t_stat": 3.1, "n_sessions": 50}},
            "quantiles": {"q5_spread_pct": 1.10, "q5_spread_bps": 110.0, "q5_monotonicity": 0.95},
            "signal_mechanics": {"mean_turnover": 0.15},
            "neutralisation": {"ic_retention_pct": 75.0},
        }
        cls, interp, next_moves = classify_result(report)
        assert cls == "SUCCESS"


class TestSignalComparison:
    def test_compare_signals(self):
        np.random.seed(42)
        n = 300
        dates = np.repeat(pd.date_range("2023-01-01", periods=10), 30)
        symbols = np.tile([f"SYM_{i}" for i in range(30)], 10)
        sig_a = np.random.normal(0, 1, size=n)
        sig_b = 0.8 * sig_a + np.random.normal(0, 0.2, size=n)
        fwd_ret = 0.5 * sig_a + np.random.normal(0, 1, size=n)

        df = pd.DataFrame({
            "date": dates,
            "symbol": symbols,
            "signal_a": sig_a,
            "signal_b": sig_b,
            "fwd_ret_10d_pct": fwd_ret,
        })

        res = compare_signals(df, ["signal_a", "signal_b"], forward_col="fwd_ret_10d_pct", top_k=5)
        assert "pairwise_rank_correlation" in res
        assert "pairwise_top_k_overlap_pct" in res
        assert "combined_ensemble" in res
        # Correlation between A and B should be high (~0.8)
        assert res["pairwise_rank_correlation"]["signal_a"]["signal_b"] > 0.7


@pytest.mark.skipif(
    not (pd.io.common.Path("data/normalized/screen_metrics_asof.parquet").exists()
         and pd.io.common.Path("data/normalized/daily_context.parquet").exists()
         and pd.io.common.Path("data/normalized/daily_bars_adj.parquet").exists()),
    reason="requires built normalized data files on disk"
)
class TestEndToEndRunner:
    def test_run_exploration_end_to_end(self):
        # Exploration on H026
        spec = ExperimentSpec(
            hypothesis_id="H026",
            question="Testing relative strength and sector breadth ranking on train partition.",
            signal_name="h026_test_run",
            partition="train",
            role="exploratory",
            horizons=(5, 10),
            primary_horizon=10,
        )

        def _compute_signal(df: pd.DataFrame) -> pd.Series:
            d = df.copy()
            # Liquid universe filter
            mask = (d["median_tv_20_cr"] >= 5.0) & (~d["is_etf"].astype(bool))
            for col in ("rs_60d_vs_mkt", "sector_breadth"):
                d[f"{col}_pctile"] = d[mask].groupby("date")[col].rank(pct=True)
            sig = (d["rs_60d_vs_mkt_pctile"] + d["sector_breadth_pctile"]) / 2.0
            return sig.where(mask)

        res = run_exploration(spec, _compute_signal, save_results=True)

        assert res["hypothesis_id"] == "H026"
        assert res["signal_name"] == "h026_test_run"
        from src.persistence.models import FAILURE_CLASSES
        assert res["failure_class"] in FAILURE_CLASSES
        assert "manifest" in res
        assert res["manifest"]["hash"] is not None

        # Verify exploration was saved in store
        exp_id = res["exploration_id"]
        loaded_exp = store.get_exploration(exp_id)
        assert loaded_exp is not None
        assert loaded_exp.hypothesis_id == "H026"
