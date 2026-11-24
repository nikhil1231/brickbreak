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
from typing import Any


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
    # Version-2 execution identity.  Version 1 objects remain readable for the
    # archived pilot, while every newly compiled contract must freeze these.
    contract_version: int = 1
    qualification_id: str = ""
    qualification_hash: str = ""
    signal_name: str = ""
    signal_definition: str = ""
    pass_criterion: dict[str, float] = field(default_factory=dict)
    falsification_condition: str = ""
    parameter_neighbourhood: tuple[str, ...] = ()
    search_wide_null: str = ""
    permitted_result_readings: tuple[str, ...] = ()
    # Version-3 execution semantics. Older frozen contracts remain readable,
    # but only v3 can express the entry clock and selector/baseline evaluation
    # needed by the research-director path.
    entry_price: str = "close"
    outcome_kind: str = "raw"
    signal_kind: str = "dense"
    baseline_name: str = ""
    baseline_source_hash: str = ""
    dissent_resolutions: tuple[str, ...] = ()
    # Version-4 freezes the exact eligible population independently from the
    # sparse selector and the baseline score.
    eligibility_name: str = ""
    eligibility_source_hash: str = ""
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
        if self.contract_version not in (1, 2, 3, 4):
            raise ExperimentContractValidationError("unsupported contract_version")
        if self.contract_version >= 2:
            for name, value in (
                ("qualification_id", self.qualification_id),
                ("qualification_hash", self.qualification_hash),
                ("signal_name", self.signal_name),
                ("signal_definition", self.signal_definition),
                ("falsification_condition", self.falsification_condition),
                ("search_wide_null", self.search_wide_null),
            ):
                if not str(value).strip():
                    raise ExperimentContractValidationError(
                        f"version-2 contract requires {name}")
            if not self.pass_criterion:
                raise ExperimentContractValidationError(
                    "version-2 contract requires a pass_criterion")
            if not self.permitted_result_readings:
                raise ExperimentContractValidationError(
                    "version-2 contract requires permitted_result_readings")
        if self.contract_version >= 3:
            if self.entry_price not in ("open", "close"):
                raise ExperimentContractValidationError(
                    "version-3 contract entry_price must be open or close")
            if self.outcome_kind not in ("raw", "market_excess"):
                raise ExperimentContractValidationError(
                    "version-3 contract outcome_kind must be raw or market_excess")
            if self.signal_kind not in ("dense", "selector"):
                raise ExperimentContractValidationError(
                    "version-3 contract signal_kind must be dense or selector")
            if not self.baseline_name.strip() or not self.baseline_source_hash.strip():
                raise ExperimentContractValidationError(
                    "version-3 contract requires a frozen executable baseline")
            if (not self.baseline_name.isidentifier()
                    or self.baseline_name == self.signal_name):
                raise ExperimentContractValidationError(
                    "version-3 baseline_name must be a distinct Python identifier")
        if self.contract_version >= 4:
            if not self.eligibility_name.strip() or not self.eligibility_source_hash.strip():
                raise ExperimentContractValidationError(
                    "version-4 contract requires frozen eligibility code")
            if (not self.eligibility_name.isidentifier()
                    or self.eligibility_name in (self.signal_name, self.baseline_name)):
                raise ExperimentContractValidationError(
                    "version-4 eligibility_name must be a distinct Python identifier")

    @property
    def contract_hash(self) -> str:
        semantic_fields = asdict(self)
        semantic_fields.pop("created_at", None)
        if self.contract_version < 3:
            for name in (
                "entry_price", "outcome_kind", "signal_kind", "baseline_name",
                "baseline_source_hash", "dissent_resolutions",
            ):
                semantic_fields.pop(name, None)
        if self.contract_version < 4:
            for name in ("eligibility_name", "eligibility_source_hash"):
                semantic_fields.pop(name, None)
        payload = json.dumps(semantic_fields, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["contract_hash"] = self.contract_hash
        data["horizons"] = list(self.horizons)
        data["baselines"] = list(self.baselines)
        data["requested_outcome_columns"] = list(self.requested_outcome_columns)
        data["abort_conditions"] = list(self.abort_conditions)
        data["parameter_neighbourhood"] = list(self.parameter_neighbourhood)
        data["permitted_result_readings"] = list(self.permitted_result_readings)
        data["dissent_resolutions"] = list(self.dissent_resolutions)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentContract:
        d = dict(data)
        expected_hash = d.pop("contract_hash", None)
        for k in ("horizons", "baselines", "requested_outcome_columns",
                  "abort_conditions", "parameter_neighbourhood",
                  "permitted_result_readings", "dissent_resolutions"):
            if k in d and isinstance(d[k], (list, tuple)):
                d[k] = tuple(d[k])
        contract = cls(**d)
        if expected_hash is not None and contract.contract_hash != expected_hash:
            raise ExperimentContractValidationError(
                f"contract_hash mismatch: stored {expected_hash}, "
                f"computed {contract.contract_hash}")
        return contract
