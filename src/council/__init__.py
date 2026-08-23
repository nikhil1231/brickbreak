"""AI Research Council package (PLAN.md §4 and Stage AA)."""
from __future__ import annotations

from .adjudicator import AdjudicationResult, adjudicate_dossier
from .critics import (
    HOSTILE_REVIEW_SYSTEM_PROMPT,
    CriticReview,
    build_hostile_review_prompt,
    parse_hostile_review,
    review_economic_mechanism,
    review_leakage_and_pit,
    review_power_and_costs,
)
from .novelty import NoveltyReport, check_dossier_novelty
from .scouts import (
    SCOUT_SYSTEM_PROMPT,
    ScoutLens,
    build_scout_prompt,
    parse_dossier_json,
)

__all__ = [
    "ScoutLens",
    "SCOUT_SYSTEM_PROMPT",
    "build_scout_prompt",
    "parse_dossier_json",
    "CriticReview",
    "HOSTILE_REVIEW_SYSTEM_PROMPT",
    "build_hostile_review_prompt",
    "parse_hostile_review",
    "review_economic_mechanism",
    "review_leakage_and_pit",
    "review_power_and_costs",
    "NoveltyReport",
    "check_dossier_novelty",
    "AdjudicationResult",
    "adjudicate_dossier",
]
