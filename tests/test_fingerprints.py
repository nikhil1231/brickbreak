"""Fingerprint verification tests for H026 and H024 (the refactor plan, Stage B target, line 676).

Verifies that H024 and H026 both produce full alpha evaluation fingerprints
matching their established properties.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.alpha_eval import evaluate_signal
from src.research_data import frame


@pytest.mark.skipif(
    not (pd.io.common.Path("data/normalized/screen_metrics_asof.parquet").exists()
         and pd.io.common.Path("data/normalized/daily_context.parquet").exists()
         and pd.io.common.Path("data/normalized/daily_bars_adj.parquet").exists()),
    reason="requires built normalized data files on disk"
)
class TestFingerprints:
    """Evaluates H026 and H024 against the standard alpha evaluation battery."""

    @pytest.fixture(scope="class")
    @classmethod
    def train_data(cls):
        df = frame.load_daily_panel(
            partition="train",
            include_context=True,
        )
        # Attach forward returns
        df["fwd_ret_5d_pct"] = frame.forward_return(df, horizon=5)
        df["fwd_ret_10d_pct"] = frame.forward_return(df, horizon=10)
        df["fwd_ret_20d_pct"] = frame.forward_return(df, horizon=20)
        return df

    def test_h026_fingerprint(self, train_data):
        """H026: Mean percentile rank of rs_60d_vs_mkt and sector_breadth.

        Established properties (HYPOTHESES.md):
        - Positive rank IC with forward returns
        - Positive monotonicity across quantiles
        - Positive Q5 - Q1 spread
        """
        df = train_data.dropna(subset=["rs_60d_vs_mkt", "sector_breadth"]).copy()
        for col in ("rs_60d_vs_mkt", "sector_breadth"):
            df[f"{col}_pctile"] = df.groupby("date")[col].rank(pct=True)
        df["h026_score"] = (df["rs_60d_vs_mkt_pctile"] + df["sector_breadth_pctile"]) / 2.0

        rep = evaluate_signal(
            df,
            signal_col="h026_score",
            forward_col="fwd_ret_10d_pct",
            horizons=(5, 10, 20),
            run_backtest=True,
            run_neutralisation=True,
        )

        # 1. Structure
        assert "predictive_content" in rep
        assert "quantiles" in rep
        assert "neutralisation" in rep
        assert "canonical_backtest" in rep

        # 2. Predictive content: Positive mean IC
        primary_ic = rep["predictive_content"]["primary_ic"]
        assert primary_ic["mean_ic"] > 0, \
            f"H026 should show positive mean IC on train, got {primary_ic['mean_ic']}"

        # 3. Quantile profile: Positive spread
        q5_spread = rep["quantiles"]["q5_spread_pct"]
        assert q5_spread > 0, \
            f"H026 should show positive Q5-Q1 spread on train, got {q5_spread}"

        # 4. Neutralisation: check that neutralisation was performed
        neu = rep["neutralisation"]
        assert "raw_mean_ic" in neu
        assert "neutralized_mean_ic" in neu

    def test_h024_fingerprint(self, train_data):
        """H024: Proximity to 52-week high (dist_52w_high).

        Established properties (HYPOTHESES.md):
        - Higher dist_52w_high (closer to 0%) produces positive forward return in sample
        - Signal is scorable and has high persistence
        """
        df = train_data.dropna(subset=["dist_52w_high"]).copy()
        # dist_52w_high is negative or zero (e.g. -5% means 5% below high); higher is closer to high
        df["h024_score"] = df["dist_52w_high"]

        rep = evaluate_signal(
            df,
            signal_col="h024_score",
            forward_col="fwd_ret_10d_pct",
            horizons=(5, 10, 20),
            run_backtest=True,
            run_neutralisation=True,
        )

        # 1. Structure
        assert "predictive_content" in rep
        assert "quantiles" in rep
        assert "signal_mechanics" in rep

        # 2. Signal mechanics: dist_52w_high is highly persistent (autocorrelation > 0.8)
        sm = rep["signal_mechanics"]
        assert sm["autocorrelation_1d"] > 0.8, \
            f"dist_52w_high should have high autocorrelation, got {sm['autocorrelation_1d']}"

        # 3. Canonical backtest ran
        bt = rep["canonical_backtest"]
        assert "portfolio" in bt
        assert "market_benchmark" in bt
