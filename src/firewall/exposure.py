"""Outcome exposure levels and accounting (PLAN.md §6 and Stage X).

Levels:
- E0: mechanics (outcome-free; no sample spent)
- E1: shape (dispersion/variance without direction; consumes outcome access slot & shape burden)
- E2: directional train (full exploration & multiplicity burden)
- E3: confirmatory (validation or frozen test; one-way promotion)
- E4: forward (post-registration chronological accrual)

Rate limit: E1 + E2 share a ceiling of 5 accesses per calendar week.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from ..core import config


class ExposureLevel(str, Enum):
    E0_MECHANICS = "E0"
    E1_SHAPE = "E1"
    E2_DIRECTIONAL_TRAIN = "E2"
    E3_CONFIRMATORY = "E3"
    E4_FORWARD = "E4"


class ExposureLimitError(RuntimeError):
    pass


WEEKLY_OUTCOME_ACCESS_CEILING = 5


@dataclass(frozen=True)
class ExposureEntry:
    entry_id: str
    hypothesis_id: str
    family: str
    batch_id: str
    exposure_level: ExposureLevel
    dataset_version: str
    partition: str
    target_columns: tuple[str, ...]
    actor: str
    reason: str
    timestamp: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "hypothesis_id": self.hypothesis_id,
            "family": self.family,
            "batch_id": self.batch_id,
            "exposure_level": self.exposure_level.value,
            "dataset_version": self.dataset_version,
            "partition": self.partition,
            "target_columns": list(self.target_columns),
            "actor": self.actor,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


EXPOSURE_LOG_PATH = config.METADATA_DIR / "research_store" / "exposure_log.json"


def load_exposure_log(path: Path | None = None) -> list[ExposureEntry]:
    p = path or EXPOSURE_LOG_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        entries = []
        for item in data.get("entries", []):
            item_copy = dict(item)
            item_copy["exposure_level"] = ExposureLevel(item_copy["exposure_level"])
            item_copy["target_columns"] = tuple(item_copy["target_columns"])
            entries.append(ExposureEntry(**item_copy))
        return entries
    except Exception:
        return []


def save_exposure_log(entries: Sequence[ExposureEntry], path: Path | None = None) -> None:
    p = path or EXPOSURE_LOG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "entries": [e.to_dict() for e in entries],
    }
    p.write_text(json.dumps(payload, indent=2) + "\n")


def check_weekly_exposure_limit(entries: Sequence[ExposureEntry],
                                now: datetime | None = None,
                                ceiling: int = WEEKLY_OUTCOME_ACCESS_CEILING
                                ) -> tuple[int, bool]:
    """Check how many E1/E2 outcome exposures occurred in the trailing 7 days."""
    ref_time = now or datetime.now()
    cutoff = ref_time - timedelta(days=7)
    recent_outcome_exposures = 0
    for e in entries:
        if e.exposure_level in (ExposureLevel.E1_SHAPE, ExposureLevel.E2_DIRECTIONAL_TRAIN):
            try:
                t = datetime.strptime(e.timestamp, "%Y-%m-%d %H:%M:%S")
                if t >= cutoff:
                    recent_outcome_exposures += 1
            except Exception:
                pass
    can_proceed = recent_outcome_exposures < ceiling
    return recent_outcome_exposures, can_proceed


def record_exposure(hypothesis_id: str,
                    family: str,
                    batch_id: str,
                    level: ExposureLevel,
                    dataset_version: str,
                    partition: str,
                    target_columns: Sequence[str],
                    actor: str,
                    reason: str,
                    path: Path | None = None,
                    enforce_limit: bool = True) -> ExposureEntry:
    """Record an exposure event in the research ledger."""
    entries = load_exposure_log(path)
    if enforce_limit and level in (ExposureLevel.E1_SHAPE, ExposureLevel.E2_DIRECTIONAL_TRAIN):
        count, ok = check_weekly_exposure_limit(entries)
        if not ok:
            raise ExposureLimitError(
                f"Weekly outcome exposure ceiling reached ({count}/{WEEKLY_OUTCOME_ACCESS_CEILING} in trailing 7 days). "
                f"Cannot spend further outcome access without human review (PLAN.md §6)."
            )

    entry = ExposureEntry(
        entry_id=f"EXP_{len(entries)+1:04d}_{datetime.now():%Y%m%d_%H%M%S}",
        hypothesis_id=hypothesis_id,
        family=family,
        batch_id=batch_id,
        exposure_level=level,
        dataset_version=dataset_version,
        partition=partition,
        target_columns=tuple(target_columns),
        actor=actor,
        reason=reason,
    )
    entries.append(entry)
    save_exposure_log(entries, path)
    return entry
