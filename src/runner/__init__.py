"""`runner` — Research exploration runner and experiment automation (the refactor plan §5.5, §5.7, §5.11, §5.12).

Exports:
- `spec`: `ExperimentSpec`, `validate_spec`, `SpecValidationError`
- `classifier`: `classify_result` implementing the §5.11 failure taxonomy
- `compare`: `compare_signals` for multi-signal comparison and ensembling
- `runner`: `run_exploration` orchestrator
"""
from __future__ import annotations

from . import classifier, compare, preflight, runner, spec
from .classifier import classify_result
from .compare import compare_signals
from .preflight import PreFlightConfig, PreFlightResult, run_preflight
from .runner import run_exploration
from .spec import ExperimentSpec, SpecValidationError, validate_spec

__all__ = [
    "ExperimentSpec",
    "PreFlightConfig",
    "PreFlightResult",
    "SpecValidationError",
    "classifier",
    "classify_result",
    "compare",
    "compare_signals",
    "preflight",
    "run_exploration",
    "run_preflight",
    "runner",
    "spec",
    "validate_spec",
]
