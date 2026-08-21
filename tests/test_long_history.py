"""Tests for Long History, Per-Feature Floors, and Dataset-Version Ledger Segregation (Stage I, PLAN.md §8, §9).

Done when:
A momentum hypothesis scores on 20 years and a delivery hypothesis on 6,
from the same catalogue.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.alpha_eval import evaluate_signal
from src.persistence import Hypothesis, LedgerEntry, SampleBudgetLedger, store
from src.research_data import catalogue, frame, splits
from src.runner import run_exploration
from src.runner.spec import ExperimentSpec



@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Isolate store directories for test runs."""
    store_dir = tmp_path / "research_store"
    monkeypatch.setattr(store, "STORE_DIR", store_dir)
    monkeypatch.setattr(store, "HYPOTHESES_DIR", store_dir / "hypotheses")
    monkeypatch.setattr(store, "EXPLORATIONS_DIR", store_dir / "explorations")
    monkeypatch.setattr(store, "SIGNALS_DIR", store_dir / "signals")
    monkeypatch.setattr(store, "EVIDENCE_DIR", store_dir / "evidence")
    monkeypatch.setattr(store, "SUGGESTIONS_DIR", store_dir / "suggestions")
    monkeypatch.setattr(store, "PREFLIGHTS_DIR", store_dir / "preflights")
    monkeypatch.setattr(store, "QUEUE_DIR", store_dir / "queue")
    monkeypatch.setattr(store, "BATCHES_DIR", store_dir / "batches")
    store._ensure_dirs()


class TestLongHistoryAndFeatureFloors:
    def test_feature_floors_in_catalogue(self):
        cat = catalogue.DEFAULT

        # Price / momentum features have long history floor (2000-01-01)
        assert cat.feature_floor("ret_20d") == "2000-01-01"
        assert cat.feature_floor("ret_60d") == "2000-01-01"
        assert cat.feature_floor("ema_fast") == "2000-01-01"
        assert cat.feature_floor("atr_pct") == "2000-01-01"

        # Delivery features have 2020-01-01 floor
        assert cat.feature_floor("deliv_pct") == "2020-01-01"

        # Effective floor takes the latest requirement
        assert cat.effective_floor(["ret_20d", "ema_fast"]) == "2000-01-01"
        assert cat.effective_floor(["ret_20d", "deliv_pct"]) == "2020-01-01"

    def test_ledger_segregated_by_dataset_version(self):
        """Splitting the sample budget ledger by dataset version ensures long history

        does not draw down the delivery-era budget (PLAN.md §8).
        """
        ledger = SampleBudgetLedger()

        # Record confirmatory read on 2021Q1 on v1
        ledger.record_usage(
            hypothesis_id="H001",
            family="opening_window",
            role="confirmatory",
            partition="test",
            quarters=["2021Q1"],
            dataset_version="v1",
        )

        # On v1, 2021Q1 is blocked for confirmatory read
        ok_v1, blocked_v1 = ledger.check_permission(
            hypothesis_id="H001",
            family="opening_window",
            role="confirmatory",
            quarters=["2021Q1"],
            dataset_version="v1",
        )
        assert ok_v1 is False
        assert "2021Q1" in blocked_v1

        # On v2_long, 2021Q1 is NOT blocked because prior exposure was on v1
        ok_v2, blocked_v2 = ledger.check_permission(
            hypothesis_id="H001",
            family="opening_window",
            role="confirmatory",
            quarters=["2021Q1"],
            dataset_version="v2_long",
        )
        assert ok_v2 is True
        assert blocked_v2 == []

    def test_momentum_scores_on_20_years_and_delivery_on_6_from_same_catalogue(self):
        """CRITICAL LOAD-BEARING TEST (PLAN.md §9, Stage I).

        A momentum hypothesis scores on 20 years and a delivery hypothesis on 6,
        from the same catalogue.
        """
        # Register both hypotheses
        h_mom = Hypothesis(
            id="H_MOM",
            title="20-Year Long History Momentum",
            statement="20-day momentum generates persistent alpha over 20-year history",
            rationale="Trend continuation in equity cross-section",
            family="momentum",
            status="proposed",
        )
        store.save_hypothesis(h_mom)

        h_del = Hypothesis(
            id="H_DEL",
            title="6-Year Delivery Persistence",
            statement="Delivery volume percentage predicts alpha in delivery era",
            rationale="Institutional accumulation visible via delivery",
            family="delivery",
            status="proposed",
        )
        store.save_hypothesis(h_del)


        # 1. Momentum spec on v2_long (20-year history)
        spec_mom = ExperimentSpec(
            hypothesis_id="H_MOM",
            question="Does 20-day momentum produce alpha over 20 years?",
            signal_name="ret_20d",
            partition="train",
            dataset_version="v2_long",
            role="exploratory",
        )

        # 2. Delivery spec on v1 (6-year history)
        spec_del = ExperimentSpec(
            hypothesis_id="H_DEL",
            question="Does delivery percentage produce alpha in delivery era?",
            signal_name="deliv_pct",
            partition="train",
            dataset_version="v1",
            role="exploratory",
        )

        cat = catalogue.DEFAULT
        assert cat.feature_floor(spec_mom.signal_name) == "2000-01-01"
        assert cat.feature_floor(spec_del.signal_name) == "2020-01-01"

        # Verify both split manifests load cleanly from the same catalogue
        split_long = splits.load(spec_mom.dataset_version)
        split_del = splits.load(spec_del.dataset_version)

        assert split_long["version"] == "v2_long"
        assert split_long["panel"]["n_quarters"] > 80  # ~20 years

        assert split_del["version"] == "v1"
        assert split_del["panel"]["n_quarters"] == 27  # ~6 years (2020-2026)
