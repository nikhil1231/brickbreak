"""The decision layer: the seal, the contract, and the commit.

Three things are checked here and each of them is load-bearing.

**The seal.** A judge with tools is a judge that can read the outcome it is
being scored on. `runner.agent.run_agent` defaults to Read/Write/Edit/Bash/
Glob/Grep because it exists to author signals; the decision path must hand it
an empty tool list and an empty directory, and that must be asserted rather
than intended.

**The contract.** Exactly one decision per case, in order, whatever happened.
An arm that drops its failures is scored on an easier population than the
baselines, which see every case.

**The commit.** A decision's hash covers the verdict and not its provenance,
so a reload is the same commitment while a changed verdict is not.
"""
from __future__ import annotations

import json

import pytest

from src.discretionary import decider, prompt as prompt_mod
from src.discretionary.case import Case
from src.discretionary.decision import (Decision, DecisionError, commit_hash,
                                        from_jsonl, to_jsonl)
from src.discretionary.providers import cli as cli_provider


def _case(i: int = 0) -> Case:
    return Case(case_id=f"C{i:03d}", symbol="AAA", date="2022-06-01",
                anonymised=True, generator_score=0.0, generator_reason="fixture",
                blocks={"market": {"mkt_regime": "chop"}})


GOOD_PAYLOAD = {
    "facts": ["the last close is 104"], "unusual": "nothing unusual",
    "inference": "possible two-sided disagreement", "speculation": "",
    "market_and_sector": "market is choppy", "thesis": "no thesis",
    "competing_explanation": "the move is noise", "invalidation": "a close below 100",
    "asymmetry": "roughly symmetric", "analogue_read": "none supplied",
    "action": "SKIP", "confidence": 0.35, "tags": ["no_edge_visible"],
    "rationale": "Nothing here is unusual. Skipping is free.",
}


# --------------------------------------------------------------------------
# the seal
# --------------------------------------------------------------------------

def test_the_cli_decider_is_given_no_tools_and_an_empty_directory(monkeypatch):
    """A judge that can run Bash can read the parquet it is being scored on.

    It would not have to intend anything: a model asked to reason about a stock
    will reasonably reach for the data when the data is reachable.
    """
    seen = {}

    def fake_run_agent(text, cwd, **kw):
        seen["tools"] = kw.get("allowed_tools")
        seen["cwd"] = cwd
        seen["dir_contents"] = list(cwd.iterdir())
        seen["max_turns"] = kw.get("max_turns")
        return type("R", (), {"ok": True, "text": json.dumps(GOOD_PAYLOAD),
                              "stderr": ""})()

    monkeypatch.setattr(cli_provider.agent, "run_agent", fake_run_agent)
    cli_provider.decide_one(_case())

    assert seen["tools"] == (), "the decider was given tools"
    assert seen["dir_contents"] == [], "the decider's directory was not empty"
    assert seen["max_turns"] == 1


def test_the_case_travels_in_the_prompt_not_on_disk(monkeypatch):
    """Nothing is written for a tool to find, so the seal has nothing to leak."""
    captured = {}

    def fake_run_agent(text, cwd, **kw):
        captured["text"] = text
        return type("R", (), {"ok": True, "text": json.dumps(GOOD_PAYLOAD),
                              "stderr": ""})()

    monkeypatch.setattr(cli_provider.agent, "run_agent", fake_run_agent)
    c = _case()
    cli_provider.decide_one(c)
    assert "mkt_regime: chop" in captured["text"]
    assert prompt_mod.SYSTEM_PROMPT in captured["text"]


# --------------------------------------------------------------------------
# the contract
# --------------------------------------------------------------------------

def test_a_failed_call_still_produces_a_decision(monkeypatch):
    """A hole in the case set is not neutral.

    Baselines see every case. An AI arm that dropped its failures would be
    scored on a different and easier population, and the difference would look
    exactly like skill.
    """
    monkeypatch.setattr(
        cli_provider.agent, "run_agent",
        lambda text, cwd, **kw: type("R", (), {
            "ok": False, "text": "", "stderr": "boom"})())
    d = cli_provider.decide_one(_case())
    assert d.action == "SKIP" and d.confidence == 0.0
    assert "boom" in d.error


def test_unparseable_output_is_recorded_not_raised(monkeypatch):
    monkeypatch.setattr(
        cli_provider.agent, "run_agent",
        lambda text, cwd, **kw: type("R", (), {
            "ok": True, "text": "I think you should buy it!", "stderr": ""})())
    d = cli_provider.decide_one(_case())
    assert d.action == "SKIP" and "unparseable" in d.error


def test_json_wrapped_in_prose_is_still_recovered(monkeypatch):
    """The CLI has no output_config, so it is asked for JSON in words."""
    monkeypatch.setattr(
        cli_provider.agent, "run_agent",
        lambda text, cwd, **kw: type("R", (), {
            "ok": True, "stderr": "",
            "text": "Here is my decision:\n```json\n"
                    + json.dumps(GOOD_PAYLOAD) + "\n```\nHope that helps."})())
    d = cli_provider.decide_one(_case())
    assert d.action == "SKIP" and d.confidence == 0.35
    assert d.tags == ["no_edge_visible"] and not d.error


