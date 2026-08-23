"""Tests for Stage V call-site inventory and migration map."""
from __future__ import annotations

from src.core.inventory import (
    INVENTORY,
    Disposition,
    MigrationStatus,
    audit_dispositions,
    get_inventory,
)


def test_inventory_is_populated_and_valid():
    assert len(INVENTORY) >= 10
    for item in INVENTORY:
        assert isinstance(item.disposition, Disposition)
        assert isinstance(item.status, MigrationStatus)
        assert item.subsystem
        assert item.module_path
        assert item.destination
        assert item.rationale


def test_query_inventory_by_disposition():
    keeps = get_inventory(Disposition.KEEP)
    assert len(keeps) >= 3
    assert any(k.subsystem == "research_data" for k in keeps)

    replaces = get_inventory(Disposition.REPLACE)
    assert len(replaces) >= 2
    assert any(r.subsystem == "suggest" for r in replaces)


def test_audit_dispositions():
    counts = audit_dispositions()
    assert "keep" in counts
    assert "generalise" in counts
    assert "replace" in counts
    assert "connect" in counts
    assert "retire" in counts
