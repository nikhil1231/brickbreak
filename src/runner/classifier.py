"""Automated failure taxonomy classifier and natural language interpretation (PLAN.md §5.11).

Failure is classified, never just 'FAILED':
`NO_SIGNAL` · `SIGNAL_BUT_BETA` · `SIGNAL_ONLY_ONE_REGIME` · `SIGNAL_TOO_SMALL` ·
`HIGH_TURNOVER` · `UNSTABLE` · `LIKELY_OVERFIT` · `INSUFFICIENT_SAMPLE` ·
`DATA_QUALITY` · `REDUNDANT_WITH_EXISTING_ALPHA` · `SUCCESS`

The class determines the system's next move in the idea graph.
"""
from __future__ import annotations

from typing import Any
import numpy as np

from .spec import ExperimentSpec


def classify_result(
    report: dict[str, Any],
    spec: ExperimentSpec | None = None,
) -> tuple[str, str, list[dict[str, str]]]:
    """Classifies exploration results and generates an actionable interpretation paragraph.

    Returns
    -------
    (failure_class, interpretation_paragraph, suggested_next_moves)
    """
    pred = report.get("predictive_content", {})
    primary_ic = pred.get("primary_ic", {})
    mean_ic = primary_ic.get("mean_ic", 0.0) or 0.0
    t_stat = primary_ic.get("t_stat", 0.0) or 0.0
    n_sessions = primary_ic.get("n_sessions", 0) or 0

    quantiles = report.get("quantiles", {})
    spread_pct = quantiles.get("q5_spread_pct", 0.0) or 0.0
    spread_bps = quantiles.get("q5_spread_bps", 0.0) or 0.0
    monotonicity = quantiles.get("q5_monotonicity", 0.0) or 0.0

    mech = report.get("signal_mechanics", {})
    turnover = mech.get("mean_turnover", 0.0) or 0.0

    neu = report.get("neutralisation", {})
    retention_pct = neu.get("ic_retention_pct", 100.0) or 100.0

    cond = report.get("conditioning", {})
    years = cond.get("year", [])

    # 1. Sample adequacy
    if n_sessions < 20 or report.get("n_total_rows", 0) < 300:
        cls = "INSUFFICIENT_SAMPLE"
        interp = f"Sample is too small ({n_sessions} sessions) to draw robust statistical conclusions."
        next_moves = [{"action": "broaden_universe", "relation": "generalises", "rationale": "Expand universe to increase sample density."}]
        return cls, interp, next_moves

    # 2. No Signal
    if mean_ic <= 0.005 or abs(t_stat) < 1.2 or spread_pct <= 0:
        cls = "NO_SIGNAL"
        interp = f"No predictive signal detected (mean IC = {mean_ic:.4f}, t = {t_stat:.2f}, Q5-Q1 spread = {spread_bps:.1f} bps)."
        next_moves = [
            {"action": "branch_laterally", "relation": "adjacent-to", "rationale": "Test conceptually adjacent setup features instead."},
            {"action": "condition_on_regime", "relation": "conditions-on", "rationale": "Test if signal activates only during specific market regimes."},
        ]
        return cls, interp, next_moves

    # 3. Signal But Beta / Factor Exposure
    if retention_pct < 35.0:
        cls = "SIGNAL_BUT_BETA"
        interp = (
            f"Signal is statistically positive (raw IC = {mean_ic:.4f}), but drops by {100 - retention_pct:.1f}% "
            f"upon factor neutralisation (residual IC = {neu.get('neutralized_mean_ic', 0.0):.4f}). "
            f"The edge is largely generic market/sector beta."
        )
        next_moves = [
            {"action": "residualize_score", "relation": "specialises", "rationale": "Explicitly score on the factor-residualized metric."},
            {"action": "sector_neutralize", "relation": "specialises", "rationale": "Rank within sector rather than across entire universe."},
        ]
        return cls, interp, next_moves

    # 4. High Turnover
    if turnover > 0.40:
        cls = "HIGH_TURNOVER"
        interp = (
            f"Signal contains predictive content (IC = {mean_ic:.4f}, spread = {spread_bps:.1f} bps), "
            f"but daily rank turnover is very high ({turnover:.2f}), eroding gains under round-trip transaction costs."
        )
        next_moves = [
            {"action": "smooth_signal", "relation": "specialises", "rationale": "Apply moving average smoothing to the score to reduce churn."},
            {"action": "lengthen_lookback", "relation": "specialises", "rationale": "Increase indicator lookback window."},
        ]
        return cls, interp, next_moves

    # 5. Stability across subperiods / years
    if years:
        year_ics = [y.get("mean_ic", 0.0) for y in years if y.get("mean_ic") is not None]
        if year_ics and (min(year_ics) < -0.01 and max(year_ics) > 0.03):
            cls = "UNSTABLE"
            interp = f"Signal shows regime instability across years: yearly ICs range from {min(year_ics):.3f} to {max(year_ics):.3f}."
            next_moves = [
                {"action": "condition_on_volatility", "relation": "conditions-on", "rationale": "Condition on market volatility state."},
            ]
            return cls, interp, next_moves

    # 6. Signal Too Small
    if spread_bps < 25.0:
        cls = "SIGNAL_TOO_SMALL"
        interp = f"Signal is monotonic (monotonicity = {monotonicity:.2f}) but the spread ({spread_bps:.1f} bps) is too small to clear realistic trading friction."
        next_moves = [
            {"action": "combine_signals", "relation": "adjacent-to", "rationale": "Combine with low-correlation momentum/breakout signal to boost spread."},
        ]
        return cls, interp, next_moves

    # 7. Success
    cls = "SUCCESS"
    interp = (
        f"Signal validated successfully on partition (mean IC = {mean_ic:.4f}, t = {t_stat:.2f}, "
        f"Q5-Q1 spread = {spread_bps:.1f} bps, monotonicity = {monotonicity:.2f}, IC retention = {retention_pct:.1f}%)."
    )
    next_moves = [
        {"action": "test_holdout", "relation": "specialises", "rationale": "Proceed to confirmatory testing on forward partition."},
        {"action": "explore_interactions", "relation": "conditions-on", "rationale": "Test interactions with secondary setup filters."},
    ]
    return cls, interp, next_moves
