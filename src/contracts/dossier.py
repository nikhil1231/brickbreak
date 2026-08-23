"""Mechanism dossier contract (PLAN.md §3.1 and Stage W).

The research director produces a dossier, not executable signal code. It names:
- the claim, population and expected horizon;
- observable facts separated from the interpretation placed on them;
- the causal chain and the participant persistently on the other side;
- why that participant's behaviour can continue despite the claimed edge;
- at least two competing explanations and the strongest simple baseline;
- predictions unique to the proposed mechanism;
- natural falsifiers, confounds, capacity and minimum effect above costs;
- nearest nodes in the hypothesis graph and expected correlation with existing signals;
- observations required but absent from the catalogue;
- historical LLM memory risk and confirmation path;
- proposer, hostile reviewer and unresolved disagreement.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Sequence


class DossierValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DossierDissent:
    """A reviewer's objection that was preserved rather than averaged away."""
    reviewer_role: str
    objection: str
    severity: str  # "fatal", "material", "advisory"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MechanismDossier:
    dossier_id: str
    hypothesis_id: str
    family: str
    claim: str
    population: str
    expected_horizon_days: int
    observable_facts: tuple[str, ...]
    interpretation: str
    causal_chain: str
    counterparty: str
    counterparty_persistence_rationale: str
    competing_explanations: tuple[str, ...]
    strongest_baseline: str
    unique_predictions: tuple[str, ...]
    natural_falsifiers: tuple[str, ...]
    confounds: tuple[str, ...]
    capacity_notes: str
    min_effect_bps: float
    nearest_hypothesis_ids: tuple[str, ...]
    required_observations_absent: tuple[str, ...]
    memory_risk_classification: str
    forward_confirmation_path: str
    proposer: str
    hostile_reviewer: str
    dissents: tuple[DossierDissent, ...] = ()
    created_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not self.dossier_id.strip():
            raise DossierValidationError("dossier_id cannot be empty")
        if not self.hypothesis_id.strip():
            raise DossierValidationError("hypothesis_id cannot be empty")
        if not self.claim.strip():
            raise DossierValidationError("claim cannot be empty")
        if not self.causal_chain.strip():
            raise DossierValidationError("causal_chain cannot be empty")
        if not self.counterparty.strip():
            raise DossierValidationError("counterparty cannot be empty")
        if len(self.competing_explanations) < 2:
            raise DossierValidationError(
                "at least two competing explanations are required (PLAN §3.1)")
        if not self.strongest_baseline.strip():
            raise DossierValidationError("strongest_baseline cannot be empty")
        if not self.natural_falsifiers:
            raise DossierValidationError("natural_falsifiers cannot be empty")
        if self.min_effect_bps <= 0.0:
            raise DossierValidationError("min_effect_bps must be positive")
        if self.proposer == self.hostile_reviewer:
            raise DossierValidationError(
                "proposer and hostile_reviewer must be separate entities (PLAN §4)")

    @property
    def has_data_gap(self) -> bool:
        return len(self.required_observations_absent) > 0

    @property
    def dossier_hash(self) -> str:
        payload = json.dumps(
            {
                "dossier_id": self.dossier_id,
                "hypothesis_id": self.hypothesis_id,
                "claim": self.claim,
                "causal_chain": self.causal_chain,
                "counterparty": self.counterparty,
                "competing_explanations": list(self.competing_explanations),
                "strongest_baseline": self.strongest_baseline,
                "natural_falsifiers": list(self.natural_falsifiers),
                "min_effect_bps": self.min_effect_bps,
                "required_observations_absent": list(self.required_observations_absent),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["dossier_hash"] = self.dossier_hash
        data["has_data_gap"] = self.has_data_gap
        data["dissents"] = [d.to_dict() for d in self.dissents]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MechanismDossier:
        d = dict(data)
        d.pop("dossier_hash", None)
        d.pop("has_data_gap", None)
        if "dissents" in d:
            d["dissents"] = tuple(
                DossierDissent(**x) if isinstance(x, dict) else x for x in d["dissents"]
            )
        for k in ("observable_facts", "competing_explanations", "unique_predictions",
                  "natural_falsifiers", "confounds", "nearest_hypothesis_ids",
                  "required_observations_absent"):
            if k in d and isinstance(d[k], (list, tuple)):
                d[k] = tuple(d[k])
        return cls(**d)
