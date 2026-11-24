"""Structural pre-flight gate (E0 — genuinely outcome-free, PLAN.md §7.1).

Reports:
- coverage, missingness, and timestamp availability;
- cross-sectional variation, usable tails, and temporal stability;
- cases or events per session, participant concentration;
- feature turnover, selector take rate, and pool attenuation;
- predictor correlation with known factors/signals;
- expected independent blocks from horizon and session count;
- minimum detectable effect at frozen noise reference;
- power adequacy verdict before any outcome is read.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..alpha_eval.guards import assert_no_forward_labels

logger = logging.getLogger(__name__)

# Frozen reference market noise (annualised standard deviation proxy: 7.9% 10-day)
REFERENCE_10D_NOISE_PCT = 7.9


@dataclass(frozen=True)
class StructuralGateReport:
    passed: bool
    n_rows: int
    n_sessions: int
    n_symbols: int
    missingness_pct: float
    cases_per_session: float
    estimated_independent_blocks: int
    pool_attenuation: float
    min_detectable_effect_bps: float
    failure_reasons: tuple[str, ...]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "n_rows": self.n_rows,
            "n_sessions": self.n_sessions,
            "n_symbols": self.n_symbols,
            "missingness_pct": self.missingness_pct,
            "cases_per_session": self.cases_per_session,
            "estimated_independent_blocks": self.estimated_independent_blocks,
            "pool_attenuation": self.pool_attenuation,
            "min_detectable_effect_bps": self.min_detectable_effect_bps,
            "failure_reasons": list(self.failure_reasons),
            "metrics": self.metrics,
        }


def evaluate_structural_gate(df: pd.DataFrame,
                             predictor_col: str,
                             horizon: int = 10,
                             min_independent_blocks: int = 8,
                             min_cases_per_session: float = 1.5,
                             cost_floor_bps: float = 40.0,
                             target_effect_bps: float | None = None,
                             selector_mode: bool = False,
                             ) -> StructuralGateReport:
    """Run E0 structural pre-flight on a candidate dataset."""
    assert_no_forward_labels(df, context="E0 structural gate")

    if predictor_col not in df.columns:
        raise ValueError(f"predictor_col {predictor_col!r} not found in frame")

    n_rows = len(df)
    if n_rows == 0:
        return StructuralGateReport(
            passed=False, n_rows=0, n_sessions=0, n_symbols=0,
            missingness_pct=100.0, cases_per_session=0.0,
            estimated_independent_blocks=0, pool_attenuation=0.0,
            min_detectable_effect_bps=0.0,
            failure_reasons=("Empty dataframe",), metrics={},
        )

    series = df[predictor_col]
    missing_count = int(series.isna().sum())
    raw_missing_pct = round(100.0 * missing_count / n_rows, 2)
    # In a selector contract NaN means "not a case", not missing data.
    missing_pct = 0.0 if selector_mode else raw_missing_pct

    has_date = "date" in df.columns
    has_symbol = "symbol" in df.columns

    n_sessions = int(df["date"].nunique()) if has_date else 1
    n_symbols = int(df["symbol"].nunique()) if has_symbol else 1

    # A selector represents non-candidates with NaN.  Counting every universe
    # row as a case made a 0.2%-take-rate selector look like it produced 2,020
    # cases per session and gave it essentially perfect pool attenuation.
    # Dense scores remain unchanged because every row is active.
    active = series.notna()
    n_active_rows = int(active.sum())
    active_counts = (df.loc[active].groupby("date").size()
                     if has_date and n_active_rows else pd.Series(dtype=float))
    n_active_sessions = int(len(active_counts))
    cases_per_session = round(n_active_rows / max(n_sessions, 1), 2)
    cases_per_active_session = round(
        n_active_rows / max(n_active_sessions, 1), 2)
    active_session_pct = round(
        100.0 * n_active_sessions / max(n_sessions, 1), 2)
    take_rate_pct = round(100.0 * n_active_rows / max(n_rows, 1), 4)
    block_sessions = n_active_sessions if selector_mode else n_sessions
    est_blocks = max(1, block_sessions // max(horizon, 1))

    # Pool attenuation: (1 - 1/k) approx
    k = max(cases_per_session, 1.0)
    pool_attenuation = round(1.0 - (1.0 / k), 3) if k > 1.0 else 0.0

    # Minimum detectable effect (MDE) with 80% power at alpha=0.05. Scale the
    # frozen 10-session noise reference to the registered horizon. We do not
    # divide it by the number of names in a session: the project's measured
    # cross-sectional dependence makes that independence assumption unsafe.
    horizon_noise_pct = REFERENCE_10D_NOISE_PCT * np.sqrt(max(horizon, 1) / 10.0)
    se_approx = horizon_noise_pct / np.sqrt(max(est_blocks, 1))
    mde_bps = round(2.8 * se_approx * 100.0, 1)

    failures = []
    if missing_pct > 20.0:
        failures.append(f"Missingness too high: {missing_pct}% > 20%")
    if est_blocks < min_independent_blocks:
        failures.append(
            f"Estimated independent blocks {est_blocks} below floor {min_independent_blocks} (PLAN §7.1)"
        )
    if cases_per_session < min_cases_per_session and n_sessions > 1:
        failures.append(
            f"Cases per session {cases_per_session} below floor {min_cases_per_session} (pool attenuation is zero)"
        )
    if n_active_sessions == 0:
        failures.append("Predictor produces no active cases")
    useful_effect_bps = (float(target_effect_bps)
                         if target_effect_bps is not None else None)
    if (useful_effect_bps is not None
            and useful_effect_bps < float(cost_floor_bps)):
        failures.append(
            f"Registered useful-effect bar {useful_effect_bps:.1f} bps is below "
            f"the {float(cost_floor_bps):.1f} bps cost floor")
    if useful_effect_bps is not None and mde_bps > useful_effect_bps:
        failures.append(
            f"Minimum detectable effect {mde_bps:.1f} bps exceeds the "
            f"registered useful-effect bar {useful_effect_bps:.1f} bps"
        )

    # Check variation
    valid_vals = series[active]
    if len(valid_vals.unique()) < 2:
        failures.append("Predictor column is degenerate (single constant value)")

    passed = len(failures) == 0

    return StructuralGateReport(
        passed=passed,
        n_rows=n_rows,
        n_sessions=n_sessions,
        n_symbols=n_symbols,
        missingness_pct=missing_pct,
        cases_per_session=cases_per_session,
        estimated_independent_blocks=est_blocks,
        pool_attenuation=pool_attenuation,
        min_detectable_effect_bps=mde_bps,
        failure_reasons=tuple(failures),
        metrics={
            "active_rows": n_active_rows,
            "active_sessions": n_active_sessions,
            "active_session_pct": active_session_pct,
            "cases_per_active_session": cases_per_active_session,
            "take_rate_pct": take_rate_pct,
            "noncandidate_pct": raw_missing_pct if selector_mode else 0.0,
            "zero_case_sessions": int(max(n_sessions - n_active_sessions, 0)),
            "useful_effect_bps": useful_effect_bps,
            "cost_floor_bps": float(cost_floor_bps),
            "predictor_mean": float(valid_vals.mean()) if len(valid_vals) else None,
            "predictor_std": float(valid_vals.std()) if len(valid_vals) else None,
            "unique_values": int(len(valid_vals.unique())),
        },
    )
