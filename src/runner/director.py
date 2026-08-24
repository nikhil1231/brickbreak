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
    CONTRACTS_DIR,
    DIRECTOR_DIR,
    EXECUTIONS_DIR,
    _atomic_json,
    contract_to_spec,
    load_contract,
    load_qualification,
    save_contract,
)
from ..persistence import store
from ..firewall import load_exposure_log
from ..research_data import frame
from . import forward, job
from . import burden as burden_mod
from .runner import run_exploration


class ContractExecutionError(RuntimeError):
    pass


WITHDRAWALS_DIR = DIRECTOR_DIR / "withdrawals"


def withdraw_contract(contract_id: str, reason: str) -> Path:
    """Preserve a frozen contract while permanently refusing its execution."""
    if not contract_id.strip() or not reason.strip():
        raise ValueError("contract_id and withdrawal reason are required")
    WITHDRAWALS_DIR.mkdir(parents=True, exist_ok=True)
    path = WITHDRAWALS_DIR / f"{contract_id}.json"
    if path.exists():
        prior = json.loads(path.read_text())
        if prior.get("reason") != reason:
            raise ContractExecutionError(
                f"contract {contract_id} already has a different withdrawal record")
        return path
    _atomic_json(path, {
        "contract_id": contract_id,
        "status": "withdrawn_unopened",
        "reason": reason,
        "withdrawn_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    return path


def _claim_execution(contract_id: str) -> Path:
    """Create the one-shot execution record without a check/write race."""
    EXECUTIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = EXECUTIONS_DIR / f"{contract_id}.json"
    import fcntl
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        if path.exists():
            prior = json.loads(path.read_text())
            if prior.get("status") != "failed_pre_exposure":
                raise ContractExecutionError(
                    f"contract {contract_id} already has execution status "
                    f"{prior.get('status', 'unknown')!r}; outcomes may already "
                    "have been accessed")
            path.unlink()
        payload = {
            "contract_id": contract_id,
            "status": "running",
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    return path


def _contract_has_exposure(contract_id: str) -> bool:
    return any(entry.source_id == contract_id and not entry.is_void
               for entry in load_exposure_log())


def _finalize_batch_if_complete(batch_id: str) -> dict[str, Any] | None:
    """Apply frozen batch correction before any positive status is promoted."""
    batch = store.get_batch(batch_id)
    if batch is None:
        raise ContractExecutionError(f"batch {batch_id!r} is missing")
    contract_ids = []
    for path in CONTRACTS_DIR.glob("*.json"):
        raw = json.loads(path.read_text())
        contract = raw.get("contract", {})
        if contract.get("batch_id") == batch_id:
            contract_ids.append(str(contract["contract_id"]))
    if len(contract_ids) != len(batch.specs):
        return None
    for contract_id in contract_ids:
        path = EXECUTIONS_DIR / f"{contract_id}.json"
        if not path.exists() or json.loads(path.read_text()).get("status") != "succeeded":
            return None

    correction = burden_mod.assess_batch(batch_id)
    for row in correction["results"]:
        exploration_id = row.get("exploration_id")
        exploration = store.get_exploration(exploration_id) if exploration_id else None
        if exploration is None or exploration.failure_class != "SUCCESS":
            continue
        hypothesis = store.get_hypothesis(str(row["hypothesis_id"]))
        if hypothesis is None:
            continue
        hypothesis.status = (
            "promising" if row.get("survives_fdr") and row.get("clears_batch_sidak")
            else "inconclusive"
        )
        store.save_hypothesis(hypothesis)
    batch.status = "completed"
    store.save_batch(batch)
    return correction


def execute_contract(path_or_id: str | Path,
                     enroll_forward: bool = False) -> tuple[dict[str, Any], Path]:
    contract, lifecycle = load_contract(path_or_id)
    withdrawal = WITHDRAWALS_DIR / f"{contract.contract_id}.json"
    if withdrawal.exists():
        record = json.loads(withdrawal.read_text())
        raise ContractExecutionError(
            f"contract {contract.contract_id} was withdrawn unopened: "
            f"{record.get('reason', 'no reason recorded')}")
    prior_execution = EXECUTIONS_DIR / f"{contract.contract_id}.json"
    if prior_execution.exists():
        prior_status = json.loads(prior_execution.read_text()).get("status")
        if prior_status != "failed_pre_exposure":
            raise ContractExecutionError(
                f"contract {contract.contract_id} already has execution status "
                f"{prior_status!r}; outcomes may already have been accessed")
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
    if contract.contract_version >= 3:
        if qualification.baseline_source_hash != contract.baseline_source_hash:
            raise ContractExecutionError(
                "qualified baseline source hash does not match contract")
    if contract.contract_version >= 4:
        if qualification.eligibility_source_hash != contract.eligibility_source_hash:
            raise ContractExecutionError(
                "qualified eligibility source hash does not match contract")
    batch = store.get_batch(contract.batch_id)
    if batch is None:
        raise ContractExecutionError(f"frozen batch {contract.batch_id!r} is missing")

    execution_path: Path | None = None
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
            baseline = None
            if contract.contract_version >= 3:
                baseline_path = Path(tmp) / "baseline.py"
                baseline_path.write_text(qualification.baseline_source)
                compute_baseline = job.load_signal_fn(baseline_path)
                baseline = compute_baseline(panel.copy())
            eligibility = None
            if contract.contract_version >= 4:
                eligibility_path = Path(tmp) / "eligibility.py"
                eligibility_path.write_text(qualification.eligibility_source)
                compute_eligibility = job.load_signal_fn(eligibility_path)
                eligibility = compute_eligibility(panel.copy())
        if not isinstance(signal, pd.Series) or not signal.index.equals(panel.index):
            raise ContractExecutionError(
                "frozen signal no longer returns an aligned pandas Series")
        if contract.contract_version >= 3 and (
                not isinstance(baseline, pd.Series)
                or not baseline.index.equals(panel.index)):
            raise ContractExecutionError(
                "frozen baseline no longer returns an aligned pandas Series")
        if contract.contract_version >= 4 and (
                not isinstance(eligibility, pd.Series)
                or not eligibility.index.equals(panel.index)
                or not pd.api.types.is_bool_dtype(eligibility)
                or eligibility.isna().any()):
            raise ContractExecutionError(
                "frozen eligibility no longer returns an aligned boolean Series")
        if contract.contract_version >= 4:
            eligible = eligibility.astype(bool)
            if not baseline.notna().equals(eligible):
                raise ContractExecutionError(
                    "frozen baseline population differs from frozen eligibility")
            if contract.signal_kind == "selector":
                if (signal.notna() & ~eligible).any():
                    raise ContractExecutionError(
                        "frozen selector contains cases outside eligibility")
            elif not signal.notna().equals(eligible):
                raise ContractExecutionError(
                    "frozen dense signal population differs from eligibility")
        panel[contract.signal_name] = signal
        if contract.contract_version >= 3:
            panel[contract.baseline_name] = baseline
        if contract.contract_version >= 4:
            panel[contract.eligibility_name] = eligibility
        assert_no_forward_labels(panel, context="outcome-blind contract output")

        # Only now claim the one-shot execution. Any failure above is entirely
        # outcome-free and may be retried without manufacturing a new contract.
        execution_path = _claim_execution(contract.contract_id)

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
            defer_batch_promotion=True,
        )
        lifecycle.transition(
            LifecycleState.OUTCOME_BLIND_EXECUTED,
            actor="contract_runner",
            input_hashes=(contract.contract_hash, contract.execution_code_or_prompt_hash),
            reason="Frozen signal computed before the evaluation vault constructed outcomes",
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
        forward_note = None
        if enroll_forward:
            if result["failure_class"] != "SUCCESS":
                forward_note = "not enrolled: registered result was not SUCCESS"
            else:
                try:
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
                except Exception as forward_exc:
                    # Forward registration is downstream of a valid persisted
                    # result. It must never rewrite that result as a failed run.
                    forward_note = (
                        f"forward enrollment failed: {type(forward_exc).__name__}: "
                        f"{forward_exc}")

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
            "forward_note": forward_note,
        }
        _atomic_json(execution_path, payload)
        try:
            correction = _finalize_batch_if_complete(batch.batch_id)
            payload["batch_correction"] = correction
            payload["batch_note"] = (
                "batch complete; positive statuses reflect frozen correction"
                if correction else "batch incomplete; no positive status promoted")
        except Exception as batch_exc:
            payload["batch_correction"] = None
            payload["batch_note"] = (
                f"batch finalization pending: {type(batch_exc).__name__}: {batch_exc}")
        _atomic_json(execution_path, payload)
        return payload, execution_path
    except Exception as exc:
        if execution_path is not None:
            exposed = _contract_has_exposure(contract.contract_id)
            _atomic_json(execution_path, {
                "contract_id": contract.contract_id,
                "contract_hash": contract.contract_hash,
                "status": "failed_exposed" if exposed else "failed_pre_exposure",
                "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": f"{type(exc).__name__}: {exc}",
                "lifecycle": lifecycle.to_dict(),
            })
        raise
