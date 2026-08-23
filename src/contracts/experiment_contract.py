"""Experiment contract specification (PLAN.md §3.3 and Stage W).

Only a dossier with usable data may compile into an experiment contract.
It freezes all execution, estimand, baseline, and evaluation parameters before
any outcome-bearing partition is accessed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Sequence


class ExperimentContractValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ExperimentContract:
    contract_id: str
    dossier_id: str
    dossier_hash: str
    hypothesis_id: str
    family: str
    batch_id: str
    adapter_type: str  # "signal" or "replay"
    dataset_version: str
    split_version: str
    partition: str  # "train", "validation", "test", "forward"
    population_definition: str
    estimand: str
    horizons: tuple[int, ...]
    cost_round_trip_bps: float
    capacity_limit_inr: float
    baselines: tuple[str, ...]
    min_magnitude_bps: float
    min_significance_t: float
    min_independent_blocks: int
    exposure_level_incurred: str  # "E0", "E1", "E2", "E3", "E4"
    requested_outcome_columns: tuple[str, ...]
    memory_risk_class: str
    forward_confirmation_path: str
    execution_code_or_prompt_hash: str
    proposer: str
    reviewer: str
    abort_conditions: tuple[str, ...]
    created_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not self.contract_id.strip():
            raise ExperimentContractValidationError("contract_id cannot be empty")
        if not self.dossier_id.strip() or not self.dossier_hash.strip():
            raise ExperimentContractValidationError("dossier reference cannot be empty")
        if not self.hypothesis_id.strip():
            raise ExperimentContractValidationError("hypothesis_id cannot be empty")
        if self.adapter_type not in ("signal", "replay"):
            raise ExperimentContractValidationError("adapter_type must be 'signal' or 'replay'")
        if self.partition not in ("train", "validation", "test", "forward"):
            raise ExperimentContractValidationError("invalid partition")
        if not self.horizons:
            raise ExperimentContractValidationError("horizons cannot be empty")
        if any(h <= 0 for h in self.horizons):
            raise ExperimentContractValidationError("horizons must be positive")
        if self.cost_round_trip_bps < 0.0:
            raise ExperimentContractValidationError("cost_round_trip_bps cannot be negative")
        if self.capacity_limit_inr <= 0.0:
            raise ExperimentContractValidationError("capacity_limit_inr must be positive")
        if not self.baselines:
            raise ExperimentContractValidationError("baselines cannot be empty")
        if self.min_magnitude_bps <= 0.0:
            raise ExperimentContractValidationError("min_magnitude_bps must be positive (PLAN §3.3)")
        if self.min_significance_t <= 0.0:
            raise ExperimentContractValidationError("min_significance_t must be positive (PLAN §3.3)")
        if self.min_independent_blocks < 4:
            raise ExperimentContractValidationError("min_independent_blocks must be >= 4")
        if self.exposure_level_incurred not in ("E0", "E1", "E2", "E3", "E4"):
            raise ExperimentContractValidationError("invalid exposure_level_incurred")
        if self.exposure_level_incurred == "E2" and self.partition != "train":
            raise ExperimentContractValidationError("E2 experiments must use train")
        if self.exposure_level_incurred == "E3" and self.partition not in ("validation", "test"):
            raise ExperimentContractValidationError(
                "E3 experiments must use validation or test")
        if self.exposure_level_incurred == "E4" and self.partition != "forward":
            raise ExperimentContractValidationError("E4 experiments must use forward")
        if self.exposure_level_incurred != "E0" and not self.requested_outcome_columns:
            raise ExperimentContractValidationError(
                "outcome-bearing experiments must declare requested_outcome_columns")
        if not self.execution_code_or_prompt_hash.strip():
            raise ExperimentContractValidationError(
                "execution_code_or_prompt_hash cannot be empty")
        if self.proposer == self.reviewer:
            raise ExperimentContractValidationError(
                "proposer and reviewer must be separate entities (PLAN §3.3)")

    @property
    def contract_hash(self) -> str:
        semantic_fields = asdict(self)
        semantic_fields.pop("created_at", None)
        payload = json.dumps(semantic_fields, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["contract_hash"] = self.contract_hash
        data["horizons"] = list(self.horizons)
        data["baselines"] = list(self.baselines)
        data["requested_outcome_columns"] = list(self.requested_outcome_columns)
        data["abort_conditions"] = list(self.abort_conditions)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentContract:
        d = dict(data)
        expected_hash = d.pop("contract_hash", None)
        for k in ("horizons", "baselines", "requested_outcome_columns", "abort_conditions"):
            if k in d and isinstance(d[k], (list, tuple)):
                d[k] = tuple(d[k])
        contract = cls(**d)
        if expected_hash is not None and contract.contract_hash != expected_hash:
            raise ExperimentContractValidationError(
                f"contract_hash mismatch: stored {expected_hash}, "
                f"computed {contract.contract_hash}")
        return contract
