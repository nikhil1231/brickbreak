"""Sample Budget Ledger — First-class tracking of data exposure (the refactor plan §2.1).

THE DATA BUDGET IS PART OF THE ARCHITECTURE:
2020-2023 has been read twice (H033 and H037) and is spent for those hypothesis
families. The only wholly untainted data is sessions in the forward lane.

This module tracks every partition/quarter read across all experiments.
If a hypothesis or any ancestor in its lineage has already consumed a quarter
in a confirmatory role, subsequent confirmatory reads on that quarter raise
BudgetExhaustedError.

INVARIANT: When lineage is ambiguous, block.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..core import config
from ..research_data import splits
from . import store


LEDGER_PATH = config.METADATA_DIR / "research_store" / "ledger.json"


class BudgetExhaustedError(RuntimeError):
    pass


@dataclass
class LedgerEntry:
    """One recorded data partition read."""
    hypothesis_id: str
    family: str
    role: str                       # generation, exploratory, confirmatory
    partition: str                  # train, validation, test, forward
    quarters: list[str]             # e.g. ["2021Q1", "2021Q2"]
    manifest_hash: str = ""
    dataset_version: str = "v1"
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> LedgerEntry:
        return cls(**data)



class SampleBudgetLedger:
    """Ledger tracking data consumption and enforcing confirmatory access permissions."""

    def __init__(self, entries: list[LedgerEntry] | None = None,
                 path: Path | None = None) -> None:
        self._entries: list[LedgerEntry] = entries or []
        # A ledger remembers where it was loaded from. Without this, a ledger
        # opened from an alternate path still saved to LEDGER_PATH, so any
        # test or side experiment silently wrote into the production ledger.
        self._path: Path | None = path

    @classmethod
    def load(cls, path: Path | None = None) -> SampleBudgetLedger:
        p = path or LEDGER_PATH
        if not p.exists():
            ledger = cls(path=p)
            ledger._init_historical_exposure()
            ledger.save(p)
            return ledger

        data = json.loads(p.read_text())
        entries = [LedgerEntry.from_dict(e) for e in data.get("entries", [])]

        # If the exposure table has been corrected since this file was written,
        # rebuild the HISTORICAL rows from it. Real experiment records are
        # kept. A stale seed is how H024 came to be allowed back onto the
        # holdout it spent.
        if data.get("exposure_version") != splits.exposure_version():
            ledger = cls([e for e in entries if e.hypothesis_id != "HISTORICAL"],
                         path=p)
            ledger._init_historical_exposure()
            ledger.save(p)
            return ledger
        return cls(entries, path=p)

    def save(self, path: Path | None = None) -> Path:
        p = path or self._path or LEDGER_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "exposure_version": splits.exposure_version(),
            "n_entries": len(self._entries),
            "entries": [e.to_dict() for e in self._entries],
        }
        p.write_text(json.dumps(data, indent=2) + "\n")
        return p

    def _init_historical_exposure(self) -> None:
        """Seed the ledger from `splits.PRIOR_EXPOSURE`.

        Read live from the exposure table rather than from the manifest's
        embedded snapshot, so correcting what is known about a past read does
        not require redrawing a frozen split.
        """
        manifest = splits.load("v1")
        for q in manifest.get("quarters", []):
            start = pd.Timestamp(q["start"])
            end = pd.Timestamp(q["end"])
            for exp in splits.exposure_for(start, end):
                self._entries.append(LedgerEntry(
                    hypothesis_id="HISTORICAL",
                    family=exp["family"],
                    role=exp["role"],
                    partition=q.get("set", "unknown"),
                    quarters=[q["quarter"]],
                    manifest_hash="legacy",
                ))

    def record_usage(
        self,
        hypothesis_id: str,
        family: str,
        role: str,
        partition: str,
        quarters: list[str],
        manifest_hash: str = "",
        dataset_version: str = "v1",
        save_after: bool = True,
    ) -> LedgerEntry:
        """Records data consumption into the ledger."""
        entry = LedgerEntry(
            hypothesis_id=hypothesis_id,
            family=family,
            role=role,
            partition=partition,
            quarters=quarters,
            manifest_hash=manifest_hash,
            dataset_version=dataset_version,
        )
        self._entries.append(entry)
        if save_after:
            self.save()
        return entry

    def check_permission(
        self,
        hypothesis_id: str,
        family: str,
        role: str,
        quarters: list[str],
        dataset_version: str = "v1",
    ) -> tuple[bool, list[str]]:
        """Verifies if the hypothesis has permission to read the requested quarters in `role`.

        If `role == 'confirmatory'`, checks if this hypothesis, its family, or any
        ancestor in the idea graph has already read any of these quarters in a
        confirmatory role on this `dataset_version`.

        Returns (is_permitted, blocked_quarters).
        """
        if role != "confirmatory":
            # Exploratory / hypothesis generation reads are recorded but not hard-blocked
            return True, []

        # Find all related families and ancestor hypotheses
        graph = store.get_idea_graph()
        related_ids = graph.ancestors(hypothesis_id) | {hypothesis_id}

        # Also get all hypotheses sharing the same family
        hyps = store.list_hypotheses()
        family_names = {family}
        for h in hyps:
            if h.id in related_ids:
                family_names.add(h.family)

        blocked = []
        for q in quarters:
            # Check if q was previously read in confirmatory role by any related hypothesis or family
            for entry in self._entries:
                if entry.dataset_version == dataset_version and entry.role == "confirmatory" and q in entry.quarters:
                    if entry.family in family_names or entry.hypothesis_id in related_ids:
                        blocked.append(q)
                        break

        if blocked:
            return False, sorted(list(set(blocked)))
        return True, []

    def enforce_permission(
        self,
        hypothesis_id: str,
        family: str,
        role: str,
        quarters: list[str],
        dataset_version: str = "v1",
    ) -> None:
        """Raises BudgetExhaustedError if access is blocked."""
        ok, blocked = self.check_permission(hypothesis_id, family, role, quarters, dataset_version=dataset_version)
        if not ok:
            raise BudgetExhaustedError(
                f"Hypothesis {hypothesis_id} (family: {family}) is BLOCKED from "
                f"confirmatory read on {dataset_version} spent quarters: {blocked}. "
                f"These quarters were previously consumed in a confirmatory role. "
                f"The forward lane is the only clean confirmatory partition."
            )

