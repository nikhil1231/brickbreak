"""`persistence` — Research state, object store, immutable manifests, and data budget ledger (the refactor plan §3, §5.6, §2.1).

The four core objects:
Hypothesis -> Exploration -> Signal -> Evidence

Exports:
- `models`: Hypothesis, Exploration, Signal, Evidence, Edge, IdeaGraph
- `store`: File-backed atomic CRUD for research objects
- `manifest`: Immutable cryptographic experiment manifests
- `ledger`: Sample budget ledger tracking partition exposure
- `migration`: Ingests and migrates HYPOTHESES.md (H001–H038)
"""
from __future__ import annotations

from . import ledger, manifest, migration, models, store
from .ledger import BudgetExhaustedError, SampleBudgetLedger
from .manifest import build_manifest, load_manifest, save_manifest, verify_manifest
from .models import Edge, Evidence, Exploration, Hypothesis, IdeaGraph, PreFlightResult, Signal
from .store import (
    void_exploration,
    add_evidence,
    get_evidence,
    get_exploration,
    get_hypothesis,
    get_idea_graph,
    get_preflight,
    get_signal,
    list_evidence,
    list_explorations,
    list_hypotheses,
    list_preflights,
    list_signals,
    save_exploration,
    save_hypothesis,
    save_preflight,
    save_signal,
)

__all__ = [
    "BudgetExhaustedError",
    "void_exploration",
    "Edge",
    "Evidence",
    "Exploration",
    "Hypothesis",
    "IdeaGraph",
    "PreFlightResult",
    "SampleBudgetLedger",
    "Signal",
    "add_evidence",
    "build_manifest",
    "get_evidence",
    "get_exploration",
    "get_hypothesis",
    "get_idea_graph",
    "get_preflight",
    "get_signal",
    "ledger",
    "list_evidence",
    "list_explorations",
    "list_hypotheses",
    "list_preflights",
    "list_signals",
    "manifest",
    "migration",
    "models",
    "save_exploration",
    "save_hypothesis",
    "save_manifest",
    "save_preflight",
    "save_signal",
    "store",
    "verify_manifest",
]