def test_a_tag_outside_the_vocabulary_is_dropped(monkeypatch):
    """Free-text tags would silently create a new group in the §8 analysis."""
    payload = dict(GOOD_PAYLOAD, tags=["chart_structure", "vibes", "moon"])
    monkeypatch.setattr(
        cli_provider.agent, "run_agent",
        lambda text, cwd, **kw: type("R", (), {
            "ok": True, "text": json.dumps(payload), "stderr": ""})())
    assert cli_provider.decide_one(_case()).tags == ["chart_structure"]


def test_a_single_fact_returned_as_a_string_is_not_iterated(monkeypatch):
    """`[str(x) for x in "Over the..."]` yields ['O', 'v', 'e', ...].

    A silent corruption that looks like a populated list, survives every
    well-formed fixture, and showed up on the first live call — a real model
    returned `facts` as one bare string. Found by running a case for real,
    which is why the fixtures alone were not enough.
    """
    payload = dict(GOOD_PAYLOAD, facts="Over the window the close fell 4%.")
    monkeypatch.setattr(
        cli_provider.agent, "run_agent",
        lambda text, cwd, **kw: type("R", (), {
            "ok": True, "text": json.dumps(payload), "stderr": ""})())
    d = cli_provider.decide_one(_case())
    assert d.facts == ["Over the window the close fell 4%."]


def test_both_providers_share_one_payload_parser():
    """Two copies of the coercion rules drift, and that is where the bugs are."""
    from src.discretionary.providers import api as api_provider
    assert "from_payload" in api_provider.__dict__
    assert "from_payload" in cli_provider.__dict__


def test_every_case_gets_exactly_one_decision_in_order(monkeypatch):
    monkeypatch.setattr(
        cli_provider.agent, "run_agent",
        lambda text, cwd, **kw: type("R", (), {
            "ok": True, "text": json.dumps(GOOD_PAYLOAD), "stderr": ""})())
    cases = [_case(i) for i in range(5)]
    out = decider.decide(cases, provider="cli")
    assert [d.case_id for d in out] == [c.case_id for c in cases]


def test_a_provider_returning_the_wrong_count_is_refused(monkeypatch):
    monkeypatch.setattr(cli_provider, "decide",
                        lambda cases, **kw: [Decision(
                            case_id="C000", replay_id="R", decider="ai",
                            action="SKIP", confidence=0.0)])
    with pytest.raises(decider.DeciderError, match="must get one"):
        decider.decide([_case(0), _case(1)], provider="cli")


def test_failure_summary_reports_what_is_real(monkeypatch):
    ds = [Decision(case_id=f"C{i}", replay_id="R", decider="ai", action="SKIP",
                   confidence=0.0, error="boom: x" if i < 2 else "")
          for i in range(10)]
    s = decider.failure_summary(ds)
    assert s["n"] == 10 and s["n_failed"] == 2 and s["failed_pct"] == 20.0
    assert s["by_kind"] == {"boom": 2}


# --------------------------------------------------------------------------
# the commit
# --------------------------------------------------------------------------

def test_the_commit_hash_covers_the_verdict_not_its_provenance():
    """A reload is the same commitment; a changed verdict is not."""
    a = Decision(case_id="C1", replay_id="R", decider="ai", action="TAKE",
                 confidence=0.6, case_hash="abc", decided_at="2026-01-01 00:00:00",
                 input_tokens=100)
    b = Decision(case_id="C1", replay_id="R", decider="ai", action="TAKE",
                 confidence=0.6, case_hash="abc", decided_at="2026-06-06 12:00:00",
                 input_tokens=999)
    assert commit_hash([a]) == commit_hash([b])

    changed = Decision(case_id="C1", replay_id="R", decider="ai", action="SKIP",
                       confidence=0.6, case_hash="abc")
    assert commit_hash([a]) != commit_hash([changed])


def test_the_commit_hash_is_order_independent():
    """Two arms written in either order are the same commitment."""
    ds = [Decision(case_id=f"C{i}", replay_id="R", decider="ai",
                   action="TAKE", confidence=0.5) for i in range(4)]
    assert commit_hash(ds) == commit_hash(list(reversed(ds)))


def test_decisions_survive_a_jsonl_round_trip():
    ds = [Decision(case_id="C1", replay_id="R", decider="ai", action="WATCH",
                   confidence=0.5, tags=["extension"], facts=["a", "b"])]
    back = from_jsonl(to_jsonl(ds))
    assert commit_hash(back) == commit_hash(ds)
    assert back[0].tags == ["extension"] and back[0].facts == ["a", "b"]


def test_watch_is_not_a_position():
    """Folding WATCH into TAKE would inflate the take rate with non-positions."""
    assert Decision(case_id="C", replay_id="R", decider="ai", action="TAKE",
                    confidence=0.5).took
    assert not Decision(case_id="C", replay_id="R", decider="ai", action="WATCH",
                        confidence=0.5).took


def test_a_confidence_outside_zero_to_one_is_refused():
    """It is scored for calibration, so it has to be a probability."""
    with pytest.raises(DecisionError, match="outside"):
        Decision(case_id="C", replay_id="R", decider="ai", action="TAKE",
                 confidence=1.5)


def test_the_prompt_hash_moves_when_the_vocabulary_does(monkeypatch):
    """A tag added is a category offered to the judge; it is a new test."""
    before = prompt_mod.prompt_hash()
    monkeypatch.setattr(prompt_mod, "REASONING_TAGS",
                        prompt_mod.REASONING_TAGS + ("a_new_idea",))
    assert prompt_mod.prompt_hash() != before
