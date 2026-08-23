"""Data contract specification (PLAN.md §3.2 and Stage W).

A missing observation creates a data request. A source is not acquired until a
probe turns that request into a contract recording:
- source owner, licence/terms, cash price, authentication and rate limits;
- raw fields, identifiers, timestamp and time-zone semantics;
- publication latency, revisions, corrections and historical availability;
- depth, universe coverage, survivorship, missingness, expected join rate;
- exact `available_at` and `first_tradable_session` rules;
- pagination, caps, silent truncation and repeated-call stability;
- entity-resolution and symbol-history policy;
- immutable raw-byte provenance, hashes, refresh cadence and maintenance owner;
- download time, storage, usable events per session and independent blocks;
- validation fixtures, catalogue entries and PIT/invariance tests;
- which other mechanism families the finished data product unlocks.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Sequence


class DataContractValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SourceFieldDef:
    name: str
    dtype: str
    description: str
    is_pit: bool
    nullable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DataContract:
    contract_id: str
    source_name: str
    source_owner: str
    licence_type: str  # "public", "proprietary", "exchange_terms"
    cash_cost_usd: float
    rate_limits: str
    raw_fields: tuple[SourceFieldDef, ...]
    timestamp_tz: str
    publication_latency_hours: float
    available_at_rule: str
    first_tradable_session_rule: str
    coverage_start: str
    coverage_end: str
    universe_depth: str
    survivorship_policy: str
    expected_join_rate_pct: float
    pagination_and_caps_notes: str
    entity_resolution_policy: str
    unlocked_families: tuple[str, ...]
    storage_path: str
    maintenance_owner: str
    created_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not self.contract_id.strip():
            raise DataContractValidationError("contract_id cannot be empty")
        if not self.source_name.strip():
            raise DataContractValidationError("source_name cannot be empty")
        if not self.raw_fields:
            raise DataContractValidationError("raw_fields cannot be empty")
        if not self.available_at_rule.strip():
            raise DataContractValidationError("available_at_rule must be explicitly declared (PLAN §3.2)")
        if not self.first_tradable_session_rule.strip():
            raise DataContractValidationError("first_tradable_session_rule must be explicitly declared (PLAN §3.2)")
        if self.expected_join_rate_pct < 0 or self.expected_join_rate_pct > 100:
            raise DataContractValidationError("expected_join_rate_pct must be between 0 and 100")
        if self.cash_cost_usd < 0:
            raise DataContractValidationError("cash_cost_usd cannot be negative")

    @property
    def contract_hash(self) -> str:
        payload = json.dumps(
            {
                "contract_id": self.contract_id,
                "source_name": self.source_name,
                "licence_type": self.licence_type,
                "cash_cost_usd": self.cash_cost_usd,
                "available_at_rule": self.available_at_rule,
                "first_tradable_session_rule": self.first_tradable_session_rule,
                "raw_fields": [f.to_dict() for f in self.raw_fields],
                "unlocked_families": list(self.unlocked_families),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["contract_hash"] = self.contract_hash
        data["raw_fields"] = [f.to_dict() for f in self.raw_fields]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DataContract:
        d = dict(data)
        d.pop("contract_hash", None)
        if "raw_fields" in d:
            d["raw_fields"] = tuple(
                SourceFieldDef(**f) if isinstance(f, dict) else f for f in d["raw_fields"]
            )
        if "unlocked_families" in d and isinstance(d["unlocked_families"], (list, tuple)):
            d["unlocked_families"] = tuple(d["unlocked_families"])
        return cls(**d)
