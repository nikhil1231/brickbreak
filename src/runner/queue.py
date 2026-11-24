"""Deep research queue for high-throughput candidate generation (PLAN.md §5, Stage 0 & Stage 2).

Maintains an unbounded deep queue of candidate proposals, ranked by expected
effect size, mechanism clarity, and orthogonality, rather than dispatching
immediately upon generation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ..persistence import QueueProposal, store

logger = logging.getLogger(__name__)


def compute_priority_score(
    rationale: str,
    expected_spread_bps: float = 0.0,
    has_preflight_passed: bool = False,
    is_orthogonal: bool = True,
) -> float:
    """Ranks candidates by expected effect size and economic prior (PLAN.md §2.1, §5)."""
    score = 0.0

    # 1. Expected spread relative to 40 bps round-trip transaction costs
    if expected_spread_bps > 40.0:
        score += (expected_spread_bps - 40.0) * 1.5
    else:
        score += max(-50.0, (expected_spread_bps - 40.0) * 2.0)

    # 2. Economic mechanism & counterparty clarity
    if rationale and len(rationale.strip()) > 30:
        score += 25.0

    # 3. Pre-flight passed
    if has_preflight_passed:
        score += 50.0

    # 4. Orthogonality
    if is_orthogonal:
        score += 15.0

    return round(score, 2)


def enqueue_proposal(
    title: str,
    question: str,
    signal_name: str,
    hypothesis_id: str,
    family: str = "general",
    rationale: str = "",
    expected_spread_bps: float = 0.0,
    priority_score: float | None = None,
) -> QueueProposal:
    """Enqueue a new candidate proposal into the deep queue."""
    p_id = store.next_proposal_id()
    if priority_score is None:
        priority_score = compute_priority_score(
            rationale=rationale,
            expected_spread_bps=expected_spread_bps,
        )

    prop = QueueProposal(
        id=p_id,
        title=title,
        question=question,
        signal_name=signal_name,
        hypothesis_id=hypothesis_id,
        family=family,
        rationale=rationale,
        expected_spread_bps=expected_spread_bps,
        priority_score=priority_score,
        status="queued",
    )
    store.save_proposal(prop)
    return prop


def list_queue(status: str | None = None) -> list[QueueProposal]:
    """List proposals in the deep queue, optionally filtered by status."""
    return store.list_proposals(status=status)


def rank_queue() -> list[QueueProposal]:
    """Sort and update queue proposals by priority score (descending)."""
    proposals = store.list_proposals()
    # Re-evaluate priority scores
    for p in proposals:
        has_pf = bool(p.status == "preflight_passed")
        p.priority_score = compute_priority_score(
            rationale=p.rationale,
            expected_spread_bps=p.expected_spread_bps,
            has_preflight_passed=has_pf,
        )
        store.save_proposal(p)

    return sorted(proposals, key=lambda x: x.priority_score, reverse=True)


def prune_stale_proposals(max_age_days: int = 30) -> int:
    """Mark proposals older than max_age_days as expired."""
    cutoff = datetime.now() - timedelta(days=max_age_days)
    count = 0
    for p in store.list_proposals(status="queued"):
        try:
            created = datetime.strptime(p.created_at, "%Y-%m-%d %H:%M:%S")
            if created < cutoff:
                p.status = "expired"
                store.save_proposal(p)
                count += 1
        except Exception:
            continue
    return count
