"""The real dossier -> qualify -> compile -> one-shot execution path."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.contracts import MechanismDossier
from src.contracts import compiler
from src.council import adjudicate_dossier
from src.runner import director
from src.runner import qualification as qualification_mod
from src.persistence import BatchManifest, Evidence, Exploration, Hypothesis, store


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
        min_effect_bps=500.0, nearest_hypothesis_ids=("H001",),
        required_observations_absent=(),
        memory_risk_classification="not_applicable_signal",
        forward_confirmation_path="Accrue chronological forward sessions",
        proposer="claude:scout_market_structure",
        hostile_reviewer="codex:critic",
        required_feature_names=("deliv_pct",),
        data_adapter="daily_panel_asof_open",
        entry_price="open",
        outcome_kind="market_excess",
        signal_kind="dense",
    )


def _panel() -> pd.DataFrame:
    dates = np.repeat(pd.bdate_range("2022-01-03", periods=80), 60)
    symbols = np.tile([f"S{i:03d}" for i in range(60)], 80)
    return pd.DataFrame({
        "date": dates,
        "symbol": symbols,
        "deliv_pct": np.tile(np.arange(60, dtype=float), 80),
    })


def test_provisional_dossier_promotion_is_idempotent_under_retries(research_store):
    dossier = _dossier()
    with ThreadPoolExecutor(max_workers=6) as pool:
        promoted = list(pool.map(
            lambda _: qualification_mod._promote_dossier(dossier), range(6)))
    assert {item.hypothesis_id for item in promoted} == {"H001"}
    exact = [h for h in store.list_hypotheses()
             if h.statement == dossier.claim and h.family == dossier.family]
    assert len(exact) == 1


def test_qualification_refuses_an_unimplemented_intraday_adapter(
        research_store):
    dossier = replace(
        _dossier(), data_adapter="intraday_panel", entry_price="intraday")
    adjudication = adjudicate_dossier(dossier).to_dict()
    with pytest.raises(qualification_mod.QualificationError,
                       match="not executable by the daily signal director"):
        qualification_mod.qualify_adjudication(
            adjudication, signal_name="intraday_signal")


def test_data_ready_is_checked_against_the_actual_adapter_frame(
        monkeypatch, research_store):
    dossier = replace(_dossier(), required_feature_names=("missing_pit_feature",))
    adjudication = adjudicate_dossier(dossier).to_dict()
    monkeypatch.setattr(
        qualification_mod.frame, "load_daily_panel", lambda **kwargs: _panel())
    with pytest.raises(qualification_mod.QualificationError,
                       match="missing required feature"):
        qualification_mod.qualify_adjudication(
            adjudication, signal_name="missing_feature_signal")


def test_execution_claim_retries_only_pre_exposure_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(director, "EXECUTIONS_DIR", tmp_path / "executions")
    path = director._claim_execution("EC_RETRY")
    record = json.loads(path.read_text())
    record["status"] = "failed_pre_exposure"
    path.write_text(json.dumps(record))
    assert director._claim_execution("EC_RETRY") == path

    record = json.loads(path.read_text())
    record["status"] = "failed_exposed"
    path.write_text(json.dumps(record))
    with pytest.raises(director.ContractExecutionError, match="outcomes may already"):
        director._claim_execution("EC_RETRY")


def test_compile_freezes_multiple_qualifications_in_one_batch(
        tmp_path, monkeypatch, research_store):
    director_root = tmp_path / "director"
    monkeypatch.setattr(compiler, "QUALIFICATIONS_DIR", director_root / "qualifications")
    monkeypatch.setattr(compiler, "CONTRACTS_DIR", director_root / "contracts")
    monkeypatch.setattr(
        qualification_mod.frame, "load_daily_panel", lambda **kwargs: _panel())

    baseline = (
        "import pandas as pd\n\n"
        "def compute(df: pd.DataFrame) -> pd.Series:\n"
        "    return -df['deliv_pct']\n"
    )
    eligibility = (
        "import pandas as pd\n\n"
        "def compute(df: pd.DataFrame) -> pd.Series:\n"
        "    return pd.Series(True, index=df.index, dtype=bool)\n"
    )
    artifacts = []
    for index in (1, 2):
        dossier = replace(
            _dossier(), dossier_id=f"DOS_BATCH_{index}",
            hypothesis_id=f"PROP_BATCH_{index}",
            claim=f"Distinct point-in-time batch mechanism {index} predicts returns",
        )
        artifact, _ = qualification_mod.qualify_adjudication(
            {"approved": True, "dossier": dossier.to_dict()},
            signal_name=f"batch_signal_{index}",
            signal_source=(
                "import pandas as pd\n\n"
                "def compute(df: pd.DataFrame) -> pd.Series:\n"
                f"    return df['deliv_pct'] * {index}.0\n"
            ),
            baseline_source=baseline,
            baseline_name=f"batch_baseline_{index}",
            eligibility_source=eligibility,
            eligibility_name=f"batch_eligible_{index}",
            signal_kind="dense",
            temp_dir=tmp_path / f"signal_load_{index}",
        )
        assert artifact.approved
        artifacts.append(artifact)

    contracts, _, batch = compiler.compile_batch(
        artifacts, reviewer="independent_reviewer")
    assert len(contracts) == 2
    assert len(batch.specs) == 2
    assert {contract.batch_id for contract in contracts} == {batch.batch_id}
    assert all(contract.contract_version == 4 for contract in contracts)
    assert all("2-member batch" in contract.search_wide_null
               for contract in contracts)
    assert all(spec["batch_id"] == batch.batch_id for spec in batch.specs)


def test_positive_status_waits_for_complete_batch_correction(
        tmp_path, monkeypatch, research_store):
    contracts_dir = tmp_path / "contracts"
    executions_dir = tmp_path / "executions"
    contracts_dir.mkdir()
    executions_dir.mkdir()
    monkeypatch.setattr(director, "CONTRACTS_DIR", contracts_dir)
    monkeypatch.setattr(director, "EXECUTIONS_DIR", executions_dir)

    batch_id = "BATCH_STATUS_GATE"
    specs = [
        {"hypothesis_id": "H001", "signal_name": "strong", "partition": "train",
         "batch_id": batch_id},
        {"hypothesis_id": "H002", "signal_name": "weak", "partition": "train",
         "batch_id": batch_id},
    ]
    store.save_batch(BatchManifest(
        batch_id=batch_id, partition="train", proposal_ids=["Q1", "Q2"],
        specs=specs, batch_hash="frozen-batch-hash"))
    for index, (signal, t_stat) in enumerate((("strong", 4.0), ("weak", 0.0)), 1):
        hypothesis_id = f"H{index:03d}"
        store.save_hypothesis(Hypothesis(
            id=hypothesis_id, title=signal, statement=signal,
            rationale="test", status="proposed"))
        exploration_id = f"EXP_BATCH_{index}"
        store.save_exploration(Exploration(
            id=exploration_id, hypothesis_id=hypothesis_id, spec=specs[index - 1],
            verdict="registered", failure_class="SUCCESS"))
        store.add_evidence(Evidence(
            id=f"EV_BATCH_{index}", hypothesis_id=hypothesis_id,
            signal_id=signal, exploration_id=exploration_id, role="exploratory",
            dataset_version="v1", partition="train", metrics={"t_stat": t_stat},
            verdict_statement="registered"))
        (contracts_dir / f"EC_{index}.json").write_text(json.dumps({
            "contract": {"contract_id": f"EC_{index}", "batch_id": batch_id}}))

    (executions_dir / "EC_1.json").write_text(json.dumps({"status": "succeeded"}))
    assert director._finalize_batch_if_complete(batch_id) is None
    assert store.get_hypothesis("H001").status == "proposed"

    (executions_dir / "EC_2.json").write_text(json.dumps({"status": "succeeded"}))
    correction = director._finalize_batch_if_complete(batch_id)
    assert correction is not None
    assert store.get_hypothesis("H001").status == "promising"
    assert store.get_hypothesis("H002").status == "inconclusive"
    assert store.get_batch(batch_id).status == "completed"


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
    dissent_resolutions = tuple(
        f"Implemented pre-outcome safeguard for: {item['objection']}"
        for item in adjudication["all_dissents"]
        if item["severity"] in ("fatal", "material")
    )
    artifact, artifact_path = qualification_mod.qualify_adjudication(
        adjudication,
        signal_name="workflow_signal",
        signal_source=(
            "import pandas as pd\n\n"
            "def compute(df: pd.DataFrame) -> pd.Series:\n"
            "    return df['deliv_pct']\n"
        ),
        baseline_source=(
            "import pandas as pd\n\n"
            "def compute(df: pd.DataFrame) -> pd.Series:\n"
            "    return -df['deliv_pct']\n"
        ),
        baseline_name="reverse_ret_20d",
        eligibility_source=(
            "import pandas as pd\n\n"
            "def compute(df: pd.DataFrame) -> pd.Series:\n"
            "    return pd.Series(True, index=df.index, dtype=bool)\n"
        ),
        eligibility_name="workflow_eligible",
        signal_kind="dense",
        dissent_resolutions=dissent_resolutions,
        output_path=director_root / "qualification_export.json",
        temp_dir=tmp_path / "signal_load",
    )
    assert artifact.approved
    assert artifact.mechanism_dossier.hypothesis_id.startswith("H")
    assert artifact_path.exists()

    contract, lifecycle, batch = compiler.compile_qualification(
        artifact, reviewer="independent_reviewer")
    contract_path = compiler.save_contract(contract, lifecycle)
    assert contract.contract_version == 4
    assert batch.batch_hash

    with pytest.raises(ValueError, match="already has a frozen contract"):
        compiler.compile_qualification(
            artifact, reviewer="another_independent_reviewer")

    monkeypatch.setattr(
        director.frame, "load_daily_panel", lambda **kwargs: panel.copy())
    calls = []
    attempts = {"count": 0}

    def fake_run(spec, compute, **kwargs):
        frame_seen = kwargs["panel"]
        assert not any(str(c).startswith("fwd_ret_") for c in frame_seen.columns)
        score = compute(frame_seen)
        assert score.equals(frame_seen["deliv_pct"])
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("transient failure before outcome reservation")
        calls.append(kwargs["exposure_source_id"])
        return {
            "exploration_id": "EXP_WORKFLOW",
            "failure_class": "NO_SIGNAL",
            "interpretation": "Registered null",
            "manifest": {"hash": "manifest123"},
        }

    monkeypatch.setattr(director, "run_exploration", fake_run)
    with pytest.raises(RuntimeError, match="transient failure"):
        director.execute_contract(contract_path)
    failed = json.loads(
        (director_root / "executions" / f"{contract.contract_id}.json").read_text())
    assert failed["status"] == "failed_pre_exposure"

    payload, execution_path = director.execute_contract(contract_path)
    assert payload["status"] == "succeeded"
    assert calls == [contract.contract_id]
    assert json.loads(execution_path.read_text())["status"] == "succeeded"

    with pytest.raises(director.ContractExecutionError, match="already has execution"):
        director.execute_contract(contract_path)
