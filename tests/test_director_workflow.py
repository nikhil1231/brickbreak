"""The real dossier -> qualify -> compile -> one-shot execution path."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.contracts import MechanismDossier
from src.contracts import compiler
from src.council import adjudicate_dossier
from src.runner import director
from src.runner import qualification as qualification_mod


def _dossier() -> MechanismDossier:
    return MechanismDossier(
        dossier_id="DOS_WORKFLOW",
        hypothesis_id="PROP_WORKFLOW",
        family="workflow_test",
        claim="A persistent point-in-time cross-sectional fact predicts returns",
        population="Liquid NSE equities",
        expected_horizon_days=5,
        observable_facts=("Lagged predictor",),
        interpretation="Constrained rebalancing",
        causal_chain="Slow mandates spread execution across sessions",
        counterparty="Mandated rebalancers",
        counterparty_persistence_rationale="Mandates fix timing rather than price",
        competing_explanations=("Risk compensation", "Measurement noise"),
        strongest_baseline="Simple momentum sort",
        unique_predictions=("Effect rises with rebalance intensity",),
        natural_falsifiers=("No cross-sectional variation",),
        confounds=(), capacity_notes="Retail-scale liquid book",
        min_effect_bps=50.0, nearest_hypothesis_ids=(),
        required_observations_absent=(),
        memory_risk_classification="not_applicable_signal",
        forward_confirmation_path="Accrue chronological forward sessions",
        proposer="claude:scout_market_structure",
        hostile_reviewer="codex:critic",
    )


def _panel() -> pd.DataFrame:
    dates = np.repeat(pd.bdate_range("2022-01-03", periods=80), 60)
    symbols = np.tile([f"S{i:03d}" for i in range(60)], 80)
    return pd.DataFrame({
        "date": dates,
        "symbol": symbols,
        "lagged_predictor": np.tile(np.arange(60, dtype=float), 80),
    })


def test_reviewed_dossier_compiles_and_executes_exactly_once(
        tmp_path, monkeypatch, research_store):
    director_root = tmp_path / "director"
    monkeypatch.setattr(compiler, "QUALIFICATIONS_DIR", director_root / "qualifications")
    monkeypatch.setattr(compiler, "CONTRACTS_DIR", director_root / "contracts")
    monkeypatch.setattr(compiler, "EXECUTIONS_DIR", director_root / "executions")
    monkeypatch.setattr(director, "EXECUTIONS_DIR", director_root / "executions")

    panel = _panel()
    monkeypatch.setattr(
        qualification_mod.frame, "load_daily_panel", lambda **kwargs: panel.copy())
    adjudication = adjudicate_dossier(_dossier()).to_dict()
    artifact, artifact_path = qualification_mod.qualify_adjudication(
        adjudication,
        signal_name="workflow_signal",
        signal_source=(
            "import pandas as pd\n\n"
            "def compute(df: pd.DataFrame) -> pd.Series:\n"
            "    return df['lagged_predictor']\n"
        ),
        output_path=director_root / "qualification_export.json",
        temp_dir=tmp_path / "signal_load",
    )
    assert artifact.approved
    assert artifact.mechanism_dossier.hypothesis_id.startswith("H")
    assert artifact_path.exists()

    contract, lifecycle, batch = compiler.compile_qualification(
        artifact, reviewer="independent_reviewer")
    contract_path = compiler.save_contract(contract, lifecycle)
    assert contract.contract_version == 2
    assert batch.batch_hash

    with pytest.raises(ValueError, match="already has a frozen contract"):
        compiler.compile_qualification(
            artifact, reviewer="another_independent_reviewer")

    monkeypatch.setattr(
        director.frame, "load_daily_panel", lambda **kwargs: panel.copy())
    calls = []

    def fake_run(spec, compute, **kwargs):
        frame_seen = kwargs["panel"]
        assert not any(str(c).startswith("fwd_ret_") for c in frame_seen.columns)
        score = compute(frame_seen)
        assert score.equals(frame_seen["lagged_predictor"])
        calls.append(kwargs["exposure_source_id"])
        return {
            "exploration_id": "EXP_WORKFLOW",
            "failure_class": "NO_SIGNAL",
            "interpretation": "Registered null",
            "manifest": {"hash": "manifest123"},
        }

    monkeypatch.setattr(director, "run_exploration", fake_run)
    payload, execution_path = director.execute_contract(contract_path)
    assert payload["status"] == "succeeded"
    assert calls == [contract.contract_id]
    assert json.loads(execution_path.read_text())["status"] == "succeeded"

    with pytest.raises(director.ContractExecutionError, match="already has execution"):
        director.execute_contract(contract_path)
