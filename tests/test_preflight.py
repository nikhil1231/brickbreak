"""Tests for label-free pre-flight screening (Stage F, PLAN.md §6).

The decisive invariant:
Pre-flight rejection must preserve the sample budget by NOT incrementing
burden.count_tests.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.alpha_eval.guards import LeakageGuardError, ScoringGuardError
from src.persistence import store
from src.runner import burden, preflight
from src.runner.spec import ExperimentSpec


@pytest.fixture
def clean_synthetic_panel():
    """Create a synthetic label-free panel with 30 dates and 100 symbols."""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=30, freq="B").strftime("%Y-%m-%d")
    symbols = [f"SYM_{i:03d}" for i in range(100)]

    rows = []
    for d in dates:
        # Market move
        mkt = np.random.normal(0.001, 0.01)
        for s in symbols:
            beta = np.random.uniform(0.5, 1.5)
            ret_20d = np.random.normal(0.02, 0.05)
            turnover = np.random.uniform(1.0, 50.0)
            atr_pct = np.random.uniform(1.5, 4.0)
            # A distinct feature (e.g. idiosyncratic volatility / volume anomaly)
            custom_alpha = np.random.normal(0.0, 1.0)
            rows.append({
                "date": d,
                "symbol": s,
                "beta": beta,
                "ret_20d": ret_20d,
                "median_tv_20_cr": turnover,
                "atr_pct": atr_pct,
                # A persistent, smooth distinct signal
                "clean_signal": np.sin(int(s.split('_')[1])) + ret_20d * 0.1 + np.random.normal(0, 0.01),
                # A white noise signal with high turnover (~0.33)
                "noisy_signal": np.random.uniform(0, 1),
                # A pure beta clone (H038 error)
                "beta_clone": beta * 2.0 + np.random.normal(0, 0.0001),
                # A constant signal
                "flat_signal": 1.0,
            })
    return pd.DataFrame(rows)



class TestPreFlightScreening:
    def test_clean_signal_passes_preflight(self, clean_synthetic_panel):
        spec = ExperimentSpec(
            hypothesis_id="H999",
            question="Clean signal test",
            signal_name="clean_signal",
            partition="train",
        )
        res = preflight.run_preflight(
            clean_synthetic_panel,
            signal_col="clean_signal",
            spec=spec,
            save_results=False,
        )
        assert res.passed is True
        assert res.failure_class is None
        assert len(res.reasons) == 0
        assert res.mechanics["mean_coverage_names"] == 100

    def test_constant_signal_rejected_as_data_quality(self, clean_synthetic_panel):
        spec = ExperimentSpec(
            hypothesis_id="H999",
            question="Flat signal test",
            signal_name="flat_signal",
            partition="train",
        )
        res = preflight.run_preflight(
            clean_synthetic_panel,
            signal_col="flat_signal",
            spec=spec,
            save_results=False,
        )
        assert res.passed is False
        assert res.failure_class == "DATA_QUALITY"
        assert any("constant" in r.lower() for r in res.reasons)

    def test_high_turnover_signal_rejected(self, clean_synthetic_panel):
        spec = ExperimentSpec(
            hypothesis_id="H999",
            question="Noisy signal test",
            signal_name="noisy_signal",
            partition="train",
        )
        cfg = preflight.PreFlightConfig(max_turnover=0.25)
        res = preflight.run_preflight(
            clean_synthetic_panel,
            signal_col="noisy_signal",
            spec=spec,
            cfg=cfg,
            save_results=False,
        )

        assert res.passed is False
        assert res.failure_class == "HIGH_TURNOVER"
        assert any("turnover" in r.lower() for r in res.reasons)

    def test_h038_beta_redundancy_rejected(self, clean_synthetic_panel):
        spec = ExperimentSpec(
            hypothesis_id="H999",
            question="Beta clone test",
            signal_name="beta_clone",
            partition="train",
        )
        res = preflight.run_preflight(
            clean_synthetic_panel,
            signal_col="beta_clone",
            spec=spec,
            save_results=False,
        )
        assert res.passed is False
        assert res.failure_class == "SIGNAL_BUT_BETA"
        assert any("beta" in r.lower() or "h038" in r.lower() for r in res.reasons)

    def test_insufficient_coverage_rejected(self, clean_synthetic_panel):
        # Filter down to only 5 names
        sparse_df = clean_synthetic_panel[clean_synthetic_panel["symbol"].isin(["SYM_001", "SYM_002", "SYM_003"])]
        spec = ExperimentSpec(
            hypothesis_id="H999",
            question="Sparse coverage test",
            signal_name="clean_signal",
            partition="train",
        )
        res = preflight.run_preflight(
            sparse_df,
            signal_col="clean_signal",
            spec=spec,
            save_results=False,
        )
        assert res.passed is False
        assert res.failure_class == "INSUFFICIENT_SAMPLE"
        assert any("coverage" in r.lower() for r in res.reasons)

    def test_leakage_guard_forbids_forward_labels_in_preflight(self, clean_synthetic_panel):
        df_leaked = clean_synthetic_panel.copy()
        df_leaked["fwd_ret_5d_pct"] = 0.05

        with pytest.raises(LeakageGuardError, match="Forward label columns"):
            preflight.run_preflight(
                df_leaked,
                signal_col="clean_signal",
            )

    def test_rejection_does_not_spend_test_budget(self, clean_synthetic_panel):
        """CRITICAL LOAD-BEARING INVARIANT (PLAN.md §6).

        A signal rejected in pre-flight never creates an Evidence or Exploration,
        so burden.count_tests remains completely unchanged.
        """
        initial_count = burden.count_tests("train")

        spec = ExperimentSpec(
            hypothesis_id="H999",
            question="Should not spend budget",
            signal_name="noisy_signal",
            partition="train",
        )
        cfg = preflight.PreFlightConfig(max_turnover=0.10)
        res = preflight.run_preflight(
            clean_synthetic_panel,
            signal_col="noisy_signal",
            spec=spec,
            cfg=cfg,
            save_results=True,
        )
        assert res.passed is False

        after_count = burden.count_tests("train")
        assert after_count == initial_count, \
            f"Pre-flight rejection must NOT increment test count! (was {initial_count}, now {after_count})"

    def test_preflight_persistence(self, clean_synthetic_panel):
        spec = ExperimentSpec(
            hypothesis_id="H998",
            question="Persistence test",
            signal_name="clean_signal",
            partition="train",
        )
        res = preflight.run_preflight(
            clean_synthetic_panel,
            signal_col="clean_signal",
            spec=spec,
            save_results=True,
        )
        saved = store.get_preflight(res.id)
        assert saved is not None
        assert saved.id == res.id
        assert saved.signal_name == "clean_signal"
