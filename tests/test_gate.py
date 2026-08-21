"""Tests for the dispatch gate, deep queue, and batch pre-registration (Stage G, PLAN.md §5, §5.1).

Done when: dispatching a sixth exploration in a five-per-week period is refused,
not warned about.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import pytest

from src.persistence import Exploration, QueueProposal, store
from src.runner import gate, preregistration, queue
from src.runner.gate import (
    DispatchRateLimitExceededError,
    RateLimitPolicy,
    check_dispatch_allowance,
    enforce_dispatch_gate,
)
from src.runner.spec import ExperimentSpec


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Isolate research store directories for test runs."""
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


class TestDispatchGate:
    def test_dispatch_allowed_when_under_limit(self):
        allowed, count, max_allowed, reason = check_dispatch_allowance("train")
        assert allowed is True
        assert count == 0
        assert max_allowed == 5

        spec = ExperimentSpec(
            hypothesis_id="H001",
            question="Allowed question",
            signal_name="sig_1",
            partition="train",
        )
        # Should not raise
        enforce_dispatch_gate(spec)

    def test_sixth_dispatch_in_five_per_week_period_refused(self):
        """CRITICAL LOAD-BEARING TEST (PLAN.md §9, Stage G).

        Dispatching a sixth exploration in a five-per-week period is refused,
        not warned about.
        """
        now = datetime.now()

        # Seed 5 explorations within the last 3 days
        for i in range(5):
            t = now - timedelta(days=i * 0.5)
            exp_id = f"EXP_{t.strftime('%Y%m%d_%H%M%S')}_{i}"
            exp = Exploration(
                id=exp_id,
                hypothesis_id=f"H00{i+1}",
                spec={"partition": "train", "signal_name": f"sig_{i}"},
                verdict="Tested",
                failure_class="NO_SIGNAL",
                signals_produced=[f"sig_{i}"],
                created_date=t.strftime("%Y-%m-%d"),
            )
            store.save_exploration(exp)

        # 5 explorations recorded
        allowed, count, max_allowed, reason = check_dispatch_allowance("train", as_of=now)
        assert count == 5
        assert max_allowed == 5
        assert allowed is False

        # Sixth exploration must be REFUSED with DispatchRateLimitExceededError
        sixth_spec = ExperimentSpec(
            hypothesis_id="H006",
            question="Sixth exploration question",
            signal_name="sig_6",
            partition="train",
        )
        with pytest.raises(DispatchRateLimitExceededError, match="Dispatch rate limit reached for partition 'train'"):
            enforce_dispatch_gate(sixth_spec, as_of=now)

    def test_old_explorations_do_not_block_new_period(self):
        now = datetime.now()

        # Seed 5 explorations from 10 days ago (outside 7-day window)
        for i in range(5):
            t = now - timedelta(days=10 + i)
            exp_id = f"EXP_{t.strftime('%Y%m%d_%H%M%S')}_{i}"
            exp = Exploration(
                id=exp_id,
                hypothesis_id=f"H00{i+1}",
                spec={"partition": "train", "signal_name": f"sig_{i}"},
                verdict="Tested",
                failure_class="NO_SIGNAL",
                created_date=t.strftime("%Y-%m-%d"),
            )
            store.save_exploration(exp)

        allowed, count, max_allowed, reason = check_dispatch_allowance("train", as_of=now)
        assert allowed is True
        assert count == 0

    def test_validation_and_test_locked_by_default(self):
        val_spec = ExperimentSpec(
            hypothesis_id="H001",
            question="Validation test",
            signal_name="sig_1",
            partition="validation",
        )
        with pytest.raises(DispatchRateLimitExceededError, match="is locked for new dispatches"):
            enforce_dispatch_gate(val_spec)

    def test_forward_lane_unlimited(self):
        fwd_spec = ExperimentSpec(
            hypothesis_id="H001",
            question="Forward lane test",
            signal_name="sig_1",
            partition="forward",
        )
        # Should always be allowed
        allowed, count, max_allowed, _ = check_dispatch_allowance("forward")
        assert allowed is True
        assert max_allowed is None
        enforce_dispatch_gate(fwd_spec)


class TestDeepQueue:
    def test_enqueue_and_rank_proposals(self):
        p1 = queue.enqueue_proposal(
            title="Weak Proposal",
            question="Weak question",
            signal_name="sig_weak",
            hypothesis_id="H001",
            rationale="Small rationale",
            expected_spread_bps=10.0,
        )
        p2 = queue.enqueue_proposal(
            title="Strong Mechanism Proposal",
            question="Strong question",
            signal_name="sig_strong",
            hypothesis_id="H002",
            rationale="Detailed institutional order flow absorption at support levels",
            expected_spread_bps=75.0,
        )

        ranked = queue.rank_queue()
        assert len(ranked) == 2
        # p2 should rank higher than p1
        assert ranked[0].id == p2.id
        assert ranked[0].priority_score > ranked[1].priority_score


class TestBatchPreregistration:
    def test_preregister_batch_freezes_hash(self):
        p1 = queue.enqueue_proposal(
            title="Proposal 1",
            question="Question 1",
            signal_name="sig_1",
            hypothesis_id="H001",
            expected_spread_bps=50.0,
        )
        p2 = queue.enqueue_proposal(
            title="Proposal 2",
            question="Question 2",
            signal_name="sig_2",
            hypothesis_id="H002",
            expected_spread_bps=60.0,
        )

        batch = preregistration.preregister_batch([p1.id, p2.id], partition="train")
        assert batch.batch_id.startswith("BATCH_")
        assert batch.partition == "train"
        assert len(batch.proposal_ids) == 2
        assert len(batch.specs) == 2
        assert len(batch.batch_hash) == 16
        assert batch.status == "preregistered"

        # Verify proposals were updated
        stored_p1 = store.get_proposal(p1.id)
        assert stored_p1.status == "preregistered"
        assert stored_p1.batch_id == batch.batch_id

        # Verify batch is stored and retrievable
        stored_batch = store.get_batch(batch.batch_id)
        assert stored_batch is not None
        assert stored_batch.batch_hash == batch.batch_hash
