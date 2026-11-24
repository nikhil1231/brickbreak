"""Unit tests for alpha evaluation suite (the refactor plan §5.8–§5.10)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.alpha_eval import backtest, diagnostics, neutralisation, report


class TestDiagnostics:
    def test_cluster_stats_basic(self):
        # Create 10 clusters of 5 observations with intra-cluster shift
        np.random.seed(42)
        dates = np.repeat(pd.date_range("2023-01-01", periods=10), 5)
        # Cluster shifts: mean of each cluster is positive
        cluster_shifts = np.repeat(np.random.uniform(0.5, 1.5, size=10), 5)
        y = pd.Series(cluster_shifts + np.random.normal(0, 0.1, size=50))
        dates = pd.Series(dates)

        res = diagnostics.cluster_stats(y, dates)
        assert res["n"] == 50
        assert res["n_dates"] == 10
        assert res["mean"] > 0
        assert np.isfinite(res["t"])
        assert np.isfinite(res["naive_t"])
        # With strong positive cluster correlation, naive standard error is deflated, so naive_t > t
        assert res["naive_t"] >= res["t"]

    def test_rank_ic_perfect_signal(self):
        # Construct synthetic daily data where signal perfectly predicts forward return
        dates = np.repeat(pd.date_range("2023-01-01", periods=5), 20)
        np.random.seed(0)
        signal = np.tile(np.arange(20, dtype=float), 5)
        fwd_ret = signal * 1.5 + np.tile(np.random.normal(0, 0.01, size=20), 5)

        df = pd.DataFrame({"date": dates, "signal": signal, "fwd_ret": fwd_ret})
        res = diagnostics.rank_ic(df, "signal", "fwd_ret", min_symbols=5)
        assert res["mean_ic"] > 0.95
        assert res["positive_ic_pct"] == 100.0
        assert res["n_sessions"] == 5

    def test_quantile_profile_monotonic(self):
        # Monotonic ascending returns across 5 quantiles
        dates = np.repeat(pd.date_range("2023-01-01", periods=10), 50)
        signal = np.tile(np.linspace(1, 100, 50), 10)
        fwd_ret = signal * 0.1  # higher signal -> strictly higher return

        df = pd.DataFrame({"date": dates, "signal": signal, "fwd_ret": fwd_ret})
        qp = diagnostics.quantile_profile(df, "signal", "fwd_ret", q=5)
        assert qp["monotonicity"] == 1.0
        assert qp["spread_pct"] > 0
        assert len(qp["quantiles"]) == 5
        assert qp["quantiles"][4]["mean"] > qp["quantiles"][0]["mean"]

    def test_signal_mechanics(self):
        # 5 dates, 10 symbols: static signal -> 0 turnover, 1.0 autocorrelation
        dates = np.repeat(pd.date_range("2023-01-01", periods=5), 10)
        symbols = np.tile([f"SYM_{i}" for i in range(10)], 5)
        signal = np.tile(np.arange(10, dtype=float), 5)

        df = pd.DataFrame({"date": dates, "symbol": symbols, "signal": signal})
        sm = diagnostics.signal_mechanics(df, "signal")
        assert sm["mean_turnover"] == 0.0
        assert sm["autocorrelation_1d"] == 1.0
        assert sm["mean_coverage_names"] == 10.0

    def test_sparse_selector_is_paired_to_baseline_at_same_take_rate(self):
        rng = np.random.default_rng(7)
        dates = np.repeat(pd.date_range("2023-01-01", periods=40), 10)
        rank = np.tile(np.arange(10, dtype=float), 40)
        selector = np.where(rank >= 8, rank, np.nan)
        outcomes = rank * 0.10 + rng.normal(0, 0.05, len(rank))
        df = pd.DataFrame({
            "date": dates,
            "selector": selector,
            "baseline": -rank,
            "fwd_ret_1d_pct": outcomes,
        })
        result = diagnostics.selector_vs_baseline(
            df, "selector", "baseline", "fwd_ret_1d_pct")
        assert result["n_selected"] == 80
        assert result["n_sessions"] == 40
        assert result["lift_bps"] > 50
        assert result["lift_t"] > 2


class TestNeutralisation:
    def test_cross_sectional_residualize_orthogonal(self):
        np.random.seed(42)
        n = 100
        dates = np.repeat(pd.date_range("2023-01-01", periods=5), 20)
        beta = np.random.uniform(0.5, 1.5, size=n)
        momentum = np.random.normal(0, 5.0, size=n)
        # Signal is partly beta and momentum plus noise
        signal = 2.0 * beta + 0.5 * momentum + np.random.normal(0, 0.5, size=n)

        df = pd.DataFrame({"date": dates, "signal": signal, "beta": beta, "mom": momentum})
        resids = neutralisation.cross_sectional_residualize(df, "signal", ["beta", "mom"], min_symbols=10)
        df["resid"] = resids

        # Check that residual is substantially uncorrelated with beta per session
        for _, g in df.groupby("date"):
            r_beta, _ = np.corrcoef(g["resid"], g["beta"])[0, 1], None
            assert abs(r_beta) < 1e-4

    def test_orthogonal_projection_detects_pure_factor(self):
        dates = np.repeat(pd.date_range("2023-01-01", periods=10), 20)
        beta = np.random.uniform(0.5, 1.5, size=200)
        # Score is algebraically beta with tiny noise
        score = beta + np.random.normal(0, 0.001, size=200)

        df = pd.DataFrame({"date": dates, "score": score, "beta": beta})
        res = neutralisation.orthogonal_projection_test(df, "score", "beta")
        assert res["is_pure_factor"] is True
        assert "H038" in res["verdict"]


class TestBacktest:
    def test_span_stats_charges_cash(self):
        # 100 days total: Strategy A is invested 100 days earning 0.1% a day
        r_a = np.full(100, 0.001)
        stats_a = backtest.span_stats(r_a)

        # Strategy B earns 0.2% on 50 days and sits in cash (0.0%) for 50 days (total return same, but active only half time)
        r_b = np.concatenate([np.full(50, 0.002), np.zeros(50)])
        is_live_b = np.concatenate([np.ones(50, dtype=bool), np.zeros(50, dtype=bool)])
        # If charged for full span of 100 days, CAGR is computed over 100 days:
        stats_b_full_span = backtest.span_stats(r_b)

        assert stats_a["n_sessions"] == 100
        assert stats_b_full_span["n_sessions"] == 100
        # Both compounded over 100 calendar days have very similar CAGRs:
        assert abs(stats_a["cagr_pct"] - stats_b_full_span["cagr_pct"]) < 1.0


class TestReportGenerator:
    def test_evaluate_signal_smoke(self):
        np.random.seed(42)
        dates = np.repeat(pd.date_range("2023-01-01", periods=10), 25)
        symbols = np.tile([f"SYM_{i}" for i in range(25)], 10)
        signal = np.random.normal(0, 1, size=250)
        fwd_5d = signal * 0.5 + np.random.normal(0, 1, size=250)
        fwd_10d = signal * 0.8 + np.random.normal(0, 1, size=250)
        beta = np.random.uniform(0.8, 1.2, size=250)

        df = pd.DataFrame({
            "date": dates,
            "symbol": symbols,
            "my_signal": signal,
            "fwd_ret_5d_pct": fwd_5d,
            "fwd_ret_10d_pct": fwd_10d,
            "beta": beta,
        })

        rep = report.evaluate_signal(
            df,
            signal_col="my_signal",
            forward_col="fwd_ret_5d_pct",
            horizons=(5, 10),
            run_backtest=False,  # Skip backtest here to avoid requiring daily bars parquet on disk
            run_neutralisation=True,
        )

        assert rep["signal"] == "my_signal"
        assert "predictive_content" in rep
        assert "quantiles" in rep
        assert "signal_mechanics" in rep
        assert "neutralisation" in rep
        assert rep["predictive_content"]["primary_ic"]["mean_ic"] is not None
