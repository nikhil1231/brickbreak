"""Firewall package (PLAN.md §6, §7 and Stage X)."""
from __future__ import annotations

from .exposure import (
    WEEKLY_OUTCOME_ACCESS_CEILING,
    ExposureEntry,
    ExposureLevel,
    ExposureLimitError,
    ExposureLogError,
    check_weekly_exposure_limit,
    load_exposure_log,
    record_exposure,
    save_exposure_log,
)
from .shape_gate import ShapeGateReport, evaluate_shape_gate
from .structural_gate import StructuralGateReport, evaluate_structural_gate
from .zones import (
    FirewallAccessError,
    FirewallZone,
    assert_zone_frame_access,
    enforce_research_guard,
)

__all__ = [
    "FirewallZone",
    "FirewallAccessError",
    "assert_zone_frame_access",
    "enforce_research_guard",
    "ExposureLevel",
    "ExposureLimitError",
    "ExposureLogError",
    "ExposureEntry",
    "WEEKLY_OUTCOME_ACCESS_CEILING",
    "load_exposure_log",
    "save_exposure_log",
    "record_exposure",
    "check_weekly_exposure_limit",
    "StructuralGateReport",
    "evaluate_structural_gate",
    "ShapeGateReport",
    "evaluate_shape_gate",
]
