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
import os
import tempfile
import uuid
from contextlib import contextmanager
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


class ExposureLogError(RuntimeError):
    """The exposure ledger is unreadable; outcome access must fail closed."""


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
    source_id: str = ""
    voided_reason: str = ""
    voided_at: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    @property
    def is_void(self) -> bool:
        return bool(self.voided_reason)

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
            "source_id": self.source_id,
            "voided_reason": self.voided_reason,
            "voided_at": self.voided_at,
            "timestamp": self.timestamp,
        }


EXPOSURE_LOG_PATH = config.METADATA_DIR / "research_store" / "exposure_log.json"


def _read_exposure_log(p: Path) -> list[ExposureEntry]:
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, dict) or not isinstance(data.get("entries", []), list):
            raise ValueError("root must contain an entries list")
        entries = []
        for item in data.get("entries", []):
            item_copy = dict(item)
            item_copy["exposure_level"] = ExposureLevel(item_copy["exposure_level"])
            item_copy["target_columns"] = tuple(item_copy["target_columns"])
            entries.append(ExposureEntry(**item_copy))
        return entries
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ExposureLogError(
            f"Exposure ledger {p} is unreadable; refusing outcome access: {exc}") from exc


def _write_exposure_log(entries: Sequence[ExposureEntry], p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "entries": [e.to_dict() for e in entries],
    }
    fd, tmp_name = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp",
                                    dir=str(p.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, p)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


@contextmanager
def _exclusive_log_lock(p: Path):
    """Serialize quota check plus append across processes."""
    import fcntl

    p.parent.mkdir(parents=True, exist_ok=True)
    lock_path = p.with_name(f".{p.name}.lock")
    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def load_exposure_log(path: Path | None = None) -> list[ExposureEntry]:
    p = path or EXPOSURE_LOG_PATH
    return _read_exposure_log(p)


def save_exposure_log(entries: Sequence[ExposureEntry], path: Path | None = None) -> None:
    p = path or EXPOSURE_LOG_PATH
    with _exclusive_log_lock(p):
        _write_exposure_log(entries, p)


def check_weekly_exposure_limit(entries: Sequence[ExposureEntry],
                                now: datetime | None = None,
                                ceiling: int = WEEKLY_OUTCOME_ACCESS_CEILING
                                ) -> tuple[int, bool]:
    """Check how many E1/E2 outcome exposures occurred in the trailing 7 days."""
    ref_time = now or datetime.now()
    cutoff = ref_time - timedelta(days=7)
    recent_outcome_exposures = 0
    for e in entries:
        if e.is_void:
            continue
        if e.exposure_level in (ExposureLevel.E1_SHAPE, ExposureLevel.E2_DIRECTIONAL_TRAIN):
            try:
                t = datetime.strptime(e.timestamp, "%Y-%m-%d %H:%M:%S")
                if t >= cutoff:
                    recent_outcome_exposures += 1
            except (TypeError, ValueError) as exc:
                raise ExposureLogError(
                    f"Exposure entry {e.entry_id!r} has an invalid timestamp; "
                    "refusing to undercount quota") from exc
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
                    source_id: str = "",
                    timestamp: str | None = None,
                    path: Path | None = None,
                    enforce_limit: bool = True) -> ExposureEntry:
    """Record an exposure event in the research ledger."""
    if not isinstance(level, ExposureLevel):
        raise TypeError("level must be an ExposureLevel")
    for name, value in (
        ("hypothesis_id", hypothesis_id), ("family", family),
        ("batch_id", batch_id), ("dataset_version", dataset_version),
        ("partition", partition), ("actor", actor), ("reason", reason),
    ):
        if not str(value).strip():
            raise ValueError(f"{name} cannot be empty in an exposure record")
    if level in (ExposureLevel.E1_SHAPE, ExposureLevel.E2_DIRECTIONAL_TRAIN) \
            and partition != "train":
        raise ValueError(f"{level.value} exposure must use the train partition")
    if level == ExposureLevel.E3_CONFIRMATORY \
            and partition not in ("validation", "test"):
        raise ValueError("E3 exposure must use validation or test")
    if level == ExposureLevel.E4_FORWARD and partition != "forward":
        raise ValueError("E4 exposure must use forward")
    if level != ExposureLevel.E0_MECHANICS and not target_columns:
        raise ValueError("outcome exposure must declare target_columns")

    p = path or EXPOSURE_LOG_PATH
    production_path = config.METADATA_DIR / "research_store" / "exposure_log.json"
    if (p.resolve() == production_path.resolve()
            and source_id
            and "TEST" in source_id.upper()):
        raise ExposureLogError(
            f"test-like source_id {source_id!r} cannot spend the production "
            "outcome ledger; pass an isolated exposure path")
    with _exclusive_log_lock(p):
        entries = _read_exposure_log(p)
        if source_id:
            existing = next(
                (entry for entry in entries if entry.source_id == source_id), None)
            if existing is not None:
                identity = (
                    existing.hypothesis_id == hypothesis_id
                    and existing.family == family
                    and existing.batch_id == batch_id
                    and existing.exposure_level == level
                    and existing.dataset_version == dataset_version
                    and existing.partition == partition
                    and existing.target_columns == tuple(target_columns)
                )
                if not identity:
                    raise ExposureLogError(
                        f"Exposure source_id {source_id!r} is already bound to a "
                        "different outcome access; refusing id reuse")
                return existing
        if enforce_limit and level in (
                ExposureLevel.E1_SHAPE, ExposureLevel.E2_DIRECTIONAL_TRAIN):
            count, ok = check_weekly_exposure_limit(entries)
            if not ok:
                raise ExposureLimitError(
                    f"Weekly outcome exposure ceiling reached "
                    f"({count}/{WEEKLY_OUTCOME_ACCESS_CEILING} in trailing 7 days). "
                    f"Cannot spend further outcome access without human review "
                    f"(PLAN.md §6)."
                )

        entry = ExposureEntry(
            entry_id=f"EXP_{datetime.now():%Y%m%d_%H%M%S_%f}_{uuid.uuid4().hex[:6]}",
            hypothesis_id=hypothesis_id,
            family=family,
            batch_id=batch_id,
            exposure_level=level,
            dataset_version=dataset_version,
            partition=partition,
            target_columns=tuple(target_columns),
            actor=actor,
            reason=reason,
            source_id=source_id,
            timestamp=timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        entries.append(entry)
        _write_exposure_log(entries, p)
        return entry
