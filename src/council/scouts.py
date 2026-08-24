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
The lab's primary discovery question is:

Can AI identify weak, repeatable conditional relationships in relatively
inefficient parts of the market, where an individual researcher's small size is
an advantage?

This is an individual researcher's bootstrap lab: trading capital is INR 5-10
lakh, proprietary-data spend is USD 0 by default, and existing public/PIT data
must be used before acquiring another source. Prefer daily-or-slower hypotheses
in capacity-compatible NSE names defined by point-in-time liquidity, never by a
present-day market-cap or index snapshot.

Search for modest but repeatable conditional shifts in under-covered,
capacity-constrained or operationally awkward pockets—not only large
unconditional anomalies. Small capacity is positive when INR 5-10 lakh can be
deployed at conservative participation and cost assumptions while the same edge
is too limited or inconvenient for institutional capital. Do not reject an idea
merely because it cannot scale to a fund. Conversely, do not confuse raw
illiquidity, an untradeable print or uncompensated market impact with an edge.
capacity_notes must state why small size is an advantage, what point-in-time
liquidity makes the trade executable, and why larger capital would not fully
arbitrage the relationship.

Keep the predictive claim separate from the causal interpretation. A daily
observable such as delivery percentage cannot by itself identify an institution
or parent order. Do not make institutional-grade ownership, fund-flow, full-depth
order-book, or trade-classification data a prerequisite when the incremental
predictive claim can be tested honestly without it.

Classify data explicitly:
- available_observations: already in the supplied catalogue;
- required_feature_names: the exact predictor columns the minimum executable
  test will read; never include a forward-return or outcome column;
- required_observations_absent: ONLY hard blockers for the minimum valid test;
- optional_observations_absent: enrichment or causal confirmation that does not
  block the minimum test.
Estimate incremental engineering days and cash cost. Bootstrap candidates should
normally require no paid source and at most two engineering days. Target at least
80 bps gross when the conservative round-trip cost is 40 bps.

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
nearest_hypothesis_ids, available_observations,
required_observations_absent, optional_observations_absent,
estimated_engineering_days, estimated_cash_cost_usd,
required_feature_names, data_adapter, entry_price, outcome_kind, signal_kind,
memory_risk_classification, and forward_confirmation_path.

Execution semantics are contractual, not prose. data_adapter must be one of
daily_panel_asof_open, intraday_panel, or replay. entry_price must be open,
close, or intraday; outcome_kind is raw or market_excess; signal_kind is dense
or selector. Choose intraday_panel/intraday whenever a same-session fixed-time
observation is required—the daily adapter cannot approximate it.

nearest_hypothesis_ids must name the closest prior ledger node even when the new
claim reverses or contradicts it. It may be empty only when the supplied ledger
is empty.

Respond strictly in valid JSON matching the MechanismDossier schema."""

_REQUIRED_DOSSIER_FIELDS = (
    "claim", "population", "expected_horizon_days", "observable_facts",
    "interpretation", "causal_chain", "counterparty",
    "counterparty_persistence_rationale", "competing_explanations",
    "strongest_baseline", "unique_predictions", "natural_falsifiers",
    "confounds", "capacity_notes", "min_effect_bps",
    "nearest_hypothesis_ids", "available_observations",
    "required_observations_absent", "optional_observations_absent",
    "estimated_engineering_days", "estimated_cash_cost_usd",
    "required_feature_names", "data_adapter", "entry_price", "outcome_kind",
    "signal_kind",
    "memory_risk_classification", "forward_confirmation_path",
)


def build_scout_prompt(lens: ScoutLens,
                       domain_hint: str = "",
                       catalogue_features: Sequence[str] = (),
                       graveyard_notes: Sequence[str] = ()) -> str:
    """Construct prompt tailored to the scout lens."""
    return f"""SCOUT LENS: {lens.value.upper()}
Domain Hint: {domain_hint or 'Identify unmined economic phenomena'}
Available Catalogue Features: {list(catalogue_features)}
Hypothesis Ledger (including graveyard): {list(graveyard_notes)}

Propose a novel, bootstrap-affordable mechanism dossier under this lens. Focus
on weak, repeatable conditional relationships caused by persistent economic
friction rather than technical indicator fitting. Prefer inefficient pockets
where the INR 5-10 lakh book's small size is an explicit advantage. A claim that
needs expensive optional evidence must remain a modest predictive claim until
that evidence exists."""


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
        available_observations=tuple(data.get("available_observations", ())),
        optional_observations_absent=tuple(
            data.get("optional_observations_absent", ())),
        estimated_engineering_days=float(data.get("estimated_engineering_days", 0.0)),
        estimated_cash_cost_usd=float(data.get("estimated_cash_cost_usd", 0.0)),
        required_feature_names=tuple(data["required_feature_names"]),
        data_adapter=str(data["data_adapter"]),
        entry_price=str(data["entry_price"]),
        outcome_kind=str(data["outcome_kind"]),
        signal_kind=str(data["signal_kind"]),
    )
