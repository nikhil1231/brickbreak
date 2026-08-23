"""Tests for Stage Y data broker."""
from __future__ import annotations

import pandas as pd
import pytest

from src.contracts.data_contract import SourceFieldDef
from src.data_broker import (
    ApprovalStatus,
    compute_data_roi_score,
    create_approval_card,
    run_source_micro_probe,
    synthesize_data_contract,
)


def test_micro_probe_normal_data():
    dates = pd.bdate_range("2021-01-04", periods=50)
    df = pd.DataFrame({
        "symbol": ["RELIANCE", "TCS"] * 25,
        "date": dates,
        "timestamp": [str(d) + " 10:30:00" for d in dates],
        "quantity": [1000] * 50,
    })
    res = run_source_micro_probe(
        source_name="Test Feed",
        sample_df=df,
        date_col="date",
        time_col="timestamp",
        calendar_sessions=dates,
    )
    assert res.passed
    assert res.n_sample_rows == 50
    assert not res.silent_cap_detected
    assert res.join_rate_pct == 100.0
    assert res.timestamp_fidelity == "exact_intraday"


def test_micro_probe_cap_detection_and_empty():
    # Empty
    empty_res = run_source_micro_probe("Empty", pd.DataFrame())
    assert not empty_res.passed
    assert empty_res.n_sample_rows == 0

    # Cap collision (70 rows)
    capped_df = pd.DataFrame({"date": ["2021-01-04"] * 70, "val": range(70)})
    capped_res = run_source_micro_probe("Capped", capped_df, known_cap_threshold=70)
    assert capped_res.silent_cap_detected
    assert not capped_res.passed


def test_approval_card_and_roi_calculation():
    # Free public source -> Auto-approved
    free_card = create_approval_card(
        source_name="NSE Free Bhavcopy",
        licence_type="exchange_terms",
        cash_cost_usd=0.0,
        engineering_hours=1.0,
        mechanisms_unlocked=("momentum", "reversal"),
        independent_blocks_added=20,
    )
    assert free_card.status == ApprovalStatus.AUTO_APPROVED
    assert free_card.roi_priority_score > 5.0

    # Paid proprietary source -> Pending
    paid_card = create_approval_card(
        source_name="Paid Vendor",
        licence_type="proprietary",
        cash_cost_usd=500.0,
        engineering_hours=10.0,
        mechanisms_unlocked=("alt_data",),
        independent_blocks_added=10,
    )
    assert paid_card.status == ApprovalStatus.PENDING


def test_synthesize_data_contract():
    dates = pd.bdate_range("2021-01-04", periods=30)
    sample_df = pd.DataFrame({"symbol": ["S1"] * 30, "date": dates, "shares": range(30)})
    probe = run_source_micro_probe("Sample Feed", sample_df)
    approval = create_approval_card("Sample Feed", "public", 0.0, 1.0, ("test_fam",), 15)

    fields = [
        SourceFieldDef("date", "datetime64[ns]", "Session date", is_pit=True),
        SourceFieldDef("shares", "int64", "Shares volume", is_pit=True),
    ]

    dc = synthesize_data_contract(
        probe=probe,
        approval=approval,
        fields=fields,
        source_owner="Test Exchange",
        storage_path="data/raw/sample/",
        available_at_rule="Available on date at 18:00",
        first_tradable_session_rule="First tradable on date + 1 session",
    )
    assert dc.contract_hash
    assert dc.source_name == "Sample Feed"
    assert dc.cash_cost_usd == 0.0
