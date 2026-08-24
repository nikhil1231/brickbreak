"""Compile a passed outcome-free qualification into an executable contract."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core import config
from ..persistence import BatchManifest, store
from ..runner.preregistration import compute_batch_hash
from ..runner.spec import ExperimentSpec, validate_pass_criterion
from .experiment_contract import ExperimentContract
from .lifecycle import LifecycleState, LifecycleTracker
from .qualification import QualificationArtifact


DIRECTOR_DIR = config.METADATA_DIR / "research_store" / "director"
QUALIFICATIONS_DIR = DIRECTOR_DIR / "qualifications"
CONTRACTS_DIR = DIRECTOR_DIR / "contracts"
EXECUTIONS_DIR = DIRECTOR_DIR / "executions"


def _atomic_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, indent=2, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return path


def _claim_qualification(qualification_id: str,
                         contract_id: str) -> Path:
    """Atomically prevent two contracts from wrapping the same frozen signal."""
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    for path in CONTRACTS_DIR.glob("*.json"):
        try:
            raw = json.loads(path.read_text())
            if not isinstance(raw, dict):
                raise ValueError(f"contract file {path} is not a JSON object")
            if raw.get("contract", {}).get("qualification_id") == qualification_id:
                raise ValueError(
                    f"qualification {qualification_id} already has a frozen contract")
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            raise ValueError(
                f"cannot verify prior contracts while {path} is unreadable") from exc

    claim = CONTRACTS_DIR / f".{qualification_id}.claim"
    try:
        fd = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError(
            f"qualification {qualification_id} already has a frozen contract") from exc
    with os.fdopen(fd, "w") as handle:
        json.dump({"qualification_id": qualification_id,
                   "contract_id": contract_id}, handle)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return claim


def save_qualification(artifact: QualificationArtifact,
                       path: Path | None = None) -> Path:
    target = path or QUALIFICATIONS_DIR / f"{artifact.qualification_id}.json"
    return _atomic_json(target, artifact.to_dict())


def load_qualification(path_or_id: str | Path) -> QualificationArtifact:
    candidate = Path(path_or_id)
    path = candidate if candidate.exists() else QUALIFICATIONS_DIR / f"{candidate}.json"
    if not path.exists():
        raise FileNotFoundError(f"qualification artifact {path_or_id!r} not found")
    return QualificationArtifact.from_dict(json.loads(path.read_text()))


def save_contract(contract: ExperimentContract,
                  lifecycle: LifecycleTracker,
                  path: Path | None = None) -> Path:
    target = path or CONTRACTS_DIR / f"{contract.contract_id}.json"
    return _atomic_json(target, {
        "contract": contract.to_dict(),
        "lifecycle": lifecycle.to_dict(),
    })


def load_contract(path_or_id: str | Path) -> tuple[ExperimentContract, LifecycleTracker]:
    candidate = Path(path_or_id)
    path = candidate if candidate.exists() else CONTRACTS_DIR / f"{candidate}.json"
    if not path.exists():
        raise FileNotFoundError(f"experiment contract {path_or_id!r} not found")
    raw = json.loads(path.read_text())
    contract = ExperimentContract.from_dict(raw["contract"])
    lifecycle = LifecycleTracker.from_dict(raw["lifecycle"])
    if lifecycle.entity_id != contract.hypothesis_id:
        raise ValueError("contract lifecycle belongs to another hypothesis")
    return contract, lifecycle


def _build_contract(
    qualification: QualificationArtifact,
    reviewer: str,
    batch_id: str,
    contract_id: str,
    batch_size: int,
    cost_round_trip_bps: float,
    capacity_limit_inr: float,
    min_significance_t: float,
) -> tuple[ExperimentContract, LifecycleTracker]:
    if not qualification.approved:
        raise ValueError(
            f"qualification {qualification.qualification_id} was rejected: "
            f"{'; '.join(qualification.rejection_reasons)}")
    if qualification.artifact_version < 3:
        raise ValueError(
            "legacy qualification does not freeze exact eligibility; re-qualify "
            "it before compiling")
    dossier = qualification.mechanism_dossier
    proposer = qualification.provider or dossier.proposer
    if not reviewer.strip() or reviewer == proposer:
        raise ValueError("contract reviewer must be non-empty and independent of proposer")

    pass_criterion = {
        "min_mean_ic": 0.01,
        "min_spread_bps": max(10.0, dossier.min_effect_bps),
        "min_monotonicity": 0.50,
    }
    validate_pass_criterion(pass_criterion)

    contract = ExperimentContract(
        contract_id=contract_id,
        dossier_id=dossier.dossier_id,
        dossier_hash=dossier.dossier_hash,
        hypothesis_id=dossier.hypothesis_id,
        family=dossier.family,
        batch_id=batch_id,
        adapter_type="signal",
        dataset_version=qualification.dataset_version,
        split_version=qualification.dataset_version,
        partition="train",
        population_definition=dossier.population,
        estimand=(f"Cross-sectional {qualification.primary_horizon}-session "
                  f"{qualification.entry_price}-entry "
                  f"{'market-excess' if qualification.outcome_kind == 'market_excess' else 'raw'} "
                  "forward return, net of the registered cost hurdle"),
        horizons=qualification.horizons,
        cost_round_trip_bps=cost_round_trip_bps,
        capacity_limit_inr=capacity_limit_inr,
        baselines=(dossier.strongest_baseline, "take_all", "walk_forward_rank_model"),
        min_magnitude_bps=max(cost_round_trip_bps, dossier.min_effect_bps),
        min_significance_t=min_significance_t,
        min_independent_blocks=8,
        exposure_level_incurred="E2",
        requested_outcome_columns=tuple(
            f"{'excess_ret' if qualification.outcome_kind == 'market_excess' else 'fwd_ret'}_{h}d_pct"
            for h in qualification.horizons),
        memory_risk_class=dossier.memory_risk_classification,
        forward_confirmation_path=dossier.forward_confirmation_path,
        execution_code_or_prompt_hash=qualification.signal_source_hash,
        proposer=proposer,
        reviewer=reviewer,
        abort_conditions=(
            "signal source hash differs from the qualified source",
            "qualification or dossier hash fails verification",
            "outcome exposure reservation is refused",
            "effective independent blocks fall below the frozen floor",
        ),
        contract_version=4,
        qualification_id=qualification.qualification_id,
        qualification_hash=qualification.qualification_hash,
        signal_name=qualification.signal_name,
        signal_definition=qualification.question,
        pass_criterion=pass_criterion,
        falsification_condition=(
            f"mean IC <= 0 or net Q5-Q1 spread < {dossier.min_effect_bps:.1f} bps"),
        parameter_neighbourhood=("exact authored signal; no post-reveal tuning",),
        search_wide_null=(
            f"maximum statistic and FDR across this frozen {batch_size}-member batch"),
        permitted_result_readings=(
            "registered standard report in full",
            "registered failure class and preregistered aggregate metrics",
            "no post-hoc cells, date slices, or parameter variants",
        ),
        entry_price=qualification.entry_price,
        outcome_kind=qualification.outcome_kind,
        signal_kind=qualification.signal_kind,
        baseline_name=qualification.baseline_name,
        baseline_source_hash=qualification.baseline_source_hash,
        dissent_resolutions=qualification.dissent_resolutions,
        eligibility_name=qualification.eligibility_name,
        eligibility_source_hash=qualification.eligibility_source_hash,
    )

    lifecycle = LifecycleTracker.from_dict(qualification.lifecycle)
    lifecycle.transition(
        LifecycleState.EXPERIMENT_CONTRACTED,
        actor=reviewer,
        input_hashes=(qualification.qualification_hash, contract.contract_hash),
        reason="Independent reviewer froze the version-4 experiment contract",
    )
    lifecycle.transition(
        LifecycleState.BATCH_FROZEN,
        actor="contract_compiler",
        input_hashes=(contract.contract_hash,),
        reason="Contract enrolled in its immutable multiplicity batch",
    )

    return contract, lifecycle


def compile_batch(
    qualifications: list[QualificationArtifact],
    reviewer: str,
    cost_round_trip_bps: float = 40.0,
    capacity_limit_inr: float = 1_000_000.0,
    min_significance_t: float = 2.5,
) -> tuple[list[ExperimentContract], list[LifecycleTracker], BatchManifest]:
    """Atomically freeze one or more qualifications into one real batch."""
    if not qualifications:
        raise ValueError("cannot compile an empty qualification batch")
    ids = [item.qualification_id for item in qualifications]
    if len(ids) != len(set(ids)):
        raise ValueError("qualification batch contains duplicate IDs")
    datasets = {item.dataset_version for item in qualifications}
    partitions = {item.partition for item in qualifications}
    if len(datasets) != 1 or partitions != {"train"}:
        raise ValueError("all batch members must use the same train dataset version")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    batch_id = f"BATCH_{stamp}"
    contracts: list[ExperimentContract] = []
    lifecycles: list[LifecycleTracker] = []
    for index, qualification in enumerate(qualifications, start=1):
        suffix = f"_{index:02d}" if len(qualifications) > 1 else ""
        contract, lifecycle = _build_contract(
            qualification, reviewer=reviewer, batch_id=batch_id,
            contract_id=f"EC_{stamp}{suffix}", batch_size=len(qualifications),
            cost_round_trip_bps=cost_round_trip_bps,
            capacity_limit_inr=capacity_limit_inr,
            min_significance_t=min_significance_t,
        )
        contracts.append(contract)
        lifecycles.append(lifecycle)

    specs = [contract_to_spec(contract).to_dict() for contract in contracts]
    batch = BatchManifest(
        batch_id=batch_id,
        partition="train",
        proposal_ids=ids,
        specs=specs,
        batch_hash=compute_batch_hash(specs),
        status="preregistered",
    )
    claims: list[Path] = []
    saved_contracts: list[Path] = []
    try:
        for qualification, contract in zip(qualifications, contracts):
            save_qualification(qualification)
            claims.append(_claim_qualification(
                qualification.qualification_id, contract.contract_id))
        store.save_batch(batch)
        for contract, lifecycle in zip(contracts, lifecycles):
            saved_contracts.append(save_contract(contract, lifecycle))
    except Exception:
        for path in saved_contracts:
            path.unlink(missing_ok=True)
        (store.BATCHES_DIR / f"{batch.batch_id}.json").unlink(missing_ok=True)
        for claim in claims:
            claim.unlink(missing_ok=True)
        raise
    return contracts, lifecycles, batch


def compile_qualification(
    qualification: QualificationArtifact,
    reviewer: str,
    cost_round_trip_bps: float = 40.0,
    capacity_limit_inr: float = 1_000_000.0,
    min_significance_t: float = 2.5,
) -> tuple[ExperimentContract, LifecycleTracker, BatchManifest]:
    """Compatibility wrapper for a one-member frozen batch."""
    contracts, lifecycles, batch = compile_batch(
        [qualification], reviewer=reviewer,
        cost_round_trip_bps=cost_round_trip_bps,
        capacity_limit_inr=capacity_limit_inr,
        min_significance_t=min_significance_t,
    )
    return contracts[0], lifecycles[0], batch


def contract_to_spec(contract: ExperimentContract) -> ExperimentSpec:
    if contract.contract_version < 2:
        raise ValueError("legacy pilot contracts are descriptive and not executable")
    return ExperimentSpec(
        hypothesis_id=contract.hypothesis_id,
        question=contract.signal_definition,
        signal_name=contract.signal_name,
        dataset_version=contract.dataset_version,
        partition=contract.partition,
        role="exploratory" if contract.exposure_level_incurred == "E2" else "confirmatory",
        horizons=contract.horizons,
        primary_horizon=contract.horizons[0],
        pass_criterion=dict(contract.pass_criterion),
        falsification_condition=contract.falsification_condition,
        backtest_holding=contract.horizons[0],
        entry_price=contract.entry_price,
        outcome_kind=contract.outcome_kind,
        signal_kind=contract.signal_kind,
        baseline_name=contract.baseline_name,
        eligibility_name=contract.eligibility_name,
        batch_id=contract.batch_id,
        min_significance_t=contract.min_significance_t,
        cost_round_trip_bps=contract.cost_round_trip_bps,
    )
