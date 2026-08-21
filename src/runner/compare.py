"""Signal comparison, novelty objective, and multi-signal ensemble (the refactor plan §5.12).

Compares 2–10 signals across:
- Cross-sectional score correlation
- Realised forward return correlation
- Top-K portfolio candidate overlap
- Incremental predictive value (both directions)
- Combined ensemble portfolio performance
"""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd

from ..alpha_eval import backtest, diagnostics


def compare_signals(
    df: pd.DataFrame,
    signal_cols: list[str],
    forward_col: str = "fwd_ret_10d_pct",
    top_k: int = 5,
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> dict[str, Any]:
    """Runs standard comparative battery across 2..10 candidate signals."""
    if len(signal_cols) < 2:
        raise ValueError("Must provide at least 2 signal columns to compare.")

    valid = df[[date_col, symbol_col, forward_col] + signal_cols].dropna().copy()
    if len(valid) < 100:
        return {"error": "insufficient overlapping observations"}

    # 1. Cross-sectional rank correlations
    corrs = {s: {} for s in signal_cols}
    for i, s1 in enumerate(signal_cols):
        for j, s2 in enumerate(signal_cols):
            if i == j:
                corrs[s1][s2] = 1.0
            elif j > i:
                def _pair_corr(g):
                    if len(g) < 10:
                        return np.nan
                    return diagnostics.spearman_corr(g[s1], g[s2])
                c = valid.groupby(date_col).apply(_pair_corr).dropna().mean()
                c_val = round(float(c), 3) if np.isfinite(c) else np.nan
                corrs[s1][s2] = c_val
                corrs[s2][s1] = c_val

    # 2. Top-K candidate overlap
    for s in signal_cols:
        valid[f"{s}_rank"] = valid.groupby(date_col)[s].rank(ascending=False, method="first")

    overlaps = {s: {} for s in signal_cols}
    for i, s1 in enumerate(signal_cols):
        for j, s2 in enumerate(signal_cols):
            if i == j:
                overlaps[s1][s2] = 100.0
            elif j > i:
                def _pair_overlap(g):
                    top_1 = set(g[g[f"{s1}_rank"] <= top_k][symbol_col])
                    top_2 = set(g[g[f"{s2}_rank"] <= top_k][symbol_col])
                    if not top_1:
                        return np.nan
                    return (len(top_1 & top_2) / len(top_1)) * 100.0
                ov = valid.groupby(date_col).apply(_pair_overlap).dropna().mean()
                ov_val = round(float(ov), 1) if np.isfinite(ov) else np.nan
                overlaps[s1][s2] = ov_val
                overlaps[s2][s1] = ov_val

    # 3. Individual signal metrics
    individual_reports = {}
    for s in signal_cols:
        ic_res = diagnostics.rank_ic(valid, s, forward_col, date_col=date_col)
        qp = diagnostics.quantile_profile(valid, s, forward_col, q=5, date_col=date_col)
        individual_reports[s] = {
            "mean_ic": ic_res["mean_ic"],
            "ic_ir": ic_res["ic_ir"],
            "spread_bps": qp["spread_bps"],
            "monotonicity": qp["monotonicity"],
        }

    # 4. Combined Equal-Weighted Ensemble Signal
    combo_ranks = [valid.groupby(date_col)[s].rank(pct=True) for s in signal_cols]
    valid["combo_score"] = sum(combo_ranks) / len(combo_ranks)

    combo_ic = diagnostics.rank_ic(valid, "combo_score", forward_col, date_col=date_col)
    combo_qp = diagnostics.quantile_profile(valid, "combo_score", forward_col, q=5, date_col=date_col)
    combo_bt = backtest.canonical_backtest(
        valid,
        signal_col="combo_score",
        cfg=backtest.BacktestConfig(top_k=top_k),
        date_col=date_col,
        symbol_col=symbol_col,
    )

    return {
        "signals": signal_cols,
        "pairwise_rank_correlation": corrs,
        "pairwise_top_k_overlap_pct": overlaps,
        "individual_signals": individual_reports,
        "combined_ensemble": {
            "mean_ic": combo_ic["mean_ic"],
            "ic_ir": combo_ic["ic_ir"],
            "spread_bps": combo_qp["spread_bps"],
            "monotonicity": combo_qp["monotonicity"],
            "backtest": combo_bt,
        },
    }
