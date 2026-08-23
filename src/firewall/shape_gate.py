"""Shape pre-flight gate (E1 — controlled outcome exposure, PLAN.md §7.2).

When dispersion/separability is part of the reason to pursue a family, the
shape gate tests whether outcomes across candidate cells exhibit excess
dispersion compared to a session-matched permutation null.

Consumes an E1 exposure slot and records to the exposure ledger.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .exposure import ExposureLevel, record_exposure

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShapeGateReport:
    passed: bool
    hypothesis_id: str
    family: str
    n_events: int
    n_sessions: int
    observed_dispersion: float
    null_p50_dispersion: float
    null_p95_dispersion: float
    excess_dispersion_ratio: float
    min_required_excess_ratio: float
    p_value: float
    verdict_statement: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_shape_gate(df: pd.DataFrame,
                        hypothesis_id: str,
                        family: str,
                        group_col: str,
                        outcome_col: str,
                        date_col: str = "date",
                        min_required_excess_ratio: float = 1.25,
                        n_permutations: int = 200,
                        seed: int = 42,
                        record_exposure_log: bool = True
                        ) -> ShapeGateReport:
    """Evaluate E1 shape gate measuring excess outcome dispersion across groups."""
    if outcome_col not in df.columns or group_col not in df.columns:
        raise ValueError(f"Columns {group_col!r} or {outcome_col!r} missing from frame")

    clean = df.dropna(subset=[group_col, outcome_col, date_col]).copy()
    if clean.empty or clean[group_col].nunique() < 2:
        return ShapeGateReport(
            passed=False,
            hypothesis_id=hypothesis_id,
            family=family,
            n_events=len(clean),
            n_sessions=0,
            observed_dispersion=0.0,
            null_p50_dispersion=0.0,
            null_p95_dispersion=0.0,
            excess_dispersion_ratio=0.0,
            min_required_excess_ratio=min_required_excess_ratio,
            p_value=1.0,
            verdict_statement="Insufficient data or single group in shape gate",
        )

    # Calculate observed dispersion: standard deviation of group mean outcomes
    group_means = clean.groupby(group_col)[outcome_col].mean()
    obs_disp = float(group_means.std())

    # Build session-matched permutation null: shuffle group labels WITHIN session date
    rng = np.random.default_rng(seed)
    null_disps = []

    for _ in range(n_permutations):
        # Permute within date
        shuffled = clean.groupby(date_col, group_keys=False)[group_col].apply(
            lambda s: pd.Series(rng.permutation(s.values), index=s.index)
        )
        null_means = clean.groupby(shuffled)[outcome_col].mean()
        null_disps.append(float(null_means.std()))

    null_arr = np.array(null_disps)
    null_p50 = float(np.percentile(null_arr, 50))
    null_p95 = float(np.percentile(null_arr, 95))

    p_val = float((null_arr >= obs_disp).mean())
    ratio = round(obs_disp / max(null_p50, 1e-6), 2)

    passed = (ratio >= min_required_excess_ratio) and (p_val <= 0.05)

    if passed:
        verdict = (
            f"Shape gate PASSED: observed dispersion {obs_disp:.3f} is {ratio:.2f}x "
            f"the median null ({null_p50:.3f}), p={p_val:.3f}. Outcomes are separable."
        )
    else:
        verdict = (
            f"Shape gate FAILED: observed dispersion {obs_disp:.3f} ratio {ratio:.2f}x "
            f"is below hurdle {min_required_excess_ratio:.2f}x or p={p_val:.3f} > 0.05. "
            f"No excess outcome separability detected."
        )

    if record_exposure_log:
        record_exposure(
            hypothesis_id=hypothesis_id,
            family=family,
            batch_id="SHAPE_GATE",
            level=ExposureLevel.E1_SHAPE,
            dataset_version="v1",
            partition="train",
            target_columns=[outcome_col],
            actor="shape_gate",
            reason=f"Registered shape gate on {group_col} vs {outcome_col}",
            enforce_limit=True,
        )

    return ShapeGateReport(
        passed=passed,
        hypothesis_id=hypothesis_id,
        family=family,
        n_events=len(clean),
        n_sessions=int(clean[date_col].nunique()),
        observed_dispersion=round(obs_disp, 4),
        null_p50_dispersion=round(null_p50, 4),
        null_p95_dispersion=round(null_p95, 4),
        excess_dispersion_ratio=ratio,
        min_required_excess_ratio=min_required_excess_ratio,
        p_value=round(p_val, 4),
        verdict_statement=verdict,
    )
