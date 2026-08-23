from __future__ import annotations

import json

import pytest

from src.interface import director_api


def test_execute_requires_explicit_outcome_confirmation(monkeypatch):
    called = []
    monkeypatch.setattr(
        director_api, "execute_contract",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )

    with pytest.raises(director_api.DirectorAPIError,
                       match="confirm_outcome_access"):
        director_api.execute({"contract_id": "EC_TEST"})

    assert called == []


def test_attack_is_idempotent_after_review_is_persisted(tmp_path, monkeypatch):
    dossier_dir = tmp_path / "dossiers"
    adjudication_dir = tmp_path / "adjudications"
    dossier_dir.mkdir()
    adjudication_dir.mkdir()
    dossier_id = "DOS_EXISTING"
    # A persisted review must be returned before another provider call. The
    # dossier itself only needs to exist because the API verifies its target.
    dossier = {
        "dossier_id": dossier_id,
        "hypothesis_id": "PROP_EXISTING",
        "family": "test",
        "claim": "A claim",
        "population": "NSE equities",
        "expected_horizon_days": 5,
        "observable_facts": ["Lagged fact"],
        "interpretation": "Interpretation",
        "causal_chain": "A sufficiently described causal chain",
        "counterparty": "Counterparty",
        "counterparty_persistence_rationale": "A persistent operational constraint",
        "competing_explanations": ["Alternative one", "Alternative two"],
        "strongest_baseline": "Momentum",
        "unique_predictions": ["Prediction"],
        "natural_falsifiers": ["Falsifier"],
        "confounds": [],
        "capacity_notes": "Retail scale",
        "min_effect_bps": 50.0,
        "nearest_hypothesis_ids": [],
        "required_observations_absent": [],
        "memory_risk_classification": "anonymous",
        "forward_confirmation_path": "Forward lane",
        "proposer": "claude:scout",
        "hostile_reviewer": "codex:critic",
        "dissents": [],
        "created_at": "2026-08-23 00:00:00",
    }
    (dossier_dir / f"{dossier_id}.json").write_text(json.dumps(dossier))
    prior = {"dossier": dossier, "approved": False, "verdict": "REJECTED"}
    prior_path = adjudication_dir / f"{dossier_id}.json"
    prior_path.write_text(json.dumps(prior))
    monkeypatch.setattr(director_api, "DOSSIERS_DIR", dossier_dir)
    monkeypatch.setattr(director_api, "ADJUDICATIONS_DIR", adjudication_dir)
    monkeypatch.setattr(
        director_api, "route_council_call",
        lambda *args, **kwargs: pytest.fail("reviewer must not run twice"),
    )

    result = director_api.attack({"dossier_id": dossier_id})

    assert result == {"adjudication": prior, "path": str(prior_path)}
