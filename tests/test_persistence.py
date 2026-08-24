"""Unit and integration tests for persistence, manifests, idea graph, and sample budget ledger (the refactor plan §3, §5.6, §2.1)."""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from src.persistence import (
    BudgetExhaustedError,
    Edge,
    Evidence,
    Exploration,
    Hypothesis,
    IdeaGraph,
    SampleBudgetLedger,
    Signal,
    build_manifest,
    migration,
    store,
    verify_manifest,
)


class TestModelsAndStore:
    def test_hypothesis_save_and_get(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "HYPOTHESES_DIR", tmp_path / "hypotheses")

        h = Hypothesis(
            id="H999",
            title="Momentum during market troughs",
            statement="High relative strength during drawdowns outperforms.",
            rationale="Institutions accumulate during panics.",
            status="exploring",
            family="resilience",
            edges=[Edge(target_id="H026", relation="specialises")],
            tags=["momentum", "resilience"],
        )
        store.save_hypothesis(h)

        loaded = store.get_hypothesis("H999")
        assert loaded is not None
        assert loaded.id == "H999"
        assert loaded.status == "exploring"
        assert len(loaded.edges) == 1
        assert loaded.edges[0].relation == "specialises"

    def test_signal_and_evidence_lifecycle(self, tmp_path, monkeypatch):
        monkeypatch.setattr(store, "SIGNALS_DIR", tmp_path / "signals")
        monkeypatch.setattr(store, "EVIDENCE_DIR", tmp_path / "evidence")

        sig = Signal(
            name="test_signal_v1",
            owner_hypothesis_id="H999",
            definition="rs_60d_vs_mkt ranked descending",
            coverage_profile={"mean_symbols": 1500},
        )
        store.save_signal(sig)
        loaded_sig = store.get_signal("test_signal_v1")
        assert loaded_sig is not None
        assert loaded_sig.owner_hypothesis_id == "H999"

        ev = Evidence(
            id="EV_001",
            hypothesis_id="H999",
            signal_id="test_signal_v1",
            exploration_id="EXP_001",
            role="exploratory",
            dataset_version="v1",
            partition="train",
            metrics={"mean_ic": 0.045, "q5_minus_q1_pct": 1.25},
            verdict_statement="Supported in training window",
        )
        store.add_evidence(ev)
        loaded_ev = store.get_evidence("EV_001")
        assert loaded_ev is not None
        assert loaded_ev.metrics["mean_ic"] == 0.045


class TestIdeaGraph:
    def test_graph_traversal(self):
        h1 = Hypothesis(id="H101", title="Root", statement="Base idea", rationale="", status="promising")
        h2 = Hypothesis(
            id="H102", title="Branch A", statement="", rationale="",
            edges=[Edge(target_id="H101", relation="specialises")]
        )
        h3 = Hypothesis(
            id="H103", title="Leaf", statement="", rationale="",
            edges=[Edge(target_id="H102", relation="conditions-on")]
        )

        graph = IdeaGraph([h1, h2, h3])

        # Ancestors of H103 should be {H102, H101}
        anc = graph.ancestors("H103")
        assert anc == {"H102", "H101"}

        # Descendants of H101 should be {H102, H103}
        desc = graph.descendants("H101")
        assert desc == {"H102", "H103"}


class TestManifest:
    def test_manifest_building_and_verification(self):
        spec = {"horizon": 10, "signal": "rs_60d"}
        metrics = {"mean_ic": 0.038, "spread_bps": 120}

        m = build_manifest(
            hypothesis_id="H026",
            spec=spec,
            partition="train",
            result_metrics=metrics,
            dataset_version="v1",
            provider_used="codex",
            model_used="gpt-test",
        )

        assert "hash" in m
        assert m["provider_used"] == "codex"
        assert m["model_used"] == "gpt-test"
        assert verify_manifest(m) is True

        # Tampering with metric changes hash and fails verification
        tampered = dict(m)
        tampered["spec"] = {"horizon": 20, "signal": "rs_60d"}
        assert verify_manifest(tampered) is False


class TestSampleBudgetLedger:
    def test_confirmatory_access_blocked_on_burned_quarters(self, tmp_path):
        ledger_path = tmp_path / "ledger.json"
        l = SampleBudgetLedger()

        # Record a confirmatory read on 2021Q1 by family opening_window
        l.record_usage(
            hypothesis_id="H033",
            family="opening_window",
            role="confirmatory",
            partition="test",
            quarters=["2021Q1", "2021Q2"],
            save_after=False,
        )

        # 1. Exploratory read by opening_window is permitted
        ok, _ = l.check_permission("H001", "opening_window", "exploratory", ["2021Q1"])
        assert ok is True

        # 2. Confirmatory read on the burned quarter by opening_window is BLOCKED
        ok, blocked = l.check_permission("H004", "opening_window", "confirmatory", ["2021Q1", "2024Q1"])
        assert ok is False
        assert "2021Q1" in blocked

        # 3. Enforce permission raises BudgetExhaustedError
        with pytest.raises(BudgetExhaustedError, match="BLOCKED"):
            l.enforce_permission("H004", "opening_window", "confirmatory", ["2021Q1"])

        # 4. Unrelated new family reading unburned quarters is permitted
        ok, _ = l.check_permission("H999", "brand_new_idea", "confirmatory", ["2024Q1", "2024Q2"])
        assert ok is True


class TestMigration:
    def test_migrate_all_hypotheses(self, research_store):
        hyps, l = migration.migrate(save_to_store=True)

        # Must have parsed all 38 hypotheses (H001..H038)
        assert len(hyps) >= 38, f"expected >=38 hypotheses, got {len(hyps)}"

        ids = [h.id for h in hyps]
        assert "H001" in ids
        assert "H026" in ids
        assert "H038" in ids
        h050 = next(h for h in hyps if h.id == "H050")
        assert h050.status == "superseded"
        assert Edge(target_id="H049", relation="subsumed-by") in h050.edges

        # Check that stored hypotheses match
        loaded_h026 = store.get_hypothesis("H026")
        assert loaded_h026 is not None
        assert "Relative strength" in loaded_h026.title

        # Check IdeaGraph built from store
        graph = store.get_idea_graph()
        assert len(graph.summary()) > 0
