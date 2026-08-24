"""Registered E1 wrapper around the canonical session-matched shape test.

The statistical implementation lives in :mod:`alpha_eval.spread`.  Keeping a
second implementation here previously turned signed group means into a
supposedly direction-free statistic.  This module owns only the firewall
responsibility: reserve exposure before outcomes are constructed, call the one
canonical second-moment test, and attach the exposure identity.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from ..alpha_eval import spread
from .exposure import ExposureLevel, record_exposure


@dataclass(frozen=True)
class ShapeGateReport:
    passed: bool
    hypothesis_id: str
    family: str
    exposure_entry_id: str
    shape: dict

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_shape_gate(
    events: pd.DataFrame,
    outcome_loader: Callable[[], pd.DataFrame],
    hypothesis_id: str,
    family: str,
    horizon: int = 10,
    label: str = "family",
    match_on: tuple[str, ...] = (),
    dataset_version: str = "v1",
    partition: str = "train",
    batch_id: str = "SHAPE_GATE",
    actor: str = "shape_gate",
    source_id: str = "",
    exposure_path: Path | None = None,
) -> ShapeGateReport:
    """Reserve E1, then measure robust outcome dispersion without direction.

    ``outcome_loader`` is deliberately a callback. Passing a preconstructed
    outcome frame would allow label access before the exposure reservation.
    """
    if not source_id.strip():
        raise ValueError("registered shape gate requires a stable source_id")
    if horizon <= 0:
        raise ValueError("shape-gate horizon must be positive")
    exposure = record_exposure(
        hypothesis_id=hypothesis_id,
        family=family,
        batch_id=batch_id,
        level=ExposureLevel.E1_SHAPE,
        dataset_version=dataset_version,
        partition=partition,
        target_columns=[f"excess_ret_{horizon}d_pct"],
        actor=actor,
        reason=f"Registered session-matched second-moment gate for {label}",
        source_id=source_id,
        path=exposure_path,
        enforce_limit=True,
    )
    outcome_panel = outcome_loader()
    result = spread.check(
        events=events,
        panel=outcome_panel,
        horizon=horizon,
        label=label,
        match_on=match_on,
    )
    passed = str(result.get("verdict", "")).startswith("WORTH THE NEXT STAGE")
    return ShapeGateReport(
        passed=passed,
        hypothesis_id=hypothesis_id,
        family=family,
        exposure_entry_id=exposure.entry_id,
        shape=result,
    )
