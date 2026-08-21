"""The discretionary lab — cases, decisions, baselines, replay.

MISSION.md asks a different question from the one the signal path answers.
The signal path asks *what rule predicts returns*; this package asks

    can an AI, given rich point-in-time context, identify unusually attractive
    trading opportunities better than strong simple quantitative baselines?

THE UNIT OF WORK IS A CASE, NOT A COLUMN
A signal is a function over the whole panel, scored by rank IC and a quantile
spread. A case is one (symbol, session) situation with a dossier, and a
decision is what a judge committed against it *before the future was revealed*.
Nothing in the signal path can express "the AI took 61 of these 500 and skipped
the rest, and here is whether that selection beat top-N-by-score on the same
500" — that sentence is what this package exists to produce.

THE DISTINCTION THAT MATTERS
Candidate generation and discretionary selection are different jobs.

    generation  — broad, high-recall, systematic, deliberately not optimised
    selection   — the thing under test

A generator tuned until it looks profitable has stolen the experiment: whatever
lift the selector then shows is measured against a baseline that already
contains the answer. Generators are frozen in the definition, and re-tuning one
is a new test against the sample, not a free adjustment.

WHAT IS BORROWED WHOLESALE, AND WHY NONE OF IT IS RE-IMPLEMENTED
Everything below the unit of work already exists and is stricter than anything
written from scratch would be: point-in-time access and forward labels
(`research_data.frame`), the partition split and its purge (`research_data.splits`),
the sample-budget ledger, the dispatch gate, multiplicity accounting
(`runner.burden`), leakage guards (`alpha_eval.guards`), session-clustered and
Hansen-Hodrick inference (`alpha_eval.diagnostics`), and the manifest. A replay
spends the sample exactly like an exploration does and is counted the same way.
"""
from __future__ import annotations

__all__ = ["opportunity", "generators", "case", "prompt", "decision",
           "decider", "providers"]
