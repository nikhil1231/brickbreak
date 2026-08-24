"""Novelty curation and idea graph linkage (PLAN.md §4 and Stage AA).

Novelty is evaluated across three dimensions:
1. Semantic overlap in mechanism, counterparty, population and falsifier.
2. Overlap in required data and transformation.
3. Graph proximity to known findings and graveyard nulls.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from ..contracts.dossier import MechanismDossier

logger = logging.getLogger(__name__)


def _tokens(*parts: object) -> set[str]:
    return set(re.findall(r"[a-z0-9]{4,}", " ".join(map(str, parts)).lower()))


def _similarity(left: set[str], right: set[str]) -> float:
    return len(left & right) / max(len(left | right), 1) if left and right else 0.0


def _ledger_claims() -> list[dict[str, str]]:
    """Read the complete durable ledger rather than a hand-picked shortlist."""
    from ..persistence import store

    return [
        {
            "id": hypothesis.id,
            "claim": " ".join((
                hypothesis.title, hypothesis.statement, hypothesis.rationale)),
            "family": hypothesis.family,
        }
        for hypothesis in store.list_hypotheses()
    ]


@dataclass(frozen=True)
class NoveltyReport:
    is_novel: bool
    lineage_complete: bool
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
    claims = _ledger_claims() if existing_claims is None else list(existing_claims)
    known_ids = {c.get("id", "") for c in claims}

    target_claim = _tokens(dossier.claim)
    target_context = _tokens(
        dossier.claim, dossier.population, dossier.counterparty,
        *dossier.natural_falsifiers, *dossier.required_observations_absent)
    max_sim = 0.0
    nearest_id = ""
    overlaps = []

    declared_neighbours = {
        value for value in dossier.nearest_hypothesis_ids
        if value and value != dossier.hypothesis_id
    }
    unknown_neighbours = sorted(declared_neighbours - known_ids)
    lineage_complete = not claims or bool(declared_neighbours & known_ids)
    if not dossier.nearest_hypothesis_ids and claims:
        overlaps.append(
            "No nearest hypothesis ID supplied; a new or contradictory claim "
            "must still link to the closest ledger node")
    if unknown_neighbours:
        overlaps.append(
            "Unknown nearest hypothesis ID(s): " + ", ".join(unknown_neighbours))

    for c in claims:
        other_claim = _tokens(c.get("claim", ""))
        other_context = _tokens(
            c.get("claim", ""), c.get("population", ""),
            c.get("counterparty", ""), c.get("falsifiers", ""),
            c.get("required_data", ""))
        jaccard = max(
            _similarity(target_claim, other_claim),
            _similarity(target_context, other_context),
        )

        if jaccard > max_sim:
            max_sim = jaccard
            nearest_id = c.get("id", "")

        if jaccard > 0.6:
            overlaps.append(
                f"High semantic overlap ({jaccard:.2f}) with {c.get('id', '?')}: "
                f"{c.get('claim', '')}")

    is_novel = max_sim < 0.6
    if not lineage_complete:
        verdict = "Lineage incomplete; nearest prior hypothesis must be linked"
    else:
        verdict = ("Novel mechanism proposed" if is_novel
                   else f"Potential restatement of {nearest_id}")

    return NoveltyReport(
        is_novel=is_novel,
        lineage_complete=lineage_complete,
        max_semantic_similarity=round(max_sim, 3),
        nearest_hypothesis_id=nearest_id,
        overlap_reasons=tuple(overlaps),
        verdict=verdict,
    )
