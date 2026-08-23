"""Tests for Stage AA AI Research Council."""
from __future__ import annotations

import argparse
import json

import pytest

from src.contracts.dossier import MechanismDossier
from src.council import (
    ScoutLens,
    adjudicate_dossier,
    build_scout_prompt,
    check_dossier_novelty,
    parse_dossier_json,
    review_economic_mechanism,
    review_leakage_and_pit,
    review_power_and_costs,
)
from src.providers import ProviderError, ProviderType


def _sample_dossier():
    return MechanismDossier(
        dossier_id="DOS_TEST",
        hypothesis_id="H047",
        family="opening_window",
        claim="Post-auction opening supply absorption predicts intraday momentum",
        population="Liquid NIFTY 500",
        expected_horizon_days=5,
        observable_facts=("Opening auction print", "First 15-min volume"),
        interpretation="Institutional accumulation",
        causal_chain="Large institutions absorbing morning sell flow over multiple sessions",
        counterparty="Impatient morning liquidity seekers",
        counterparty_persistence_rationale="Execution mandates requiring open participation",
        competing_explanations=("Random morning inventory noise", "Temporary bid-ask bounce"),
        strongest_baseline="Mechanical 20d momentum sort",
        unique_predictions=("Strongest on morning gap-down followed by quick recovery",),
        natural_falsifiers=("Fails completely on earnings announcement days",),
        confounds=("Quarterly result dates",),
        capacity_notes="Liquid top 500",
        min_effect_bps=55.0,
        nearest_hypothesis_ids=(),
        required_observations_absent=(),
        memory_risk_classification="anonymised_unrecognised",
        forward_confirmation_path="Accrue 60 clean forward sessions",
        proposer="scout_market_structure",
        hostile_reviewer="critic_economic",
    )


def test_scout_prompt_and_json_parsing():
    prompt = build_scout_prompt(ScoutLens.MARKET_STRUCTURE, domain_hint="Auction prints")
    assert "MARKET_STRUCTURE" in prompt
    assert "Auction prints" in prompt

    mock_json = """
    {
      "claim": "Morning auction volume imbalance",
      "population": "NIFTY 200",
      "expected_horizon_days": 10,
      "observable_facts": ["Auction price vs prev close"],
      "interpretation": "Flow imbalance",
      "causal_chain": "Hedging orders execute at open",
      "counterparty": "Passive market makers",
      "counterparty_persistence_rationale": "Obligation to quote spreads",
      "competing_explanations": ["Random noise", "Spread noise"],
      "strongest_baseline": "Mechanical 5d return",
      "unique_predictions": ["High volume gap"],
      "natural_falsifiers": ["Low volume session"],
      "confounds": [],
      "capacity_notes": "Liquid",
      "min_effect_bps": 50.0,
      "nearest_hypothesis_ids": [],
      "required_observations_absent": [],
      "memory_risk_classification": "anonymised_unrecognised",
      "forward_confirmation_path": "Accrue 60 clean forward sessions"
    }
    """
    dossier = parse_dossier_json(mock_json, dossier_id="D1", hypothesis_id="H048", family="opening", proposer="scout")
    assert dossier.claim == "Morning auction volume imbalance"
    assert dossier.min_effect_bps == 50.0
    assert len(dossier.competing_explanations) == 2


def test_scout_parser_rejects_missing_fields_instead_of_inventing_a_dossier():
    with pytest.raises(ValueError, match="omitted required dossier fields"):
        parse_dossier_json(
            '{"claim": "A fluent but incomplete idea"}',
            dossier_id="D_BAD",
            hypothesis_id="H999",
            family="general",
            proposer="scout",
        )


def test_critics_and_leakage_detection():
    dos = _sample_dossier()

    # Clean reviews
    r_econ = review_economic_mechanism(dos)
    assert r_econ.approved
    r_leak = review_leakage_and_pit(dos)
    assert r_leak.approved
    r_power = review_power_and_costs(dos)
    assert r_power.approved

    # Plant lookahead in facts
    bad_dos = MechanismDossier(
        dossier_id=dos.dossier_id,
        hypothesis_id=dos.hypothesis_id,
        family=dos.family,
        claim=dos.claim,
        population=dos.population,
        expected_horizon_days=dos.expected_horizon_days,
        observable_facts=("entry_day_next_close",),
        interpretation=dos.interpretation,
        causal_chain=dos.causal_chain,
        counterparty=dos.counterparty,
        counterparty_persistence_rationale=dos.counterparty_persistence_rationale,
        competing_explanations=dos.competing_explanations,
        strongest_baseline=dos.strongest_baseline,
        unique_predictions=dos.unique_predictions,
        natural_falsifiers=dos.natural_falsifiers,
        confounds=dos.confounds,
        capacity_notes=dos.capacity_notes,
        min_effect_bps=dos.min_effect_bps,
        nearest_hypothesis_ids=(),
        required_observations_absent=(),
        memory_risk_classification="anon",
        forward_confirmation_path="fwd",
        proposer=dos.proposer,
        hostile_reviewer=dos.hostile_reviewer,
    )
    r_leak_bad = review_leakage_and_pit(bad_dos)
    assert not r_leak_bad.approved
    assert any(d.severity == "fatal" for d in r_leak_bad.dissents)


def test_novelty_and_adjudication():
    dos = _sample_dossier()
    nov = check_dossier_novelty(dos)
    assert nov.is_novel

    adj = adjudicate_dossier(dos)
    assert adj.approved
    assert adj.priority_score > 5.0
    assert "APPROVED" in adj.verdict


def test_discover_cli_persists_a_deterministically_named_dossier(
        tmp_path, monkeypatch):
    from src.interface.cli import council as council_cli

    response = json.dumps(_sample_dossier().to_dict())
    monkeypatch.setattr(
        council_cli,
        "route_council_call",
        lambda *args, **kwargs: (response, ProviderType.CLAUDE),
    )
    output = tmp_path / "dossier.json"
    args = argparse.Namespace(
        lens="market_structure", hint="", hypothesis="H048",
        family="opening_window", provider="claude", output=str(output),
    )

    assert council_cli.cmd_discover(args) == 0
    stored = json.loads(output.read_text())
    assert stored["dossier_id"].startswith("DOS_MARK_")
    assert stored["dossier_hash"]


def test_discover_cli_reports_provider_failure_without_canned_fallback(
        tmp_path, monkeypatch):
    from src.interface.cli import council as council_cli

    def fail(*args, **kwargs):
        raise ProviderError("subscription unavailable")

    monkeypatch.setattr(council_cli, "route_council_call", fail)
    args = argparse.Namespace(
        lens="market_structure", hint="", hypothesis="H048",
        family="general", provider="claude",
        output=str(tmp_path / "must_not_exist.json"),
    )
    assert council_cli.cmd_discover(args) == 1
    assert not (tmp_path / "must_not_exist.json").exists()
