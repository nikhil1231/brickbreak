"""Contracts package (PLAN.md §3 and Stage W)."""
from __future__ import annotations

from .data_contract import DataContract, SourceFieldDef
from .dossier import DossierDissent, MechanismDossier
from .experiment_contract import ExperimentContract
from .lifecycle import (
    IllegalLifecycleTransitionError,
    LifecycleState,
    LifecycleTracker,
    StateTransitionRecord,
    validate_transition,
)

__all__ = [
    "MechanismDossier",
    "DossierDissent",
    "DataContract",
    "SourceFieldDef",
    "ExperimentContract",
    "LifecycleState",
    "LifecycleTracker",
    "StateTransitionRecord",
    "IllegalLifecycleTransitionError",
    "validate_transition",
]
