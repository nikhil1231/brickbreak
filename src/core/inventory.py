"""Call-site and subsystem migration inventory (PLAN.md §11 and Stage V).

Enforces keep / generalise / replace / connect / retire dispositions across all
code in the lab. Every existing orchestration path has one declared destination.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Disposition(str, Enum):
    KEEP = "keep"
    GENERALISE = "generalise"
    REPLACE = "replace"
    CONNECT = "connect"
    RETIRE = "retire"


class MigrationStatus(str, Enum):
    ACTIVE = "active"
    IN_PROGRESS = "in_progress"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


@dataclass(frozen=True)
class InventoryItem:
    subsystem: str
    module_path: str
    disposition: Disposition
    target_stage: str
    destination: str
    rationale: str
    status: MigrationStatus = MigrationStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "subsystem": self.subsystem,
            "module_path": self.module_path,
            "disposition": self.disposition.value,
            "target_stage": self.target_stage,
            "destination": self.destination,
            "rationale": self.rationale,
            "status": self.status.value,
        }


INVENTORY: tuple[InventoryItem, ...] = (
    # --- KEEP ---
    InventoryItem(
        subsystem="research_data",
        module_path="src/research_data/frame.py",
        disposition=Disposition.KEEP,
        target_stage="Stage V",
        destination="src/research_data/frame.py",
        rationale="Point-in-time single door to market data, splits, and forward partitions.",
    ),
    InventoryItem(
        subsystem="persistence",
        module_path="src/persistence/ledger.py",
        disposition=Disposition.KEEP,
        target_stage="Stage V",
        destination="src/persistence/ledger.py",
        rationale="Sample budget and hypothesis exposure tracking.",
    ),
    InventoryItem(
        subsystem="alpha_eval",
        module_path="src/alpha_eval/report.py",
        disposition=Disposition.KEEP,
        target_stage="Stage V",
        destination="src/alpha_eval/report.py",
        rationale="Standard alpha battery, backtests, and Hansen-Hodrick corrections.",
    ),
    InventoryItem(
        subsystem="discretionary_replay",
        module_path="src/discretionary/replay.py",
        disposition=Disposition.KEEP,
        target_stage="Stage V",
        destination="src/discretionary/replay.py",
        rationale="Sealed replay phases, anonymisation, and decision evaluation.",
    ),
    InventoryItem(
        subsystem="discretionary_memory",
        module_path="src/discretionary/memory.py",
        disposition=Disposition.KEEP,
        target_stage="Stage U",
        destination="src/discretionary/memory.py",
        rationale="H042 memorisation control, recognition probes, and case quarantine.",
    ),

    # --- GENERALISE ---
    InventoryItem(
        subsystem="feasibility",
        module_path="src/research_data/feasibility.py",
        disposition=Disposition.GENERALISE,
        target_stage="Stage Y",
        destination="src/data_broker/probe.py",
        rationale="Generalise Breeze spike machinery into generic source probes.",
    ),
    InventoryItem(
        subsystem="hypothesis_graph",
        module_path="src/persistence/models.py",
        disposition=Disposition.GENERALISE,
        target_stage="Stage W/AA",
        destination="src/contracts/dossier.py",
        rationale="Generalise idea graph into mechanism dossiers and data provenance.",
    ),
    InventoryItem(
        subsystem="providers",
        module_path="src/discretionary/providers/",
        disposition=Disposition.GENERALISE,
        target_stage="Stage Z",
        destination="src/providers/pool.py",
        rationale="Expand CLI/API dispatch into four subscription lanes with quotas.",
    ),

    # --- REPLACE ---
    InventoryItem(
        subsystem="suggest",
        module_path="src/runner/suggest.py",
        disposition=Disposition.REPLACE,
        target_stage="Stage AA/AB",
        destination="src/council/scouts.py",
        rationale="Replace one-shot fixed-column suggestion with multi-lens research council.",
    ),
    InventoryItem(
        subsystem="planner",
        module_path="src/runner/planner.py",
        disposition=Disposition.REPLACE,
        target_stage="Stage W/AB",
        destination="src/contracts/compiler.py",
        rationale="Replace ad-hoc planning with immutable experiment contracts.",
    ),

    # --- CONNECT ---
    InventoryItem(
        subsystem="distillation",
        module_path="src/discretionary/distil.py",
        disposition=Disposition.CONNECT,
        target_stage="Stage U",
        destination="src/alpha_eval/evaluate_signal",
        rationale="Connect distilled rules to panel-scale signal evaluation.",
    ),
    InventoryItem(
        subsystem="forward_accrual",
        module_path="src/runner/forward.py",
        disposition=Disposition.CONNECT,
        target_stage="Stage U",
        destination="src/runner/forward.py",
        rationale="Connect replay forward identities and distilled rules to forward lane.",
    ),

    # --- RETIRE ---
    InventoryItem(
        subsystem="legacy_canned_suggest",
        module_path="src/runner/suggest.py:_canned",
        disposition=Disposition.RETIRE,
        target_stage="Stage AB",
        destination="N/A",
        rationale="Retire silent canned/offline suggestion fallbacks.",
    ),
)


def get_inventory(disposition: Disposition | None = None) -> list[InventoryItem]:
    """Query the inventory by disposition."""
    if disposition is None:
        return list(INVENTORY)
    return [item for item in INVENTORY if item.disposition == disposition]


def audit_dispositions() -> dict[str, int]:
    """Summary counts of subsystems by disposition."""
    counts: dict[str, int] = {}
    for item in INVENTORY:
        counts[item.disposition.value] = counts.get(item.disposition.value, 0) + 1
    return counts
