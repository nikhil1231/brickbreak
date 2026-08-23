"""Specialized critic roles in the AI Research Council (PLAN.md §4 and Stage AA).

Roles:
- ECONOMIC_CRITIC: attacks counterparty and persistence arguments.
- LEAKAGE_ADVERSARY: attacks timestamps, revisions, survivorship, identity leakage.
- POWER_REVIEWER: evaluates sample shape, independent blocks, detectable effect vs costs.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from ..contracts.dossier import DossierDissent, MechanismDossier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CriticReview:
    critic_role: str
    approved: bool
    score: float  # 0.0 to 10.0
    critique: str
    dissents: tuple[DossierDissent, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "critic_role": self.critic_role,
            "approved": self.approved,
            "score": self.score,
            "critique": self.critique,
            "dissents": [d.to_dict() for d in self.dissents],
        }


def review_economic_mechanism(dossier: MechanismDossier) -> CriticReview:
    """Economic critic review."""
    dissents = []
    score = 8.0

    # Attack counterparty rationale
    if len(dossier.counterparty_persistence_rationale) < 15:
        score -= 2.0
        dissents.append(DossierDissent("economic_critic", "Thin counterparty persistence rationale", "material"))

    if dossier.min_effect_bps < 40.0:
        score -= 3.0
        dissents.append(DossierDissent("economic_critic", "Claimed effect sits below 40 bps round-trip cost floor", "fatal"))

    approved = score >= 5.0 and not any(d.severity == "fatal" for d in dissents)
    return CriticReview(
        critic_role="economic_critic",
        approved=approved,
        score=score,
        critique="Evaluated economic persistence and counterparty constraints.",
        dissents=tuple(dissents),
    )


def review_leakage_and_pit(dossier: MechanismDossier) -> CriticReview:
    """Leakage adversary review."""
    dissents = []
    score = 9.0

    # Check for known lookahead trap keywords in facts
    banned_in_facts = ("next_close", "full_day_volume", "size_tier_rank", "todays_close")
    for fact in dossier.observable_facts:
        if any(b in fact.lower() for b in banned_in_facts):
            score -= 5.0
            dissents.append(DossierDissent("leakage_adversary", f"Suspected lookahead in fact: {fact}", "fatal"))

    approved = score >= 5.0 and not any(d.severity == "fatal" for d in dissents)
    return CriticReview(
        critic_role="leakage_adversary",
        approved=approved,
        score=score,
        critique="Checked timestamp and point-in-time fact definitions.",
        dissents=tuple(dissents),
    )


def review_power_and_costs(dossier: MechanismDossier) -> CriticReview:
    """Power reviewer."""
    dissents = []
    score = 8.5

    if dossier.expected_horizon_days > 20:
        score -= 1.5
        dissents.append(DossierDissent("power_reviewer", "Horizon > 20d reduces independent calendar blocks", "advisory"))

    approved = score >= 5.0
    return CriticReview(
        critic_role="power_reviewer",
        approved=approved,
        score=score,
        critique="Evaluated statistical power, horizon, and sample requirements.",
        dissents=tuple(dissents),
    )
