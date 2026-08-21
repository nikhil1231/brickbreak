"""Tests for the research inbox (the refactor plan §6, "Research inbox").

The thing worth testing here is not that a model returns text. It is that the
lab's own rules survive contact with what a model returns: a bar that cannot
fail is replaced, lineage pointing at nothing is dropped, a restatement of an
existing hypothesis is flagged, and pressing play registers a hypothesis
before anything is spent.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.persistence import store
from src.persistence.models import Hypothesis, Suggestion
from src.runner import agent, suggest


@pytest.fixture
def isolated_store(research_store):
    """The shared tmp store, seeded with the hypothesis these tests assume."""
    store.save_hypothesis(Hypothesis(
        id="H001", title="Enter at 09:20 at the close of the opening window",
        statement="Buying candidates at 09:20 beats the market",
        rationale="", status="rejected", family="opening_window"))
    return research_store


def _reply(payload) -> agent.AgentResult:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return agent.AgentResult(ok=True, text=text, returncode=0, duration_s=0.1)


ONE_GOOD = {
    "title": "Delivery share rising through a contraction predicts the break",
    "question": "Do names whose 20-day delivery percentage rises while range "
                "contracts outperform over 10 sessions?",
    "rationale": "Accumulation by holders who do not sell into the next print.",
    "signal_name": "deliv_trend_in_contraction",
    "signal_sketch": "20-day slope of deliv_pct, ranked within contraction_steps.",
    "family": "accumulation",
    "lineage": [{"target_id": "H001", "relation": "adjacent-to"}],
    "novelty_note": "Delivery has never been scored here.",
    "evidence_basis": "The catalogue lists deliv_pct; no signal uses it.",
    "horizons": [5, 10, 20],
    "primary_horizon": 10,
    "pass_criterion": {"min_mean_ic": 0.02, "min_spread_bps": 40.0},
    "falsification_condition": "IC indistinguishable from zero after the "
                               "overlap correction",
}


class TestCoercion:
    def test_keeps_a_well_formed_suggestion_intact(self, isolated_store):
        sug = suggest.coerce(ONE_GOOD, slot=0, source="claude")
        assert sug.signal_name == "deliv_trend_in_contraction"
        assert sug.pass_criterion == {"min_mean_ic": 0.02, "min_spread_bps": 40.0}
        assert sug.lineage == [{"target_id": "H001", "relation": "adjacent-to"}]
        assert sug.warnings == []

    def test_a_bar_that_cannot_fail_is_replaced_and_said_so(self, isolated_store):
        data = dict(ONE_GOOD, pass_criterion={"min_spread_bps": 0.0})
        sug = suggest.coerce(data, slot=0, source="claude")
        assert sug.pass_criterion == suggest.DEFAULT_BAR
        assert any("sign test" in w or "replaced with the lab default" in w
                   for w in sug.warnings)

    def test_a_bar_inside_transaction_costs_is_replaced(self, isolated_store):
        data = dict(ONE_GOOD, pass_criterion={"min_spread_bps": 2.0})
        sug = suggest.coerce(data, slot=0, source="claude")
        assert sug.pass_criterion == suggest.DEFAULT_BAR

    def test_lineage_to_an_unknown_hypothesis_is_dropped(self, isolated_store):
        data = dict(ONE_GOOD,
                    lineage=[{"target_id": "H999", "relation": "specialises"},
                             {"target_id": "H001", "relation": "nonsense"}])
        sug = suggest.coerce(data, slot=0, source="claude")
        assert sug.lineage == []
        assert len(sug.warnings) == 2

    def test_a_restatement_of_an_existing_hypothesis_is_flagged(self, isolated_store):
        data = dict(ONE_GOOD,
                    title="Enter at 09:20 at the close of the opening window",
                    question="Buying candidates at 09:20 beats the market")
        sug = suggest.coerce(data, slot=0, source="claude")
        assert any("restatement of H001" in w for w in sug.warnings)

    def test_a_signal_name_already_scored_is_flagged(self, isolated_store):
        from src.persistence.models import Signal
        store.save_signal(Signal(name="deliv_trend_in_contraction",
                                 owner_hypothesis_id="H001", definition="x"))
        sug = suggest.coerce(ONE_GOOD, slot=0, source="claude")
        assert any("already been scored" in w for w in sug.warnings)

    def test_a_suggestion_with_no_question_is_rejected(self, isolated_store):
        with pytest.raises(ValueError):
            suggest.coerce({"rationale": "nothing else"}, slot=0, source="claude")


class TestGeneration:
    def test_parses_a_json_array_wrapped_in_prose(self, isolated_store):
        out = suggest.generate(
            1, agent_fn=lambda p: _reply(
                "Here you go:\n" + json.dumps([ONE_GOOD]) + "\nHope that helps."))
        assert len(out) == 1
        assert out[0].title == ONE_GOOD["title"]
        assert store.get_suggestion(out[0].id) is not None

    def test_the_prompt_carries_the_ledger_and_the_columns(self, isolated_store):
        seen = {}

        def capture(prompt):
            seen["prompt"] = prompt
            return _reply([ONE_GOOD])

        suggest.generate(1, agent_fn=capture)
        assert "H001" in seen["prompt"]
        assert "deliv_pct" in seen["prompt"]
        assert "0.40% round trip" in seen["prompt"]

    def test_a_repeated_proposal_is_flagged_rather_than_prompted_against(
            self, isolated_store):
        """The inbox is caught on the way out, not carried in the prompt.

        Showing the generator every proposal ever made grew without bound and
        bought nothing this check does not, so the prompt no longer carries
        them — but proposing the same thing twice must still not pass silently.
        """
        suggest.generate(1, agent_fn=lambda p: _reply([ONE_GOOD]))
        seen = {}

        def capture(prompt):
            seen["prompt"] = prompt
            return _reply([ONE_GOOD])

        again = suggest.generate(1, slots=[1], agent_fn=capture)[0]

        assert ONE_GOOD["title"] not in seen["prompt"]
        assert any("restatement" in w for w in again.warnings), again.warnings

    def test_the_static_half_of_the_prompt_is_stable_across_calls(
            self, isolated_store):
        """Everything above the ledger must be byte-identical to cache.

        The column catalogue is ~3k tokens and does not change; it sits in the
        prefix so a run does not pay for it. Anything volatile moving above
        the ledger heading — including the requested count — silently costs
        that back on every call.
        """
        prefix_of = lambda n: suggest.build_prompt(n).split("# The ledger")[0]
        assert prefix_of(3) == prefix_of(5)
        assert "deliv_pct" in prefix_of(3)

    def test_a_failed_call_falls_back_and_says_so(self, isolated_store):
        out = suggest.generate(
            2, agent_fn=lambda p: agent.AgentResult(
                ok=False, text="", returncode=1, duration_s=0.0,
                stderr="rate limited"))
        assert len(out) == 2
        assert all(s.source == "offline" for s in out)
        assert all(any("rate limited" in w for w in s.warnings) for s in out)

    def test_unparseable_output_falls_back_rather_than_raising(self, isolated_store):
        out = suggest.generate(1, agent_fn=lambda p: _reply("no json here"))
        assert len(out) == 1 and out[0].source == "offline"

    def test_a_short_batch_is_topped_up_mechanically(self, isolated_store):
        out = suggest.generate(3, agent_fn=lambda p: _reply([ONE_GOOD]))
        assert len(out) == 3
        assert out[0].source == "claude"
        assert [s.slot for s in out] == [0, 1, 2]
        assert all(s.source == "offline" for s in out[1:])

    def test_ids_within_one_batch_are_distinct(self, isolated_store):
        out = suggest.generate(
            3, agent_fn=lambda p: _reply([ONE_GOOD, dict(ONE_GOOD, title="B"),
                                          dict(ONE_GOOD, title="C")]))
        assert len({s.id for s in out}) == 3

    def test_generating_into_an_occupied_slot_retires_its_occupant(self, isolated_store):
        first = suggest.generate(1, agent_fn=lambda p: _reply([ONE_GOOD]))[0]
        suggest.generate(1, slots=[0],
                         agent_fn=lambda p: _reply([dict(ONE_GOOD, title="B")]))
        assert store.get_suggestion(first.id).status == "replaced"
        assert len(suggest.open_suggestions()) == 1


class TestRefresh:
    def test_refresh_replaces_one_slot_and_leaves_the_others(self, isolated_store):
        batch = suggest.generate(
            3, agent_fn=lambda p: _reply(
                [ONE_GOOD, dict(ONE_GOOD, title="B", signal_name="b"),
                 dict(ONE_GOOD, title="C", signal_name="c")]))
        target = batch[1]
        new = suggest.refresh(
            target.id, agent_fn=lambda p: _reply([dict(ONE_GOOD, title="D",
                                                       signal_name="d")]))
        assert new.slot == target.slot
        assert new.replaces == target.id
        assert store.get_suggestion(target.id).status == "replaced"
        open_now = suggest.open_suggestions()
        assert [s.slot for s in open_now] == [0, 1, 2]
        assert {s.title for s in open_now} == {ONE_GOOD["title"], "D", "C"}

    def test_a_replaced_suggestion_is_kept_and_comes_back_flagged(
            self, isolated_store):
        """Refreshing a slot must not launder the idea it displaced."""
        first = suggest.generate(1, agent_fn=lambda p: _reply([ONE_GOOD]))[0]

        # The generator hands back exactly what was just replaced.
        again = suggest.refresh(first.id, agent_fn=lambda p: _reply([ONE_GOOD]))

        assert store.get_suggestion(first.id).status == "replaced"
        assert any("restatement" in w for w in again.warnings), again.warnings

    def test_refreshing_something_already_launched_is_refused(self, isolated_store):
        sug = suggest.generate(1, agent_fn=lambda p: _reply([ONE_GOOD]))[0]
        suggest.promote(sug.id)
        with pytest.raises(ValueError):
            suggest.refresh(sug.id, agent_fn=lambda p: _reply([ONE_GOOD]))

    def test_an_unknown_id_raises(self, isolated_store):
        with pytest.raises(KeyError):
            suggest.refresh("S999", agent_fn=lambda p: _reply([ONE_GOOD]))


class TestPromotion:
    def test_promotion_registers_a_hypothesis_with_its_lineage(self, isolated_store):
        sug = suggest.generate(1, agent_fn=lambda p: _reply([ONE_GOOD]))[0]
        promoted, hyp = suggest.promote(sug.id)

        assert hyp.id == "H002"                      # H001 is the only prior
        assert store.get_hypothesis("H002") is not None
        assert hyp.status == "proposed"
        assert hyp.family == "accumulation"
        assert [(e.target_id, e.relation) for e in hyp.edges] == [
            ("H001", "adjacent-to")]
        assert promoted.status == "launched"
        assert promoted.hypothesis_id == "H002"
        assert sug.id in " ".join(hyp.tags)

    def test_promotion_is_idempotent(self, isolated_store):
        sug = suggest.generate(1, agent_fn=lambda p: _reply([ONE_GOOD]))[0]
        _, first = suggest.promote(sug.id)
        _, second = suggest.promote(sug.id)
        assert first.id == second.id
        assert len(store.list_hypotheses()) == 2

    def test_a_promoted_suggestion_leaves_the_inbox(self, isolated_store):
        sug = suggest.generate(1, agent_fn=lambda p: _reply([ONE_GOOD]))[0]
        suggest.promote(sug.id)
        assert suggest.open_suggestions() == []


class TestOfflinePath:
    def test_it_follows_up_a_recorded_failure_rather_than_inventing(self, isolated_store):
        from src.persistence.models import Exploration
        store.save_exploration(Exploration(
            id="EXP_1", hypothesis_id="H001",
            spec={"signal_name": "opening_demand"},
            verdict="raw IC collapsed under neutralisation",
            failure_class="SIGNAL_BUT_BETA",
            signals_produced=["opening_demand"]))

        out = suggest.offline_suggestions(1)
        assert len(out) == 1
        assert "opening_demand" in out[0].title
        assert out[0].lineage == [{"target_id": "H001", "relation": "specialises"}]
        assert "EXP_1" in out[0].evidence_basis
        assert any("mechanical" in w for w in out[0].warnings)

    def test_coverage_probes_skip_columns_that_cannot_rank_a_cross_section(self):
        # A price level ranks by share price; a market-wide series is constant
        # within a session. Neither can rank anything.
        assert not suggest._rankable("ema_fast")
        assert not suggest._rankable("mkt_ret_5d")
        assert suggest._rankable("deliv_pct")
        assert suggest._rankable("atr_ratio")

    def test_it_returns_fewer_rather_than_inventing_filler(self, isolated_store,
                                                           monkeypatch):
        monkeypatch.setattr(suggest, "_rankable", lambda name: False)
        assert suggest.offline_suggestions(3) == []

    def test_no_cli_installed_still_produces_something_labelled(self, isolated_store,
                                                               monkeypatch):
        monkeypatch.setattr(agent, "available", lambda *a, **k: False)
        out = suggest.generate(2)
        assert len(out) == 2
        assert all(s.source == "offline" for s in out)
        assert all("CLI not installed" in " ".join(s.warnings) for s in out)


class TestSuggestionAPI:
    """The endpoints the Explore tab reads, over a live server."""

    @pytest.fixture
    def server(self, isolated_store, monkeypatch):
        import urllib.request
        from src.interface import backend
        srv, _ = backend.serve_backend(port=0, block=False)
        yield srv, backend, urllib.request
        srv.shutdown()

    def _get(self, urllib_request, srv, path):
        with urllib_request.urlopen(
                f"http://127.0.0.1:{srv.server_address[1]}{path}") as res:
            return json.loads(res.read().decode())

    def _post(self, urllib_request, srv, path, body):
        req = urllib_request.Request(
            f"http://127.0.0.1:{srv.server_address[1]}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib_request.urlopen(req) as res:
            return json.loads(res.read().decode())

    def test_get_is_read_only_and_does_not_generate(self, server, monkeypatch):
        srv, backend, urllib_request = server
        monkeypatch.setattr(suggest, "generate",
                            lambda *a, **k: pytest.fail("GET generated"))
        payload = self._get(urllib_request, srv, "/api/suggestions")
        assert payload == {"suggestions": [], "n_open": 0, "n_slots": 3,
                           "n_proposed_ever": 0}

    def test_generate_then_read_back(self, server, monkeypatch):
        srv, backend, urllib_request = server
        monkeypatch.setattr(
            suggest, "generate",
            lambda n, slots=None, **k: suggest._persist([
                Suggestion(id=f"S{i + 1:03d}", title=f"T{i}",
                           question=f"Q{i}", slot=i) for i in range(n)]))
        made = self._post(urllib_request, srv, "/api/suggestions/generate",
                          {"count": 3, "provider": "claude"})
        assert made["n_open"] == 3
        assert self._get(urllib_request, srv, "/api/suggestions") == made

    def test_promote_registers_and_empties_the_slot(self, server):
        srv, backend, urllib_request = server
        sug = suggest.generate(1, agent_fn=lambda p: _reply([ONE_GOOD]))[0]

        payload = self._post(urllib_request, srv, "/api/suggestions/promote",
                             {"id": sug.id})

        assert payload["hypothesis_id"] == "H002"
        assert payload["promoted"]["status"] == "launched"
        assert payload["n_open"] == 0          # the slot is free to refill
        assert store.get_hypothesis("H002") is not None

    def test_refilling_a_slot_cannot_retire_the_suggestion_being_launched(
            self, server, monkeypatch):
        """The reason promotion is its own step.

        `generate` retires whatever is still `open` in the slot it writes to.
        If the inbox refilled before the promotion landed, the suggestion the
        run was launched from would be marked `replaced` — a launched idea
        recorded as discarded.
        """
        srv, backend, urllib_request = server
        sug = suggest.generate(1, agent_fn=lambda p: _reply([ONE_GOOD]))[0]

        self._post(urllib_request, srv, "/api/suggestions/promote", {"id": sug.id})
        suggest.generate(1, slots=[sug.slot],
                         agent_fn=lambda p: _reply([dict(ONE_GOOD, title="next",
                                                         signal_name="n")]))

        assert store.get_suggestion(sug.id).status == "launched"
        assert [s.title for s in suggest.open_suggestions()] == ["next"]

    def test_promote_of_an_unknown_id_is_a_404(self, server):
        import urllib.error
        srv, backend, urllib_request = server
        with pytest.raises(urllib.error.HTTPError) as exc:
            self._post(urllib_request, srv, "/api/suggestions/promote",
                       {"id": "S999"})
        assert exc.value.code == 404

    def test_a_generated_batch_records_what_it_cost(self, isolated_store):
        priced = agent.AgentResult(ok=True, text=json.dumps([ONE_GOOD, ONE_GOOD]),
                                   returncode=0, duration_s=1.0, num_turns=4,
                                   cost_usd=0.40)
        out = suggest.generate(2, agent_fn=lambda p: priced)
        # One call, two suggestions: the cost is shared, not double-counted.
        assert [s.cost_usd for s in out] == [0.20, 0.20]
        assert all(s.turns == 4 for s in out)

    def test_refresh_of_an_unknown_id_is_a_404(self, server):
        import urllib.error
        srv, backend, urllib_request = server
        with pytest.raises(urllib.error.HTTPError) as exc:
            self._post(urllib_request, srv, "/api/suggestions/refresh",
                       {"id": "S999", "provider": "claude"})
        assert exc.value.code == 404

    def test_explore_promotes_the_suggestion_before_dispatching(self, server,
                                                                monkeypatch,
                                                                tmp_path):
        srv, backend, urllib_request = server
        sug = suggest.generate(1, agent_fn=lambda p: _reply([ONE_GOOD]))[0]

        result_path = tmp_path / "result.json"
        result_path.write_text(json.dumps({"job_id": "J1", "hypothesis_id": "H002",
                                           "failure_class": "NO_SIGNAL",
                                           "interpretation": "x"}))
        captured = {}

        def fake_run_job(exp_spec, provider, model):
            captured["spec"] = exp_spec
            return SimpleNamespace(state="succeeded", id="J1", error="",
                                   result_path=str(result_path))

        monkeypatch.setattr(backend.agent, "available", lambda provider: True)
        monkeypatch.setattr(backend.job, "run_job", fake_run_job)

        self._post(urllib_request, srv, "/api/explore",
                   {"suggestion_id": sug.id, "provider": "claude",
                    "partition": "train"})

        # The hypothesis exists before the job runs, and the spec carries the
        # suggestion's own bar rather than the generic default.
        assert captured["spec"].hypothesis_id == "H002"
        assert store.get_hypothesis("H002") is not None
        assert captured["spec"].signal_name == ONE_GOOD["signal_name"]
        assert captured["spec"].pass_criterion == ONE_GOOD["pass_criterion"]
        assert store.get_suggestion(sug.id).status == "launched"
