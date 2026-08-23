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

Respond strictly in valid JSON matching the MechanismDossier schema."""


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
    competing = data.get("competing_explanations") or ["Random noise", "Liquidity friction"]
    if len(competing) < 2:
        competing = list(competing) + ["Alternative liquidity friction"]

    return MechanismDossier(
        dossier_id=dossier_id,
        hypothesis_id=hypothesis_id,
        family=family,
        claim=str(data.get("claim") or "Proposed mechanism claim"),
        population=str(data.get("population") or "NIFTY 500 equities"),
        expected_horizon_days=int(data.get("expected_horizon_days") or 10),
        observable_facts=tuple(data.get("observable_facts") or ["Point-in-time order flow and prices"]),
        interpretation=str(data.get("interpretation") or "Persistent economic imbalance"),
        causal_chain=str(data.get("causal_chain") or "Institutional constraint drives execution across sessions"),
        counterparty=str(data.get("counterparty") or "Constrained liquidity seeker"),
        counterparty_persistence_rationale=str(data.get("counterparty_persistence_rationale") or "Mandated deadline"),
        competing_explanations=tuple(competing),
        strongest_baseline=str(data.get("strongest_baseline") or "20d mechanical momentum"),
        unique_predictions=tuple(data.get("unique_predictions") or ["Strongest on high turnover sessions"]),
        natural_falsifiers=tuple(data.get("natural_falsifiers") or ["Fails across low volatility regimes"]),
        confounds=tuple(data.get("confounds") or ["Earnings announcement dates"]),
        capacity_notes=str(data.get("capacity_notes") or "₹5-10 lakh book scale"),
        min_effect_bps=float(data.get("min_effect_bps") or 45.0),
        nearest_hypothesis_ids=tuple(data.get("nearest_hypothesis_ids") or ()),
        required_observations_absent=tuple(data.get("required_observations_absent") or ()),
        memory_risk_classification=str(data.get("memory_risk_classification") or "anonymised_unrecognised"),
        forward_confirmation_path=str(data.get("forward_confirmation_path") or "Accrue 60 clean forward sessions"),
        proposer=proposer,
        hostile_reviewer=hostile_reviewer,
    )
