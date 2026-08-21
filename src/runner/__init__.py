"""`runner` — Research exploration runner and experiment automation (the refactor plan §5.5, §5.7, §5.11, §5.12).

Exports:
- `spec`: `ExperimentSpec`, `validate_spec`, `SpecValidationError`
- `classifier`: `classify_result` implementing the §5.11 failure taxonomy
- `compare`: `compare_signals` for multi-signal comparison and ensembling
- `runner`: `run_exploration` orchestrator
"""
from __future__ import annotations

from . import classifier, compare, gate, preflight, preregistration, queue, runner, spec
from .classifier import classify_result
from .compare import compare_signals
from .gate import (DispatchGateRefusalError, DispatchRateLimitExceededError,
                   RateLimitPolicy, check_dispatch_allowance, enforce_dispatch_gate,
                   gate_status)
from .preflight import PreFlightConfig, PreFlightResult, run_preflight
from .preregistration import compute_batch_hash, preregister_batch
from .queue import compute_priority_score, enqueue_proposal, list_queue, rank_queue
from .runner import run_exploration
from .spec import ExperimentSpec, SpecValidationError, validate_spec

__all__ = [
    "DispatchGateRefusalError",
    "DispatchRateLimitExceededError",
    "ExperimentSpec",
    "PreFlightConfig",
    "PreFlightResult",
    "RateLimitPolicy",
    "SpecValidationError",
    "check_dispatch_allowance",
    "classifier",
    "classify_result",
    "compare",
    "compare_signals",
    "compute_batch_hash",
    "compute_priority_score",
    "enforce_dispatch_gate",
    "enqueue_proposal",
    "gate",
    "gate_status",
    "list_queue",
    "preflight",
    "preregister_batch",
    "preregistration",
    "queue",
    "rank_queue",
    "run_exploration",
    "run_preflight",
    "runner",
    "spec",
    "validate_spec",
]

