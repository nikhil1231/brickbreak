"""Mechanism scouts with diverse lenses (PLAN.md §4 and Stage AA).

Lenses:
- MARKET_STRUCTURE: exchange mechanics, auction prints, margin constraints, lot sizing
- PARTICIPANT_CONSTRAINTS: institutional mandates, hedging deadlines, liquidity urgency
- EXTERNAL_RESEARCH: disclosures, earnings revisions, corporate event filings
- DATA_CATALOGUE: untapped point-in-time features in research_data catalogue
- GRAVEYARD_BRANCH: variations on failed hypotheses addressing the known failure mode
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Sequence

from ..contracts.dossier import DossierDissent, MechanismDossier
from ..providers.pool import ProviderRole, ProviderType, SubscriptionPool

logger = logging.getLogger(__name__)


class ScoutLens(str, Enum):
    MARKET_STRUCTURE = "market_structure"
    PARTICIPANT_CONSTRAINTS = "participant_constraints"
    EXTERNAL_RESEARCH = "external_research"
    DATA_CATALOGUE = "data_catalogue"
    GRAVEYARD_BRANCH = "graveyard_branch"


SCOUT_SYSTEM_PROMPT = """You are a Mechanism Scout in an AI trading research lab for NSE equities.
Your task is to propose a rigorous Mechanism Dossier (not signal code).
The dossier must explain:
1. The exact causal chain and who is persistently on the other side of the trade.
2. Why that counterparty continues their behaviour despite losing money or paying a premium (constraints/mandates/hedging).
3. At least TWO distinct competing explanations (e.g. noise, risk compensation, inventory friction).
4. Strongest simple quantitative baseline.
5. Unique testable predictions and natural falsifiers.
6. Minimum required effect after 40 bps round-trip costs.

Return every required field explicitly, including empty lists where appropriate:
claim, population, expected_horizon_days, observable_facts, interpretation,
causal_chain, counterparty, counterparty_persistence_rationale,
competing_explanations, strongest_baseline, unique_predictions,
natural_falsifiers, confounds, capacity_notes, min_effect_bps,
nearest_hypothesis_ids, required_observations_absent,
memory_risk_classification, and forward_confirmation_path.

Respond strictly in valid JSON matching the MechanismDossier schema."""

_REQUIRED_DOSSIER_FIELDS = (
    "claim", "population", "expected_horizon_days", "observable_facts",
    "interpretation", "causal_chain", "counterparty",
    "counterparty_persistence_rationale", "competing_explanations",
    "strongest_baseline", "unique_predictions", "natural_falsifiers",
    "confounds", "capacity_notes", "min_effect_bps",
    "nearest_hypothesis_ids", "required_observations_absent",
    "memory_risk_classification", "forward_confirmation_path",
)


def build_scout_prompt(lens: ScoutLens,
                       domain_hint: str = "",
                       catalogue_features: Sequence[str] = (),
                       graveyard_notes: Sequence[str] = ()) -> str:
    """Construct prompt tailored to the scout lens."""
    return f"""SCOUT LENS: {lens.value.upper()}
Domain Hint: {domain_hint or 'Identify unmined economic phenomena'}
Available Catalogue Features: {list(catalogue_features)[:20]}
Known Graveyard Findings: {list(graveyard_notes)[:5]}

Propose a novel mechanism dossier under this lens. Focus on persistent economic friction rather than technical indicator fitting."""


def parse_dossier_json(response_text: str,
                       dossier_id: str,
                       hypothesis_id: str,
                       family: str,
                       proposer: str,
                       hostile_reviewer: str = "critic_economic") -> MechanismDossier:
    """Parse scout JSON response into a validated MechanismDossier."""
    import re
    match = re.search(r"\{.*\}", response_text, re.DOTALL)
    if not match:
        raise ValueError("Could not find JSON object in scout response")

    data = json.loads(match.group(0))
    missing = [field for field in _REQUIRED_DOSSIER_FIELDS if field not in data]
    if missing:
        raise ValueError(
            "Scout response omitted required dossier fields: " + ", ".join(missing))

    return MechanismDossier(
        dossier_id=dossier_id,
        hypothesis_id=hypothesis_id,
        family=family,
        claim=str(data["claim"]),
        population=str(data["population"]),
        expected_horizon_days=int(data["expected_horizon_days"]),
        observable_facts=tuple(data["observable_facts"]),
        interpretation=str(data["interpretation"]),
        causal_chain=str(data["causal_chain"]),
        counterparty=str(data["counterparty"]),
        counterparty_persistence_rationale=str(data["counterparty_persistence_rationale"]),
        competing_explanations=tuple(data["competing_explanations"]),
        strongest_baseline=str(data["strongest_baseline"]),
        unique_predictions=tuple(data["unique_predictions"]),
        natural_falsifiers=tuple(data["natural_falsifiers"]),
        confounds=tuple(data["confounds"]),
        capacity_notes=str(data["capacity_notes"]),
        min_effect_bps=float(data["min_effect_bps"]),
        nearest_hypothesis_ids=tuple(data["nearest_hypothesis_ids"]),
        required_observations_absent=tuple(data["required_observations_absent"]),
        memory_risk_classification=str(data["memory_risk_classification"]),
        forward_confirmation_path=str(data["forward_confirmation_path"]),
        proposer=proposer,
        hostile_reviewer=hostile_reviewer,
    )
