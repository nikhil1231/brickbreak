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
        if self.min_magnitude_bps <= 0.0:
            raise ExperimentContractValidationError("min_magnitude_bps must be positive (PLAN §3.3)")
        if self.min_significance_t <= 0.0:
            raise ExperimentContractValidationError("min_significance_t must be positive (PLAN §3.3)")
        if self.min_independent_blocks < 4:
            raise ExperimentContractValidationError("min_independent_blocks must be >= 4")
        if self.exposure_level_incurred not in ("E0", "E1", "E2", "E3", "E4"):
            raise ExperimentContractValidationError("invalid exposure_level_incurred")
        if self.proposer == self.reviewer:
            raise ExperimentContractValidationError(
                "proposer and reviewer must be separate entities (PLAN §3.3)")

    @property
    def contract_hash(self) -> str:
        payload = json.dumps(
            {
                "contract_id": self.contract_id,
                "dossier_hash": self.dossier_hash,
                "hypothesis_id": self.hypothesis_id,
                "family": self.family,
                "batch_id": self.batch_id,
                "adapter_type": self.adapter_type,
                "dataset_version": self.dataset_version,
                "split_version": self.split_version,
                "partition": self.partition,
                "horizons": list(self.horizons),
                "min_magnitude_bps": self.min_magnitude_bps,
                "min_significance_t": self.min_significance_t,
                "execution_code_or_prompt_hash": self.execution_code_or_prompt_hash,
                "exposure_level_incurred": self.exposure_level_incurred,
            },
            sort_keys=True,
        )
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
        d.pop("contract_hash", None)
        for k in ("horizons", "baselines", "requested_outcome_columns", "abort_conditions"):
            if k in d and isinstance(d[k], (list, tuple)):
                d[k] = tuple(d[k])
        return cls(**d)
