"""The distillation stage: the judge's reasons, made falsifiable.

The stage exists because the judge's *picks* cannot be tested — 500 cases is
four independent blocks and 8.8% of coin-flippers clear the bar there. Its
*reasons*, written as code, run over the whole panel where the sample is.

So these tests are mostly about honesty rather than arithmetic: that a rule
cannot be authored with outcomes in view, that fidelity is measured against
chance rather than raw agreement, and that a rule which works without
reproducing the judge is not allowed to be read as a win for the judge.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.discretionary import distil as D
from src.discretionary.decision import Decision


def _decisions(n=40, take_every=4):
    out = []
    for i in range(n):
        took = i % take_every == 0
        out.append(Decision(
            case_id=f"C{i:03d}", replay_id="RPL_T", decider="ai",
            action="TAKE" if took else "SKIP", confidence=0.7 if took else 0.3,
            unusual="volume dried up into the last three bars" if took else "",
            thesis="tightening base" if took else "nothing unusual",
            tags=["contraction", "volume_dry"] if took else ["no_edge_visible"]))
    return out


def _frame(n=40):
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "case_id": [f"C{i:03d}" for i in range(n)],
        "date": pd.bdate_range("2021-01-04", periods=n),
        "bb_width_pctile": rng.uniform(0, 100, n),
        "atr_ratio": rng.uniform(0.5, 1.5, n),
    })


def _rule(expr="bb_width_pctile < 20"):
    return D.DistilledRule(
        name="tightening_base", claim="the base was tightening while volume dried up",
        expression=expr, source_replay="RPL_T", source_tags=("contraction",))


# --------------------------------------------------------------------------
# authoring cannot see the answers
# --------------------------------------------------------------------------

def test_a_rule_cannot_be_authored_with_the_outcomes_on_screen():
    """Writing a predicate while able to see which takes worked is a fit."""
    meta = _frame().assign(fwd_ret_10d_pct=0.0)
    with pytest.raises(Exception) as exc:
        D.propose_from_replay(_decisions(), meta)
    assert "fwd" in str(exc.value).lower() or "forward" in str(exc.value).lower()


def test_the_authoring_material_carries_no_outcome_anywhere():
    mat = D.propose_from_replay(_decisions(), _frame())
    # Everything except the prose that warns the author off outcomes.
    blob = str({k: v for k, v in mat.items() if k != "authoring_rule"}).lower()
    for banned in ("fwd_", "forward", "excess_pct", "outcome", "_ret_"):
        assert banned not in blob, banned


def test_a_replay_that_took_nothing_has_no_reason_to_distil():
    silent = [Decision(case_id=f"C{i}", replay_id="R", decider="ai",
                       action="SKIP", confidence=0.2) for i in range(10)]
    with pytest.raises(D.DistillationError, match="took nothing"):
        D.propose_from_replay(silent)


def test_tags_are_ranked_by_separation_not_by_frequency():
    """A tag on 90% of takes and 88% of skips is vocabulary, not a reason."""
    ds = _decisions()
    for d in ds:                      # a tag everything carries
        d.tags = list(d.tags) + ["chart_structure"]
    mat = D.propose_from_replay(ds)
    top = mat["discriminating_tags"][0]
    assert top["tag"] != "chart_structure"
    common = [r for r in mat["discriminating_tags"] if r["tag"] == "chart_structure"]
    assert common and common[0]["separation_pp"] == 0.0


# --------------------------------------------------------------------------
# fidelity is measured against chance
# --------------------------------------------------------------------------

def test_two_unrelated_selectors_agree_most_of_the_time_and_score_zero():
    """The trap raw agreement sets: two 25% arms agree ~62% knowing nothing."""
    rng = np.random.default_rng(1)
    a = pd.Series(rng.random(4000) < 0.25)
    b = pd.Series(rng.random(4000) < 0.25)
    rep = D.fidelity(a, b)
    assert rep["agreement_pct"] > 55
    assert abs(rep["kappa"]) < 0.06, rep


def test_a_perfect_reproduction_scores_one():
    a = pd.Series([True, False, True, False] * 25)
    assert D.fidelity(a, a)["kappa"] == 1.0


def test_fidelity_is_only_defined_on_the_same_case_set():
    with pytest.raises(D.DistillationError, match="same case set"):
        D.fidelity(pd.Series([True] * 5), pd.Series([True] * 6))


def test_per_session_agreement_is_reported():
    f = _frame()
    rep = D.fidelity(pd.Series([True, False] * 20), pd.Series([True, False] * 20),
                     dates=f["date"])
    assert rep["sessions"] == 40


# --------------------------------------------------------------------------
# applying a rule
# --------------------------------------------------------------------------

def test_a_rule_refuses_a_frame_that_carries_the_future():
    with pytest.raises(Exception):
        D.apply_rule(_rule(), _frame().assign(fwd_ret_10d_pct=0.0))


def test_a_rule_that_does_not_evaluate_says_so_clearly():
    with pytest.raises(D.DistillationError, match="did not evaluate"):
        D.apply_rule(_rule("no_such_column > 3"), _frame())


def test_a_rule_selects_and_the_mask_lines_up_with_the_frame():
    f = _frame()
    mask = D.apply_rule(_rule(), f)
    assert len(mask) == len(f)
    assert mask.sum() == (f["bb_width_pctile"] < 20).sum()


def test_a_rule_must_say_where_it_came_from():
    with pytest.raises(D.DistillationError, match="source_replay"):
        D.DistilledRule(name="x", claim="c", expression="a > 1", source_replay=" ")


def test_the_rule_hash_tracks_the_expression():
    assert _rule().rule_hash != _rule("bb_width_pctile < 21").rule_hash


# --------------------------------------------------------------------------
# the two-by-two the stage exists to fill in
# --------------------------------------------------------------------------

def test_a_faithful_rule_with_an_edge_is_the_win():
    rep = D.classify({"kappa": 0.6}, 90.0, True)
    assert rep["cell"] == "DISTILLED"


def test_a_faithful_rule_without_an_edge_is_a_real_finding():
    rep = D.classify({"kappa": 0.6}, 5.0, False)
    assert rep["cell"] == "REASON_WITHOUT_EDGE"
    assert "worth nothing" in rep["reading"]


def test_an_edge_that_does_not_reproduce_the_judge_is_not_credited_to_it():
    """The dangerous cell: it reads as a success and is not one."""
    rep = D.classify({"kappa": 0.05}, 120.0, True)
    assert rep["cell"] == "EDGE_WITHOUT_REASON"
    assert "not evidence about discretionary judgement" in rep["reading"]


def test_an_unrun_rule_is_not_scored():
    assert D.classify({"kappa": 0.9}, None, None)["cell"] == "UNTESTED"


def test_measure_fidelity_on_holdout():
    f = _frame(50)
    ds = _decisions(50, take_every=2)
    rule = _rule("bb_width_pctile < 50")
    rep = D.measure_fidelity_on_holdout(rule, f, ds)
    assert rep["n_cases"] == 50
    assert "kappa" in rep
    assert rep["holdout_cases"] == 50


def test_evaluate_distilled_rule_mock():
    rng = np.random.default_rng(42)
    n = 100
    dates = pd.bdate_range("2021-01-04", periods=20)
    df = pd.DataFrame({
        "symbol": ["S1", "S2", "S3", "S4", "S5"] * 20,
        "date": np.repeat(dates, 5),
        "bb_width_pctile": rng.uniform(0, 100, n),
        "fwd_ret_5d_pct": rng.normal(0.5, 2.0, n),
        "fwd_ret_10d_pct": rng.normal(0.8, 3.0, n),
        "fwd_ret_20d_pct": rng.normal(1.2, 4.0, n),
    })
    rule = _rule("bb_width_pctile < 30")
    rep = D.evaluate_distilled_rule(rule, df, fidelity_report={"kappa": 0.55}, horizons=(5, 10, 20), run_backtest=False)
    assert "classification" in rep
    assert "alpha_evaluation" in rep
    assert rep["classification"]["faithful"]


def test_register_distilled_rule_and_replay(tmp_path, monkeypatch):
    from src.runner import forward as F
    monkeypatch.setattr(F, "REGISTRY_PATH", tmp_path / "forward_registry.json")
    reg_rule = F.register_distilled_rule(
        rule_name="tightening_base",
        expression="bb_width_pctile < 20",
        rule_hash="abc123456789",
        hypothesis_id="H041",
    )
    assert reg_rule.kind == "distilled_rule"
    assert "compute" in reg_rule.source

    reg_replay = F.register_replay(
        replay_id="RPL_001",
        hypothesis_id="H041",
    )
    assert reg_replay.kind == "replay"
    assert reg_replay.replay_id == "RPL_001"

