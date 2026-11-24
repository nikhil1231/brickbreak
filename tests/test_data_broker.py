"""Tests for Stage Y data broker."""
from __future__ import annotations

import pandas as pd
import pytest

from src.contracts.data_contract import SourceFieldDef
from src.data_broker import (
    ApprovalStatus,
    create_approval_card,
    run_source_micro_probe,
    synthesize_data_contract,
)


def test_micro_probe_normal_data():
    dates = pd.bdate_range("2021-01-04", periods=50)
    df = pd.DataFrame({
        "symbol": ["RELIANCE", "TCS"] * 25,
        "date": dates,
        "timestamp": dates + pd.Timedelta(hours=10, minutes=30),
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


def test_micro_probe_does_not_call_a_mixed_timestamp_era_exact():
    df = pd.DataFrame({
        "date": pd.to_datetime(["2006-01-02", "2026-01-02"]),
        "timestamp": ["2006-01-02 00:00:00", "2026-01-02 14:30:00"],
    })
    result = run_source_micro_probe(
        "Mixed Feed", df, date_col="date", time_col="timestamp")
    assert result.timestamp_fidelity == "mixed"


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


def test_failed_probe_cannot_be_promoted_into_a_data_contract():
    probe = run_source_micro_probe("Empty Feed", pd.DataFrame())
    approval = create_approval_card(
        "Empty Feed", "public", 0.0, 1.0, ("test_fam",), 0)

    with pytest.raises(ValueError, match="failed source probe"):
        synthesize_data_contract(
            probe=probe,
            approval=approval,
            fields=[SourceFieldDef("date", "datetime64[ns]", "Date", is_pit=True)],
            source_owner="Test Exchange",
            storage_path="data/raw/empty/",
            available_at_rule="After close",
            first_tradable_session_rule="Next session",
        )


def test_approval_card_cannot_be_reused_for_another_source():
    dates = pd.bdate_range("2021-01-04", periods=10)
    probe = run_source_micro_probe(
        "Source A", pd.DataFrame({"date": dates, "value": range(10)}))
    approval = create_approval_card(
        "Source B", "public", 0.0, 1.0, ("family",), 5)
    with pytest.raises(ValueError, match="does not match"):
        synthesize_data_contract(
            probe=probe, approval=approval,
            fields=[SourceFieldDef("date", "datetime64[ns]", "Date", is_pit=True)],
            source_owner="Exchange", storage_path="data/raw/source_a/",
            available_at_rule="After close",
            first_tradable_session_rule="Next session",
        )
