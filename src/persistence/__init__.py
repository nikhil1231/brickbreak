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
from .models import (BatchManifest, Edge, Evidence, Exploration, Hypothesis,
                     IdeaGraph, PreFlightResult, QueueProposal, Signal)
from .store import (
    void_exploration,
    add_evidence,
    get_batch,
    get_evidence,
    get_exploration,
    get_hypothesis,
    get_idea_graph,
    get_preflight,
    get_proposal,
    get_signal,
    list_batches,
    list_evidence,
    list_explorations,
    list_hypotheses,
    list_preflights,
    list_proposals,
    list_signals,
    next_proposal_id,
    save_batch,
    save_exploration,
    save_hypothesis,
    save_preflight,
    save_proposal,
    save_signal,
)

__all__ = [
    "BatchManifest",
    "BudgetExhaustedError",
    "void_exploration",
    "Edge",
    "Evidence",
    "Exploration",
    "Hypothesis",
    "IdeaGraph",
    "PreFlightResult",
    "QueueProposal",
    "SampleBudgetLedger",
    "Signal",
    "add_evidence",
    "build_manifest",
    "get_batch",
    "get_evidence",
    "get_exploration",
    "get_hypothesis",
    "get_idea_graph",
    "get_preflight",
    "get_proposal",
    "get_signal",
    "ledger",
    "list_batches",
    "list_evidence",
    "list_explorations",
    "list_hypotheses",
    "list_preflights",
    "list_proposals",
    "list_signals",
    "manifest",
    "migration",
    "models",
    "next_proposal_id",
    "save_batch",
    "save_exploration",
    "save_hypothesis",
    "save_manifest",
    "save_preflight",
    "save_proposal",
    "save_signal",
    "store",
    "verify_manifest",
]


