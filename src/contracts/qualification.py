"""Frozen outcome-free qualification artifact (PLAN.md stages AA-AB).

This is the missing link between a reviewed mechanism dossier and an
ExperimentContract.  It freezes the authored signal source and both E0 checks
before any forward return is constructed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from .dossier import MechanismDossier
from .lifecycle import LifecycleState, LifecycleTracker


class QualificationValidationError(ValueError):
    pass


def source_hash(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class QualificationArtifact:
    qualification_id: str
    dossier: dict[str, Any]
    adjudication_hash: str
    signal_name: str
    signal_source: str
    signal_source_hash: str
    question: str
    dataset_version: str
    partition: str
    horizons: tuple[int, ...]
    primary_horizon: int
    provider: str
    model: str
    author_summary: str
    model_turns: int
    model_cost_usd: float | None
    structural_gate: dict[str, Any]
    preflight: dict[str, Any]
    approved: bool
    rejection_reasons: tuple[str, ...]
    lifecycle: dict[str, Any]
    created_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    # Version 1 is the original single-source artifact. Version 2 freezes the
    # entry clock, outcome interpretation, selector semantics, and an
    # outcome-blind strongest-baseline implementation. Version 3 also freezes
    # the eligible population as executable code.
    artifact_version: int = 1
    entry_price: str = "close"
    outcome_kind: str = "raw"
    signal_kind: str = "dense"
    baseline_name: str = ""
    baseline_source: str = ""
    baseline_source_hash: str = ""
    dissent_resolutions: tuple[str, ...] = ()
    semantic_check: dict[str, Any] = field(default_factory=dict)
    eligibility_name: str = ""
    eligibility_source: str = ""
    eligibility_source_hash: str = ""

    def __post_init__(self) -> None:
        self.validate()

    @property
    def mechanism_dossier(self) -> MechanismDossier:
        return MechanismDossier.from_dict(self.dossier)

    def validate(self) -> None:
        if not self.qualification_id.strip():
            raise QualificationValidationError("qualification_id cannot be empty")
        dossier = self.mechanism_dossier
        if not self.adjudication_hash.strip():
            raise QualificationValidationError("adjudication_hash cannot be empty")
        if not self.signal_name.strip() or not self.signal_source.strip():
            raise QualificationValidationError("qualified signal source cannot be empty")
        if not self.signal_name.isidentifier():
            raise QualificationValidationError(
                "signal_name must be a valid Python identifier")
        actual_source_hash = source_hash(self.signal_source)
        if actual_source_hash != self.signal_source_hash:
            raise QualificationValidationError(
                f"signal_source_hash mismatch: stored {self.signal_source_hash}, "
                f"computed {actual_source_hash}")
        if self.partition != "train":
            raise QualificationValidationError(
                "outcome-free qualification must use the train predictor partition")
        if not self.horizons or any(h <= 0 for h in self.horizons):
            raise QualificationValidationError("horizons must be positive")
        if self.primary_horizon not in self.horizons:
            raise QualificationValidationError("primary_horizon must be in horizons")
        if self.model_turns < 0:
            raise QualificationValidationError("model_turns cannot be negative")
        if self.model_cost_usd is not None and self.model_cost_usd < 0:
            raise QualificationValidationError("model_cost_usd cannot be negative")
        if self.artifact_version not in (1, 2, 3):
            raise QualificationValidationError("unsupported qualification artifact_version")
        if self.artifact_version >= 2:
            if self.entry_price not in ("open", "close"):
                raise QualificationValidationError("entry_price must be open or close")
            if self.outcome_kind not in ("raw", "market_excess"):
                raise QualificationValidationError(
                    "outcome_kind must be raw or market_excess")
            if self.signal_kind not in ("dense", "selector"):
                raise QualificationValidationError(
                    "signal_kind must be dense or selector")
            if not self.baseline_name.strip() or not self.baseline_source.strip():
                raise QualificationValidationError(
                    "version-2 qualification requires a frozen baseline")
            if (not self.baseline_name.isidentifier()
                    or self.baseline_name == self.signal_name):
                raise QualificationValidationError(
                    "baseline_name must be a distinct Python identifier")
            if source_hash(self.baseline_source) != self.baseline_source_hash:
                raise QualificationValidationError(
                    "baseline_source_hash does not match baseline_source")
        if self.artifact_version >= 3:
            if not self.eligibility_name.strip() or not self.eligibility_source.strip():
                raise QualificationValidationError(
                    "version-3 qualification requires frozen eligibility code")
            if (not self.eligibility_name.isidentifier()
                    or self.eligibility_name in (self.signal_name, self.baseline_name)):
                raise QualificationValidationError(
                    "eligibility_name must be a distinct Python identifier")
            if source_hash(self.eligibility_source) != self.eligibility_source_hash:
                raise QualificationValidationError(
                    "eligibility_source_hash does not match eligibility_source")
        structural_passed = bool(self.structural_gate.get("passed"))
        preflight_passed = bool(self.preflight.get("passed"))
        semantic_passed = (bool(self.semantic_check.get("passed"))
                           if self.artifact_version >= 2 else True)
        expected_approved = structural_passed and preflight_passed and semantic_passed
        if self.approved != expected_approved:
            raise QualificationValidationError(
                "approved must equal structural, preflight, and semantic gate results")
        if not self.approved and not self.rejection_reasons:
            raise QualificationValidationError(
                "a rejected qualification must preserve its rejection reasons")
        tracker = LifecycleTracker.from_dict(self.lifecycle)
        expected_state = (LifecycleState.PREFLIGHTED if self.approved
                          else LifecycleState.DATA_READY)
        if tracker.entity_id != dossier.hypothesis_id:
            raise QualificationValidationError(
                "lifecycle entity does not match dossier hypothesis")
        if tracker.current_state != expected_state:
            raise QualificationValidationError(
                f"qualification lifecycle must end at {expected_state.value}")

    @property
    def qualification_hash(self) -> str:
        semantic = asdict(self)
        semantic.pop("created_at", None)
        if self.artifact_version == 1:
            for name in (
                "artifact_version", "entry_price", "outcome_kind", "signal_kind",
                "baseline_name", "baseline_source", "baseline_source_hash",
                "dissent_resolutions", "semantic_check",
                "eligibility_name", "eligibility_source",
                "eligibility_source_hash",
            ):
                semantic.pop(name, None)
        elif self.artifact_version == 2:
            for name in (
                "eligibility_name", "eligibility_source",
                "eligibility_source_hash",
            ):
                semantic.pop(name, None)
        payload = json.dumps(semantic, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["qualification_hash"] = self.qualification_hash
        data["horizons"] = list(self.horizons)
        data["rejection_reasons"] = list(self.rejection_reasons)
        data["dissent_resolutions"] = list(self.dissent_resolutions)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QualificationArtifact:
        raw = dict(data)
        expected_hash = raw.pop("qualification_hash", None)
        raw["horizons"] = tuple(raw.get("horizons", ()))
        raw["rejection_reasons"] = tuple(raw.get("rejection_reasons", ()))
        raw["dissent_resolutions"] = tuple(raw.get("dissent_resolutions", ()))
        artifact = cls(**raw)
        if expected_hash is not None and artifact.qualification_hash != expected_hash:
            raise QualificationValidationError(
                f"qualification_hash mismatch: stored {expected_hash}, "
                f"computed {artifact.qualification_hash}")
        return artifact
