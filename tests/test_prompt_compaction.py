"""Tests for Suggestion Prompt Compaction and Sub-Linear Scaling (Stage J, PLAN.md §7, §9).

Done when:
Suggestion prompt token count does not grow linearly with store size
(measured over 50 mock experiments).
"""
from __future__ import annotations

import pytest

from src.persistence import Evidence, Exploration, Hypothesis, Signal, store
from src.runner import suggest


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Isolate store directories for prompt compaction testing."""
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


class TestPromptCompaction:
    def test_prompt_size_sublinear_in_store_size(self):
        """CRITICAL LOAD-BEARING TEST (PLAN.md §9, Stage J).

        Suggestion prompt token count does not grow linearly with store size
        (measured over 50 mock experiments).
        """
        # Baseline prompt with 5 experiments
        for i in range(5):
            h = Hypothesis(
                id=f"H00{i+1}",
                title=f"Initial Hypothesis {i+1}",
                statement="Statement",
                rationale="Rationale",
                family="momentum",
                status="proposed" if i % 2 == 0 else "rejected",
            )
            store.save_hypothesis(h)
            ev = Evidence(
                id=f"EV_00{i+1}",
                hypothesis_id=f"H00{i+1}",
                signal_id=f"sig_{i+1}",
                exploration_id=f"EXP_00{i+1}",
                role="exploratory",
                dataset_version="v1",
                partition="train",
                metrics={"mean_ic": 0.02 * (i - 2), "t_stat": 1.5 * (i - 2)},
                verdict_statement="Outcome statement",
            )
            store.add_evidence(ev)

        prompt_small = suggest.build_prompt(n=3)
        tokens_small = len(prompt_small.split())  # approximate token count by word count

        # Scale store up by 10x (50 mock experiments across 5 families)
        families = ["momentum", "breakout", "volume", "reversal", "volatility"]
        for i in range(5, 55):
            fam = families[i % len(families)]
            status = "rejected" if i % 3 != 0 else "proposed"
            h = Hypothesis(
                id=f"H0{i+1:02d}",
                title=f"Scaled Hypothesis {i+1} in {fam}",
                statement=f"Statement for test {i+1}",
                rationale=f"Rationale for mechanism {i+1}",
                family=fam,
                status=status,
            )
            store.save_hypothesis(h)
            ev = Evidence(
                id=f"EV_0{i+1:02d}",
                hypothesis_id=f"H0{i+1:02d}",
                signal_id=f"sig_{i+1}",
                exploration_id=f"EXP_0{i+1:02d}",
                role="exploratory",
                dataset_version="v1",
                partition="train",
                metrics={"mean_ic": 0.01 * (i % 5 - 2), "t_stat": 0.8 * (i % 7 - 3)},
                verdict_statement=f"Verdict for {i+1}",
            )
            store.add_evidence(ev)

        prompt_large = suggest.build_prompt(n=3)
        tokens_large = len(prompt_large.split())

        # A 10x increase in experiments (5 -> 55) must produce sublinear scaling (<2.5x growth)
        # Without compaction, 55 items with full evidence and graveyard would grow 5x-10x.
        growth_ratio = tokens_large / tokens_small
        assert growth_ratio < 2.5, f"Prompt grew linearly: {tokens_small} words -> {tokens_large} words (ratio={growth_ratio:.2f})"

    def test_family_rollups_retain_extremes(self):
        """Compacted evidence retains the most extreme positive and negative signals."""
        h = Hypothesis(
            id="H_ROLLUP",
            title="Rollup Test Hypothesis",
            statement="Statement",
            rationale="Rationale",
            family="breakout",
            status="proposed",
        )
        store.save_hypothesis(h)

        # Seed 20 evidence items in family breakout with extreme t-stats: -5.0 and +6.0
        for i in range(20):
            t_val = -5.0 if i == 0 else (6.0 if i == 19 else float(i - 10) * 0.2)
            ev = Evidence(
                id=f"EV_ROLLUP_{i}",
                hypothesis_id="H_ROLLUP",
                signal_id=f"sig_break_{i}",
                exploration_id=f"EXP_ROLLUP_{i}",
                role="exploratory",
                dataset_version="v1",
                partition="train",
                metrics={"mean_ic": 0.02 * (i - 10), "t_stat": t_val},
                verdict_statement=f"Outcome for sig_break_{i}",
            )
            store.add_evidence(ev)

        context = suggest._evidence_context()
        assert "[Evidence Compacted:" in context
        assert "Family 'breakout'" in context
        # Extremes must be present in the retained lines
        assert "sig_break_0" in context
        assert "sig_break_19" in context

    def test_graveyard_compacts_past_threshold(self):
        """Graveyard compacts into family breakdown past 15 dead hypotheses."""
        for i in range(20):
            h = Hypothesis(
                id=f"H_DEAD_{i}",
                title=f"Dead Idea {i}",
                statement="Statement",
                rationale=f"Failed reason {i}",
                family="reversal" if i % 2 == 0 else "momentum",
                status="rejected",
            )
            store.save_hypothesis(h)

        _, graveyard = suggest._ledger_context()
        assert "[Graveyard Summary: 20 dead hypotheses" in graveyard
        assert "Family 'reversal'" in graveyard
        assert "Family 'momentum'" in graveyard
