"""The seal, the budget boundary, and the matched take rate.

MISSION §6 asks that a decision never be revised after subsequent data is seen.
An instruction to that effect is worth nothing; what is worth something is a
`reveal` that refuses to run unless the decisions already on disk hash to what
was committed. These tests are that refusal.

They also pin *where the budget is spent*. A replay that is defined, generated,
built and judged has read nothing about what happened next — it has spent
tokens and compute, both replaceable. If the gate fired at freeze instead, a
researcher would burn dispatches on experiments they never revealed, and the
one genuinely scarce resource would drain to no purpose.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.discretionary import baselines as B
from src.discretionary import replay as R
from src.discretionary.case import Case
from src.discretionary.decision import Decision, commit_hash
from src.discretionary.opportunity import OpportunityDef


@pytest.fixture
def rid(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "REPLAYS_DIR", tmp_path / "replays")
    return "RPL_TEST"


def _defn(**kw) -> OpportunityDef:
    base = dict(id="RPL_TEST", hypothesis_id="H001", idea="a test idea",
                sample_n=6, baselines=("take_all", "random_matched"))
    base.update(kw)
    return OpportunityDef(**base)


def _cases(n=6) -> list[Case]:
    return [Case(case_id=f"RPL_TEST_C{i:05d}", symbol=f"S{i}",
                 date="2022-06-01", anonymised=True, generator_score=float(i),
                 generator_reason="fixture", blocks={"market": {"mkt_regime": "chop"}})
            for i in range(n)]


def _decisions(cases, actions=None) -> list[Decision]:
    actions = actions or ["TAKE", "SKIP", "SKIP", "TAKE", "SKIP", "SKIP"]
    return [Decision(case_id=c.case_id, replay_id="RPL_TEST", decider="ai",
                     action=a, confidence=0.5, case_hash=c.case_hash)
            for c, a in zip(cases, actions)]


def _seed(rid, cases, decisions):
    """Write a replay to disk as the decide phase would have left it."""
    from src.discretionary import case as case_mod
    from src.discretionary.decision import to_jsonl
    r = R._open(rid)
    r.root.mkdir(parents=True, exist_ok=True)
    r.definition_path.write_text(_defn().to_json())
    r.cases_path.write_text(case_mod.to_jsonl(cases))
    r.decisions_path.write_text(to_jsonl(decisions))
    r.seal_path.write_text(json.dumps({
        "commit_hash": commit_hash(decisions),
        "case_set_hash": case_mod.case_set_hash(cases),
        "identity_hash": "abc", "prompt_hash": "p", "n_decisions": len(decisions),
    }))
    return r


# --------------------------------------------------------------------------
# the seal
# --------------------------------------------------------------------------

def test_reveal_refuses_when_no_decision_was_ever_committed(rid):
    cases = _cases()
    r = R._open(rid)
    r.root.mkdir(parents=True, exist_ok=True)
    r.definition_path.write_text(_defn().to_json())
    from src.discretionary import case as case_mod
    r.cases_path.write_text(case_mod.to_jsonl(cases))

    with pytest.raises(R.SealBrokenError, match="ordering is the experiment"):
        R.check_seal(rid)


def test_reveal_refuses_when_a_decision_changed_after_the_commit(rid):
    """The point of the whole design: no revising once the future is in view."""
    cases = _cases()
    decisions = _decisions(cases)
    r = _seed(rid, cases, decisions)

    tampered = list(decisions)
    tampered[1] = Decision(case_id=cases[1].case_id, replay_id="RPL_TEST",
                           decider="ai", action="TAKE", confidence=0.9,
                           case_hash=cases[1].case_hash)
    from src.discretionary.decision import to_jsonl
    r.decisions_path.write_text(to_jsonl(tampered))

    with pytest.raises(R.SealBrokenError, match="has been changed"):
        R.check_seal(rid)


def test_reveal_refuses_when_a_decision_was_quietly_dropped(rid):
    """A selector that deletes its losers is the oldest trick there is."""
    cases = _cases()
    decisions = _decisions(cases)
    r = _seed(rid, cases, decisions)
    from src.discretionary.decision import to_jsonl
    r.decisions_path.write_text(to_jsonl(decisions[:-1]))
    with pytest.raises(R.SealBrokenError):
        R.check_seal(rid)


def test_decisions_without_a_seal_are_treated_as_compromised(rid):
    cases = _cases()
    r = _seed(rid, cases, _decisions(cases))
    r.seal_path.unlink()
    with pytest.raises(R.SealBrokenError, match="compromised"):
        R.check_seal(rid)


def test_an_untouched_replay_passes_the_seal(rid):
    cases = _cases()
    _seed(rid, cases, _decisions(cases))
    seal = R.check_seal(rid)
    assert seal["n_decisions"] == 6


def test_reloading_decisions_does_not_break_the_seal(rid):
    """Provenance may differ on reload; the verdict may not."""
    cases = _cases()
    r = _seed(rid, cases, _decisions(cases))
    reloaded = r.decisions()
    from src.discretionary.decision import to_jsonl
    r.decisions_path.write_text(to_jsonl(reloaded))
    assert R.check_seal(rid)["commit_hash"] == commit_hash(reloaded)


def test_deciding_twice_is_refused(rid):
    """Re-deciding is a second test of the same sample, and it must be visible."""
    cases = _cases()
    _seed(rid, cases, _decisions(cases))
    with pytest.raises(R.ReplayError, match="already has committed decisions"):
        R.decide(rid)


def test_freezing_twice_is_refused(rid):
    R.freeze(_defn())
    with pytest.raises(R.ReplayError, match="immutable"):
        R.freeze(_defn())


# --------------------------------------------------------------------------
# where the budget is spent
# --------------------------------------------------------------------------

def test_freeze_does_not_touch_the_budget(rid, monkeypatch):
    """Defining an experiment reads nothing about what happened next."""
    called = []
    monkeypatch.setattr(R.gate, "enforce_dispatch_gate",
                        lambda *a, **k: called.append("gate"))
    R.freeze(_defn())
    assert called == []


def test_reveal_consults_the_gate_before_reading_an_outcome(rid, monkeypatch):
    cases = _cases()
    _seed(rid, cases, _decisions(cases))
    order = []
    monkeypatch.setattr(R, "validate", lambda d, check_budget=False: order.append("ledger"))
    monkeypatch.setattr(R.gate, "enforce_dispatch_gate", lambda s: order.append("gate"))
    monkeypatch.setattr(R.outcomes_mod, "compute",
                        lambda *a, **k: order.append("outcome") or pd.DataFrame())
    R.reveal(rid)
    assert order == ["ledger", "gate", "outcome"], (
        "the budget must be checked before the partition is read")


def test_a_refused_gate_stops_the_reveal(rid, monkeypatch):
    cases = _cases()
    _seed(rid, cases, _decisions(cases))
    monkeypatch.setattr(R, "validate", lambda d, check_budget=False: None)
    monkeypatch.setattr(R.gate, "enforce_dispatch_gate",
                        lambda s: (_ for _ in ()).throw(
                            R.gate.DispatchRateLimitExceededError("no budget")))
    touched = []
    monkeypatch.setattr(R.outcomes_mod, "compute",
                        lambda *a, **k: touched.append(1) or pd.DataFrame())
    with pytest.raises(R.gate.DispatchRateLimitExceededError):
        R.reveal(rid)
    assert touched == [], "an outcome was read after the gate refused"


def test_a_replay_is_presented_to_the_gate_as_one_more_test(rid):
    """burden reads Evidence records; a replay must look like a test to it."""
    spec = R._gate_spec(_defn())
    assert spec.signal_name == "replay:RPL_TEST"
    assert spec.partition == "train" and spec.role == "exploratory"


# --------------------------------------------------------------------------
# the matched take rate
# --------------------------------------------------------------------------

def test_baselines_are_matched_to_the_ai_take_rate():
    """Selectivity and skill are confounded unless the rate is held equal."""
    cases = _cases(20)
    ai = [Decision(case_id=c.case_id, replay_id="R", decider="ai",
                   action="TAKE" if i < 5 else "SKIP", confidence=0.5)
          for i, c in enumerate(cases)]
    arms = B.run(("random_matched", "top_n_by_score"), cases, ai, "R", seed=1)
    for name in ("random_matched", "top_n_by_score"):
        took = sum(d.took for d in arms if d.decider == name)
        assert took == 5, f"{name} took {took}, expected the AI's 5"


def test_take_all_is_not_matched():
    """It is the pool itself — the thing every lift is measured against."""
    cases = _cases(10)
    ai = [Decision(case_id=c.case_id, replay_id="R", decider="ai",
                   action="SKIP", confidence=0.5) for c in cases]
    arms = B.run(("take_all",), cases, ai, "R")
    assert all(d.took for d in arms)


def test_watch_does_not_count_as_a_position():
    cases = _cases(10)
    ai = [Decision(case_id=c.case_id, replay_id="R", decider="ai",
                   action="WATCH" if i < 4 else "SKIP", confidence=0.5)
          for i, c in enumerate(cases)]
    assert B.take_rate(ai) == 0.0


def test_top_n_by_score_spreads_across_sessions():
    """A global cut on a regime-drifting score picks sessions, not names."""
    cases = []
    for s, day in enumerate(("2022-01-03", "2022-06-01")):
        for i in range(10):
            # The second session's scores are uniformly higher.
            cases.append(Case(case_id=f"C{s}{i}", symbol=f"S{i}", date=day,
                              anonymised=True, generator_score=i + s * 100,
                              generator_reason="f", blocks={}))
    ai = [Decision(case_id=c.case_id, replay_id="R", decider="ai",
                   action="TAKE" if i < 6 else "SKIP", confidence=0.5)
          for i, c in enumerate(cases)]
    arms = B.run(("top_n_by_score",), cases, ai, "R")
    by_day: dict[str, int] = {}
    for c, d in zip(cases, arms):
        by_day[c.date] = by_day.get(c.date, 0) + int(d.took)
    assert by_day == {"2022-01-03": 3, "2022-06-01": 3}, (
        f"a global cut would have taken all six from one session: {by_day}")


def test_a_degenerate_generator_score_is_reported_not_hidden(caplog):
    """liquid_universe scores everything zero; that arm is not a ranking."""
    cases = [Case(case_id=f"C{i}", symbol=f"S{i}", date="2022-01-03",
                  anonymised=True, generator_score=0.0, generator_reason="f",
                  blocks={}) for i in range(10)]
    ai = [Decision(case_id=c.case_id, replay_id="R", decider="ai",
                   action="TAKE" if i < 3 else "SKIP", confidence=0.5)
          for i, c in enumerate(cases)]
    with caplog.at_level("WARNING"):
        arms = B.run(("top_n_by_score",), cases, ai, "R")
    assert "not a ranking" in caplog.text
    assert sum(d.took for d in arms) == 3


def test_the_rank_model_never_fits_on_an_unresolved_outcome():
    """Filtering on a row's date rather than on when its outcome landed leaks.

    A row five sessions before a case has not resolved at a ten-session
    horizon: its window overlaps the case being scored.
    """
    dates = pd.bdate_range("2022-01-03", periods=400)
    rng = np.random.default_rng(0)
    fit = pd.DataFrame({
        "symbol": np.repeat([f"S{i}" for i in range(10)], len(dates)),
        "date": np.tile(dates, 10),
        "outcome_pct": rng.normal(0, 3, 10 * len(dates)),
        "ret_20d": rng.normal(0, 5, 10 * len(dates)),
        "rs_20d_vs_mkt": rng.normal(0, 4, 10 * len(dates)),
    })
    fit["resolved_by"] = fit["date"] + pd.Timedelta(days=14)

    cut = dates[300]
    cases = [Case(case_id=f"C{i}", symbol=f"S{i}", date=cut.strftime("%Y-%m-%d"),
                  anonymised=True, generator_score=0.0, generator_reason="f",
                  blocks={}) for i in range(10)]
    ai = [Decision(case_id=c.case_id, replay_id="R", decider="ai",
                   action="TAKE" if i < 3 else "SKIP", confidence=0.5)
          for i, c in enumerate(cases)]
    arms = B.run(("rank_model",), cases, ai, "R", fit_frame=fit)
    assert sum(d.took for d in arms) == 3
    # Every row the model could legally have used resolved before the case.
    usable = fit[fit["resolved_by"] < cut]
    assert usable["date"].max() < cut
