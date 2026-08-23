"""Execute frozen research-director contracts through the existing harness."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..alpha_eval.guards import assert_no_forward_labels
from ..contracts import LifecycleState
from ..contracts.compiler import (
    EXECUTIONS_DIR,
    _atomic_json,
    contract_to_spec,
    load_contract,
    load_qualification,
    save_contract,
)
from ..persistence import store
from ..research_data import frame
from . import forward, job
from .runner import run_exploration


class ContractExecutionError(RuntimeError):
    pass


def _claim_execution(contract_id: str) -> Path:
    """Create the one-shot execution record without a check/write race."""
    EXECUTIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = EXECUTIONS_DIR / f"{contract_id}.json"
    payload = {
        "contract_id": contract_id,
        "status": "running",
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        prior = json.loads(path.read_text())
        raise ContractExecutionError(
            f"contract {contract_id} already has execution status "
            f"{prior.get('status', 'unknown')!r}; compile a new contract rather "
            "than reading the same outcomes twice") from exc
    with os.fdopen(fd, "w") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return path


def execute_contract(path_or_id: str | Path,
                     enroll_forward: bool = False) -> tuple[dict[str, Any], Path]:
    contract, lifecycle = load_contract(path_or_id)
    existing_execution = EXECUTIONS_DIR / f"{contract.contract_id}.json"
    if existing_execution.exists():
        prior = json.loads(existing_execution.read_text())
        raise ContractExecutionError(
            f"contract {contract.contract_id} already has execution status "
            f"{prior.get('status', 'unknown')!r}; compile a new contract rather "
            "than reading the same outcomes twice")
    if lifecycle.current_state != LifecycleState.BATCH_FROZEN:
        raise ContractExecutionError(
            f"contract lifecycle is {lifecycle.current_state.value}, expected BATCH_FROZEN")
    qualification = load_qualification(contract.qualification_id)
    if qualification.qualification_hash != contract.qualification_hash:
        raise ContractExecutionError("qualification hash does not match contract")
    dossier = qualification.mechanism_dossier
    if dossier.dossier_hash != contract.dossier_hash:
        raise ContractExecutionError("dossier hash does not match contract")
    if qualification.signal_source_hash != contract.execution_code_or_prompt_hash:
        raise ContractExecutionError("qualified signal source hash does not match contract")
    batch = store.get_batch(contract.batch_id)
    if batch is None:
        raise ContractExecutionError(f"frozen batch {contract.batch_id!r} is missing")

    execution_path = _claim_execution(contract.contract_id)
    try:
        spec = contract_to_spec(contract)
        panel = frame.load_daily_panel(
            version=contract.dataset_version,
            partition=contract.partition,
            asof_open=True,
            include_context=True,
        )
        assert_no_forward_labels(panel, context="contract execution input")
        with tempfile.TemporaryDirectory(prefix="brickbreak_execute_") as tmp:
            source_path = Path(tmp) / "signal.py"
            source_path.write_text(qualification.signal_source)
            compute = job.load_signal_fn(source_path)
            signal = compute(panel.copy())
        if not isinstance(signal, pd.Series) or not signal.index.equals(panel.index):
            raise ContractExecutionError(
                "frozen signal no longer returns an aligned pandas Series")
        panel[contract.signal_name] = signal
        assert_no_forward_labels(panel, context="outcome-blind contract output")

        lifecycle.transition(
            LifecycleState.OUTCOME_BLIND_EXECUTED,
            actor="contract_runner",
            input_hashes=(contract.contract_hash, contract.execution_code_or_prompt_hash),
            reason="Frozen signal computed before the evaluation vault constructed outcomes",
        )
        save_contract(contract, lifecycle)

        result = run_exploration(
            spec,
            lambda frame_without_outcomes: panel[contract.signal_name].copy(),
            save_results=True,
            provider_used=qualification.provider,
            model_used=qualification.model,
            batch_id=batch.batch_id,
            batch_hash=batch.batch_hash,
            panel=panel.drop(columns=[contract.signal_name]),
            exposure_source_id=contract.contract_id,
        )
        lifecycle.transition(
            LifecycleState.REVEALED,
            actor="evaluation_vault",
            input_hashes=(result["manifest"]["hash"],),
            exposure_level=contract.exposure_level_incurred,
            reason="Registered outcomes revealed through the standard report",
        )
        lifecycle.transition(
            LifecycleState.EVIDENCE,
            actor="evidence_sink",
            input_hashes=(result["manifest"]["hash"],),
            exposure_level=contract.exposure_level_incurred,
            reason="Complete registered report persisted as evidence",
        )

        forward_registration = None
        if enroll_forward:
            if result["failure_class"] != "SUCCESS":
                raise ContractExecutionError(
                    "only a SUCCESS may be enrolled automatically in the forward lane")
            forward_registration = forward.register(
                signal_name=contract.signal_name,
                hypothesis_id=contract.hypothesis_id,
                source=qualification.signal_source,
                primary_horizon=spec.primary_horizon,
                dataset_version=contract.dataset_version,
                exploration_id=result["exploration_id"],
            )
            lifecycle.transition(
                LifecycleState.FORWARD,
                actor="forward_lane",
                input_hashes=(forward_registration.identity_hash,),
                exposure_level="E4",
                reason="Successful frozen identity enrolled for chronological accrual",
            )

        save_contract(contract, lifecycle)
        payload = {
            "contract_id": contract.contract_id,
            "contract_hash": contract.contract_hash,
            "qualification_hash": qualification.qualification_hash,
            "status": "succeeded",
            "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "result": result,
            "lifecycle": lifecycle.to_dict(),
            "forward_identity": (
                forward_registration.identity_hash if forward_registration else None),
        }
        _atomic_json(execution_path, payload)
        return payload, execution_path
    except Exception as exc:
        _atomic_json(execution_path, {
            "contract_id": contract.contract_id,
            "contract_hash": contract.contract_hash,
            "status": "failed",
            "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error": f"{type(exc).__name__}: {exc}",
            "lifecycle": lifecycle.to_dict(),
        })
        raise
