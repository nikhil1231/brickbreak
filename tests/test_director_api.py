from __future__ import annotations

import json

import pytest

from src.interface import director_api


def test_dispatch_persists_run_before_discovery_finishes(tmp_path, monkeypatch):
    monkeypatch.setattr(director_api, "RUNS_DIR", tmp_path / "runs")
    observed = {}

    def fake_discover(payload):
        path = director_api._run_path(payload["run_id"])
        observed.update(json.loads(path.read_text()))
        return {"dossier": {
            "dossier_id": "DOS_DURABLE",
            "claim": "A durable mechanism",
            "has_data_gap": False,
        }}

    monkeypatch.setitem(
        director_api.POST_OPERATIONS, "/api/director/discover", fake_discover)
    result = director_api.dispatch_post("/api/director/discover", {
        "run_id": "RUN_DURABLE_001",
        "lens": "market_structure",
        "provider": "codex",
        "model": "gpt-test",
    })

    assert observed["status"] == "running"
    assert observed["stage"] == "discover"
    assert observed["provider"] == "codex"
    assert observed["model"] == "gpt-test"
    persisted = json.loads(
        director_api._run_path("RUN_DURABLE_001").read_text())
    assert persisted["dossier_id"] == "DOS_DURABLE"
    assert persisted["claim"] == "A durable mechanism"
    assert persisted["stage"] == "attack"
    assert persisted["status"] == "ready"
    assert result["run"] == persisted


def test_dispatch_persists_discovery_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(director_api, "RUNS_DIR", tmp_path / "runs")

    def fail_discover(_payload):
        raise RuntimeError("provider vanished")

    monkeypatch.setitem(
        director_api.POST_OPERATIONS, "/api/director/discover", fail_discover)
    with pytest.raises(director_api.DirectorAPIError,
                       match="provider vanished"):
        director_api.dispatch_post("/api/director/discover", {
            "run_id": "RUN_DURABLE_002",
            "provider": "codex",
        })

    persisted = json.loads(
        director_api._run_path("RUN_DURABLE_002").read_text())
    assert persisted["status"] == "failed"
    assert persisted["stage"] == "discover"
    assert "provider vanished" in persisted["error"]


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
        "nearest_hypothesis_ids": ["H001"],
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


def test_failed_independent_attack_can_be_waived_without_erasing_it(
        tmp_path, monkeypatch):
    dossier_dir = tmp_path / "dossiers"
    adjudication_dir = tmp_path / "adjudications"
    dossier_dir.mkdir()
    adjudication_dir.mkdir()
    dossier_id = "DOS_FAILED_MODEL"
    dossier = {
        "dossier_id": dossier_id,
        "hypothesis_id": "PROP_FAILED_MODEL",
        "family": "test",
        "claim": "A weak conditional relationship for a small book",
        "population": "Capacity-constrained NSE equities",
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
        "capacity_notes": "Executable for INR 5-10 lakh but too small for funds",
        "min_effect_bps": 80.0,
        "nearest_hypothesis_ids": ["H001"],
        "required_observations_absent": [],
        "memory_risk_classification": "anonymous",
        "forward_confirmation_path": "Forward lane",
        "proposer": "codex:scout",
        "hostile_reviewer": "antigravity:critic",
        "dissents": [],
        "created_at": "2026-08-23 00:00:00",
    }
    failed_review = {
        "critic_role": "independent_model_critic:antigravity/gemini-3.7-flash-high",
        "approved": False,
        "score": 3.0,
        "critique": "A preserved hostile rejection",
        "dissents": [{
            "reviewer_role": "hostile",
            "objection": "Missing execution control",
            "severity": "fatal",
        }],
    }
    prior = {
        "dossier": dossier,
        "approved": False,
        "priority_score": 4.0,
        "reviews": [failed_review],
        "novelty": {},
        "all_dissents": failed_review["dissents"],
        "verdict": "REJECTED. Fatal objection.",
    }
    (dossier_dir / f"{dossier_id}.json").write_text(json.dumps(dossier))
    prior_path = adjudication_dir / f"{dossier_id}.json"
    prior_path.write_text(json.dumps(prior))
    monkeypatch.setattr(director_api, "DOSSIERS_DIR", dossier_dir)
    monkeypatch.setattr(director_api, "ADJUDICATIONS_DIR", adjudication_dir)
    monkeypatch.setattr(
        director_api, "route_council_call",
        lambda *args, **kwargs: pytest.fail("a waiver must not call a provider"),
    )

    result = director_api.attack({
        "dossier_id": dossier_id,
        "waive_failed_independent_attack": True,
        "waiver_reason": "Owner accepts the unresolved risk.",
    })
    waived = result["adjudication"]

    assert waived["approved"] is True
    assert waived["reviews"] == prior["reviews"]
    assert waived["all_dissents"] == prior["all_dissents"]
    assert waived["independent_attack_waiver"]["original_verdict"] == prior["verdict"]
    assert waived["independent_attack_waiver"]["reason"] == "Owner accepts the unresolved risk."
    assert json.loads(prior_path.read_text()) == json.loads(json.dumps(waived))


def test_attack_deterministic_only_skips_provider_dispatch(tmp_path, monkeypatch):
    dossier_dir = tmp_path / "dossiers"
    adjudication_dir = tmp_path / "adjudications"
    dossier_dir.mkdir()
    adjudication_dir.mkdir()
    dossier_id = "DOS_DET_ONLY"
    dossier = {
        "dossier_id": dossier_id,
        "hypothesis_id": "PROP_DET_ONLY",
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
        "nearest_hypothesis_ids": ["H001"],
        "required_observations_absent": [],
        "memory_risk_classification": "anonymous",
        "forward_confirmation_path": "Forward lane",
        "proposer": "codex:scout",
        "hostile_reviewer": "critic_economic",
        "dissents": [],
        "created_at": "2026-08-23 00:00:00",
    }
    (dossier_dir / f"{dossier_id}.json").write_text(json.dumps(dossier))
    monkeypatch.setattr(director_api, "DOSSIERS_DIR", dossier_dir)
    monkeypatch.setattr(director_api, "ADJUDICATIONS_DIR", adjudication_dir)
    monkeypatch.setattr(
        director_api, "route_council_call",
        lambda *args, **kwargs: pytest.fail("route_council_call must not run when deterministic_only=True"),
    )

    result = director_api.attack({"dossier_id": dossier_id, "deterministic_only": True})
    assert result["adjudication"]["approved"] is False
    assert result["adjudication"]["deterministic_only"] is True
    assert result["adjudication"]["independent_review_provider"] == ""
    assert "DIAGNOSTIC ONLY" in result["adjudication"]["verdict"]
    assert (adjudication_dir / f"{dossier_id}.json").exists()
