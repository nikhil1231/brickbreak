"""Tests for Batch Correction and Unified Counting Invariants (Stage H, PLAN.md §4, §9).

Done when:
count_tests and partition_summary cannot disagree — enforced by test,
not by review.
"""
from __future__ import annotations

import pytest

from src.persistence import (
    BatchManifest,
    Evidence,
    Exploration,
    Hypothesis,
    store,
)
from src.runner import burden, preregistration
from src.runner.spec import ExperimentSpec


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Isolate store directories for burden accounting tests."""
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


class TestBatchCorrectionAndUnifiedCounting:
    def test_count_tests_and_partition_summary_cannot_disagree(self):
        """CRITICAL LOAD-BEARING INVARIANT (PLAN.md §4, Stage H).

        Two counters of the same quantity will drift apart. Any second count
        derives directly from the first.
        """
        # Test on empty store
        assert burden.count_tests("train") == 0
        assert burden.partition_summary("train")["n_tests"] == 0

        # Seed explorations:
        # Exp 1: H001, sig_a on train, with evidence
        exp1 = Exploration(
            id="EXP_20260101_000001",
            hypothesis_id="H001",
            spec={"partition": "train", "signal_name": "sig_a"},
            verdict="Tested",
            failure_class="SUCCESS",
        )
        store.save_exploration(exp1)
        ev1 = Evidence(
            id="EV_EXP_20260101_000001",
            hypothesis_id="H001",
            signal_id="sig_a",
            exploration_id="EXP_20260101_000001",
            role="exploratory",
            dataset_version="v1",
            partition="train",
            metrics={"t_stat": 3.45},
            verdict_statement="Positive",
        )
        store.add_evidence(ev1)

        # Exp 2: H002, sig_b on train, without evidence
        exp2 = Exploration(
            id="EXP_20260101_000002",
            hypothesis_id="H002",
            spec={"partition": "train", "signal_name": "sig_b"},
            verdict="Tested",
            failure_class="NO_SIGNAL",
        )
        store.save_exploration(exp2)

        # Exp 3: Re-run of H001, sig_a on train (should supersede, not duplicate)
        exp3 = Exploration(
            id="EXP_20260101_000003",
            hypothesis_id="H001",
            spec={"partition": "train", "signal_name": "sig_a"},
            verdict="Retested",
            failure_class="SUCCESS",
        )
        store.save_exploration(exp3)
        ev3 = Evidence(
            id="EV_EXP_20260101_000003",
            hypothesis_id="H001",
            signal_id="sig_a",
            exploration_id="EXP_20260101_000003",
            role="exploratory",
            dataset_version="v1",
            partition="train",
            metrics={"t_stat": 3.60},
            verdict_statement="Positive retest",
        )
        store.add_evidence(ev3)

        # Exp 4: Exploration on validation (different partition)
        exp4 = Exploration(
            id="EXP_20260101_000004",
            hypothesis_id="H003",
            spec={"partition": "validation", "signal_name": "sig_c"},
            verdict="Tested",
            failure_class="NO_SIGNAL",
        )
        store.save_exploration(exp4)

        # Exp 5: Voided exploration on train (must be excluded)
        exp5 = Exploration(
            id="EXP_20260101_000005",
            hypothesis_id="H004",
            spec={"partition": "train", "signal_name": "sig_d"},
            verdict="Tested",
            failure_class="NO_SIGNAL",
            voided_reason="Defective normalization",
            voided_date="2026-01-02",
        )
        store.save_exploration(exp5)

        # Assert count_tests and partition_summary MUST agree perfectly
        train_count = burden.count_tests("train")
        train_summary = burden.partition_summary("train")
        assert train_count == train_summary["n_tests"]
        assert train_count == 2  # H001/sig_a and H002/sig_b (re-run deduplicated, voided excluded)

        val_count = burden.count_tests("validation")
        val_summary = burden.partition_summary("validation")
        assert val_count == val_summary["n_tests"]
        assert val_count == 1

        test_count = burden.count_tests("test")
        test_summary = burden.partition_summary("test")
        assert test_count == test_summary["n_tests"]
        assert test_count == 0

    def test_batch_level_multiplicity_correction(self):
        """Batch pre-registration allows FDR correction across the frozen batch."""
        # Create a batch of 4 specs
        specs = [
            {"hypothesis_id": "H010", "signal_name": "sig_alpha", "partition": "train"},
            {"hypothesis_id": "H011", "signal_name": "sig_beta", "partition": "train"},
            {"hypothesis_id": "H012", "signal_name": "sig_gamma", "partition": "train"},
            {"hypothesis_id": "H013", "signal_name": "sig_delta", "partition": "train"},
        ]
        batch = BatchManifest(
            batch_id="BATCH_20260821_TEST",
            partition="train",
            proposal_ids=["P010", "P011", "P012", "P013"],
            specs=specs,
            batch_hash="abcdef0123456789",
        )
        store.save_batch(batch)

        # Attach exploration and evidence results:
        # sig_alpha: t = 3.50 (strong hit)
        exp_a = Exploration(id="EXP_A", hypothesis_id="H010", spec=specs[0], verdict="A", failure_class="SUCCESS")
        store.save_exploration(exp_a)
        store.add_evidence(Evidence(
            id="EV_A", hypothesis_id="H010", signal_id="sig_alpha", exploration_id="EXP_A",
            role="exploratory", dataset_version="v1", partition="train", metrics={"t_stat": 3.50},
            verdict_statement="Hit",
        ))

        # sig_beta: t = 2.40 (moderate hit)
        exp_b = Exploration(id="EXP_B", hypothesis_id="H011", spec=specs[1], verdict="B", failure_class="SUCCESS")
        store.save_exploration(exp_b)
        store.add_evidence(Evidence(
            id="EV_B", hypothesis_id="H011", signal_id="sig_beta", exploration_id="EXP_B",
            role="exploratory", dataset_version="v1", partition="train", metrics={"t_stat": 2.40},
            verdict_statement="Hit",
        ))

        # sig_gamma: t = 0.20 (null)
        exp_c = Exploration(id="EXP_C", hypothesis_id="H012", spec=specs[2], verdict="C", failure_class="NO_SIGNAL")
        store.save_exploration(exp_c)
        store.add_evidence(Evidence(
            id="EV_C", hypothesis_id="H012", signal_id="sig_gamma", exploration_id="EXP_C",
            role="exploratory", dataset_version="v1", partition="train", metrics={"t_stat": 0.20},
            verdict_statement="Null",
        ))

        # sig_delta: t = -0.10 (null)
        exp_d = Exploration(id="EXP_D", hypothesis_id="H013", spec=specs[3], verdict="D", failure_class="NO_SIGNAL")
        store.save_exploration(exp_d)
        store.add_evidence(Evidence(
            id="EV_D", hypothesis_id="H013", signal_id="sig_delta", exploration_id="EXP_D",
            role="exploratory", dataset_version="v1", partition="train", metrics={"t_stat": -0.10},
            verdict_statement="Null",
        ))

        res = burden.assess_batch(batch.batch_id, q=0.10)
        assert res["batch_id"] == batch.batch_id
        assert res["batch_size"] == 4
        assert res["batch_sidak_bar"] > 2.0  # 4-test Sidak bar ~2.50
        assert res["n_surviving_fdr"] == 2  # sig_alpha and sig_beta survive FDR at q=0.10

        # sig_alpha should clear both batch Sidak and FDR
        alpha_res = next(r for r in res["results"] if r["signal"] == "sig_alpha")
        assert alpha_res["survives_fdr"] is True
        assert alpha_res["clears_batch_sidak"] is True

        # sig_gamma should fail both
        gamma_res = next(r for r in res["results"] if r["signal"] == "sig_gamma")
        assert gamma_res["survives_fdr"] is False
        assert gamma_res["clears_batch_sidak"] is False
