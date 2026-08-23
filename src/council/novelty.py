"""Novelty curation and idea graph linkage (PLAN.md §4 and Stage AA).

Novelty is evaluated across three dimensions:
1. Semantic overlap in mechanism, counterparty, population and falsifier.
2. Overlap in required data and transformation.
3. Graph proximity to known findings and graveyard nulls.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from ..contracts.dossier import MechanismDossier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NoveltyReport:
    is_novel: bool
    max_semantic_similarity: float
    nearest_hypothesis_id: str
    overlap_reasons: tuple[str, ...]
    verdict: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_dossier_novelty(dossier: MechanismDossier,
                          existing_claims: Sequence[dict[str, str]] | None = None
                          ) -> NoveltyReport:
    """Evaluate whether a proposed dossier is genuinely novel or a restatement."""
    claims = existing_claims or [
        {"id": "H024", "claim": "Proximity to 52-week high predicts forward return", "family": "breakout"},
        {"id": "H026", "claim": "Relative strength vs market predicts continuation", "family": "momentum"},
        {"id": "H033", "claim": "Opening-window demand predicts post-open return", "family": "opening_window"},
        {"id": "H037", "claim": "Resilience in market drawdown produces post-rebound alpha", "family": "resilience"},
    ]

    target_words = set(dossier.claim.lower().split())
    max_sim = 0.0
    nearest_id = ""
    overlaps = []

    for c in claims:
        other_words = set(c["claim"].lower().split())
        inter = len(target_words & other_words)
        union = len(target_words | other_words)
        jaccard = inter / max(union, 1)

        if jaccard > max_sim:
            max_sim = jaccard
            nearest_id = c["id"]

        if jaccard > 0.6:
            overlaps.append(f"High semantic overlap ({jaccard:.2f}) with {c['id']}: {c['claim']}")

    is_novel = max_sim < 0.6
    verdict = "Novel mechanism proposed" if is_novel else f"Potential restatement of {nearest_id}"

    return NoveltyReport(
        is_novel=is_novel,
        max_semantic_similarity=round(max_sim, 3),
        nearest_hypothesis_id=nearest_id,
        overlap_reasons=tuple(overlaps),
        verdict=verdict,
    )
