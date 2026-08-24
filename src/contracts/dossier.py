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
    # Bootstrap economics.  `required_observations_absent` is deliberately
    # reserved for facts without which the minimum predictive test is invalid.
    # Gold-standard mechanism evidence belongs in the optional bucket and must
    # not block an otherwise honest E0 qualification.
    available_observations: tuple[str, ...] = ()
    optional_observations_absent: tuple[str, ...] = ()
    estimated_engineering_days: float = 0.0
    estimated_cash_cost_usd: float = 0.0
    # Version-2 execution semantics. Legacy dossiers remain readable, but the
    # research director refuses to qualify them until these are explicit.
    required_feature_names: tuple[str, ...] = ()
    data_adapter: str = ""
    entry_price: str = ""
    outcome_kind: str = ""
    signal_kind: str = ""
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
        if not self.population.strip():
            raise DossierValidationError("population cannot be empty")
        if self.expected_horizon_days <= 0:
            raise DossierValidationError("expected_horizon_days must be positive")
        if not self.observable_facts:
            raise DossierValidationError("observable_facts cannot be empty")
        if not self.interpretation.strip():
            raise DossierValidationError("interpretation cannot be empty")
        if not self.causal_chain.strip():
            raise DossierValidationError("causal_chain cannot be empty")
        if not self.counterparty.strip():
            raise DossierValidationError("counterparty cannot be empty")
        if not self.counterparty_persistence_rationale.strip():
            raise DossierValidationError(
                "counterparty_persistence_rationale cannot be empty")
        if len(self.competing_explanations) < 2:
            raise DossierValidationError(
                "at least two competing explanations are required (PLAN §3.1)")
        if not self.strongest_baseline.strip():
            raise DossierValidationError("strongest_baseline cannot be empty")
        if not self.natural_falsifiers:
            raise DossierValidationError("natural_falsifiers cannot be empty")
        if not self.unique_predictions:
            raise DossierValidationError("unique_predictions cannot be empty")
        if self.min_effect_bps <= 0.0:
            raise DossierValidationError("min_effect_bps must be positive")
        if not self.memory_risk_classification.strip():
            raise DossierValidationError("memory_risk_classification cannot be empty")
        if not self.forward_confirmation_path.strip():
            raise DossierValidationError("forward_confirmation_path cannot be empty")
        if not self.proposer.strip() or not self.hostile_reviewer.strip():
            raise DossierValidationError("proposer and hostile_reviewer cannot be empty")
        if self.proposer == self.hostile_reviewer:
            raise DossierValidationError(
                "proposer and hostile_reviewer must be separate entities (PLAN §4)")
        if self.estimated_engineering_days < 0:
            raise DossierValidationError("estimated_engineering_days cannot be negative")
        if self.estimated_cash_cost_usd < 0:
            raise DossierValidationError("estimated_cash_cost_usd cannot be negative")
        if self.data_adapter and self.data_adapter not in (
                "daily_panel_asof_open", "intraday_panel", "replay"):
            raise DossierValidationError("unsupported data_adapter")
        if self.entry_price and self.entry_price not in ("open", "close", "intraday"):
            raise DossierValidationError("entry_price must be open, close or intraday")
        if self.outcome_kind and self.outcome_kind not in ("raw", "market_excess"):
            raise DossierValidationError("outcome_kind must be raw or market_excess")
        if self.signal_kind and self.signal_kind not in ("dense", "selector"):
            raise DossierValidationError("signal_kind must be dense or selector")

    @property
    def has_data_gap(self) -> bool:
        """Whether the minimum valid test is blocked, not whether richer data exists."""
        return len(self.required_observations_absent) > 0

    @property
    def bootstrap_ready(self) -> bool:
        return not self.has_data_gap

    @property
    def execution_semantics_explicit(self) -> bool:
        return bool(
            self.required_feature_names
            and self.data_adapter
            and self.entry_price
            and self.outcome_kind
            and self.signal_kind
        )

    @staticmethod
    def _hash_fields(fields: dict[str, Any]) -> str:
        payload = json.dumps(fields, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _semantic_fields(self) -> dict[str, Any]:
        fields = asdict(self)
        fields.pop("created_at", None)
        return fields

    @property
    def legacy_dossier_hash(self) -> str:
        """Hash used before bootstrap cost/optionality fields were introduced."""
        fields = self._semantic_fields()
        for name in (
            "available_observations", "optional_observations_absent",
            "estimated_engineering_days", "estimated_cash_cost_usd",
            "required_feature_names", "data_adapter", "entry_price",
            "outcome_kind", "signal_kind",
        ):
            fields.pop(name, None)
        return self._hash_fields(fields)

    @property
    def pre_execution_dossier_hash(self) -> str:
        """Hash used before execution semantics became explicit fields."""
        fields = self._semantic_fields()
        for name in (
            "required_feature_names", "data_adapter", "entry_price",
            "outcome_kind", "signal_kind",
        ):
            fields.pop(name, None)
        return self._hash_fields(fields)

    @property
    def dossier_hash(self) -> str:
        return self._hash_fields(self._semantic_fields())

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["dossier_hash"] = self.dossier_hash
        data["has_data_gap"] = self.has_data_gap
        data["bootstrap_ready"] = self.bootstrap_ready
        data["dissents"] = [d.to_dict() for d in self.dissents]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MechanismDossier:
        d = dict(data)
        expected_hash = d.pop("dossier_hash", None)
        d.pop("has_data_gap", None)
        d.pop("bootstrap_ready", None)
        had_bootstrap_fields = any(name in d for name in (
            "available_observations", "optional_observations_absent",
            "estimated_engineering_days", "estimated_cash_cost_usd",
        ))
        had_execution_fields = any(name in d for name in (
            "required_feature_names", "data_adapter", "entry_price",
            "outcome_kind", "signal_kind",
        ))
        if "dissents" in d:
            d["dissents"] = tuple(
                DossierDissent(**x) if isinstance(x, dict) else x for x in d["dissents"]
            )
        for k in ("observable_facts", "competing_explanations", "unique_predictions",
                  "natural_falsifiers", "confounds", "nearest_hypothesis_ids",
                  "required_observations_absent", "available_observations",
                  "optional_observations_absent", "required_feature_names"):
            if k in d and isinstance(d[k], (list, tuple)):
                d[k] = tuple(d[k])
        dossier = cls(**d)
        hash_matches = dossier.dossier_hash == expected_hash
        if expected_hash is not None and not had_execution_fields:
            hash_matches = (hash_matches
                            or dossier.pre_execution_dossier_hash == expected_hash)
        if expected_hash is not None and not had_bootstrap_fields:
            hash_matches = hash_matches or dossier.legacy_dossier_hash == expected_hash
        if expected_hash is not None and not hash_matches:
            raise DossierValidationError(
                f"dossier_hash mismatch: stored {expected_hash}, "
                f"computed {dossier.dossier_hash}")
        return dossier
