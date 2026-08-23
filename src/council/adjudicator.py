"""Council adjudicator (PLAN.md §4, §10 and Stage AA).

Preserves disagreements, ranks dossiers by expected information gain,
and produces frozen candidates without silently averaging dissent into certainty.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from ..contracts.dossier import DossierDissent, MechanismDossier
from .critics import (
    CriticReview,
    review_economic_mechanism,
    review_leakage_and_pit,
    review_power_and_costs,
)
from .novelty import NoveltyReport, check_dossier_novelty

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdjudicationResult:
    dossier: MechanismDossier
    approved: bool
    priority_score: float
    reviews: tuple[CriticReview, ...]
    novelty: NoveltyReport
    all_dissents: tuple[DossierDissent, ...]
    verdict: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dossier": self.dossier.to_dict(),
            "approved": self.approved,
            "priority_score": self.priority_score,
            "reviews": [r.to_dict() for r in self.reviews],
            "novelty": self.novelty.to_dict(),
            "all_dissents": [d.to_dict() for d in self.all_dissents],
            "verdict": self.verdict,
        }


def compute_expected_information_score(dossier: MechanismDossier,
                                       reviews: Sequence[CriticReview],
                                       novelty: NoveltyReport) -> float:
    """Compute expected-information score from PLAN.md §10."""
    mean_review_score = float(np.mean([r.score for r in reviews])) if reviews else 5.0
    novelty_multiplier = 1.2 if novelty.is_novel else 0.5
    cost_margin = max(1.0, dossier.min_effect_bps / 40.0)

    score = mean_review_score * novelty_multiplier * cost_margin
    return round(float(score), 2)


import numpy as np


def adjudicate_dossier(dossier: MechanismDossier,
                       existing_claims: Sequence[dict[str, str]] | None = None
                       ) -> AdjudicationResult:
    """Evaluate a dossier across all council critics and adjudicate approval."""
    r_econ = review_economic_mechanism(dossier)
    r_leak = review_leakage_and_pit(dossier)
    r_power = review_power_and_costs(dossier)
    reviews = (r_econ, r_leak, r_power)

    novelty = check_dossier_novelty(dossier, existing_claims)

    all_dissents = list(dossier.dissents)
    for r in reviews:
        all_dissents.extend(r.dissents)

    # Check fatal objections
    has_fatal = any(d.severity == "fatal" for d in all_dissents)
    all_approved = all(r.approved for r in reviews) and novelty.is_novel and not has_fatal

    priority = compute_expected_information_score(dossier, reviews, novelty)

    if all_approved:
        verdict = f"APPROVED with priority {priority:.2f}. {len(all_dissents)} dissent(s) noted."
    else:
        verdict = f"REJECTED. Fatal objections or critic disapproval. {len(all_dissents)} dissent(s)."

    # Return new dossier copy with aggregated dissents
    updated_dossier = MechanismDossier(
        dossier_id=dossier.dossier_id,
        hypothesis_id=dossier.hypothesis_id,
        family=dossier.family,
        claim=dossier.claim,
        population=dossier.population,
        expected_horizon_days=dossier.expected_horizon_days,
        observable_facts=dossier.observable_facts,
        interpretation=dossier.interpretation,
        causal_chain=dossier.causal_chain,
        counterparty=dossier.counterparty,
        counterparty_persistence_rationale=dossier.counterparty_persistence_rationale,
        competing_explanations=dossier.competing_explanations,
        strongest_baseline=dossier.strongest_baseline,
        unique_predictions=dossier.unique_predictions,
        natural_falsifiers=dossier.natural_falsifiers,
        confounds=dossier.confounds,
        capacity_notes=dossier.capacity_notes,
        min_effect_bps=dossier.min_effect_bps,
        nearest_hypothesis_ids=dossier.nearest_hypothesis_ids,
        required_observations_absent=dossier.required_observations_absent,
        memory_risk_classification=dossier.memory_risk_classification,
        forward_confirmation_path=dossier.forward_confirmation_path,
        proposer=dossier.proposer,
        hostile_reviewer=dossier.hostile_reviewer,
        dissents=tuple(all_dissents),
    )

    return AdjudicationResult(
        dossier=updated_dossier,
        approved=all_approved,
        priority_score=priority,
        reviews=reviews,
        novelty=novelty,
        all_dissents=tuple(all_dissents),
        verdict=verdict,
    )
