"""Can the report find an edge that is there, and refuse one that is not?

Two controls, and the second matters more than the first.

**Recovery.** Plant a selector that genuinely picks better cases and require
the report to see it, at roughly the size it was planted.

**The null.** Give the report a selector that picks at random and require it to
say so. A framework that reports lift on noise is worse than no framework: it
would produce a stream of confident, wrong findings, each one indistinguishable
from a real one, and it would spend the partition doing it.

The null control is run over many seeds because a single random draw can look
like anything. What is checked is the *rejection rate* — how often a
no-information selector clears the bar — which is the property that decides
whether this lab can trust its own output.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.discretionary import evaluate as E
from src.discretionary.decision import Decision
from src.discretionary.opportunity import OpportunityDef

N_SESSIONS = 220
PER_SESSION = 8
HORIZON = 10


def _world(seed: int, edge_bps: float = 0.0, skill: float = 0.0):
    """A case set, its outcomes, and a selector with a planted edge.

    `skill` is the correlation between what the selector sees and the outcome:
    0 is a coin, 1 is clairvoyance. `edge_bps` scales the planted lift.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-04", periods=N_SESSIONS)
    rows = []
    for d in dates:
        session = rng.normal(0, 0.8)          # a common shock, as real days have
        for k in range(PER_SESSION):
            rows.append({"case_id": f"C{len(rows):05d}", "date": d,
                         "symbol": f"S{k}", "_session": session})
    df = pd.DataFrame(rows)
    n = len(df)
    noise = rng.normal(0, 3.0, n)
    quality = rng.normal(0, 1.0, n)
    df["primary_excess_pct"] = df["_session"] + noise + quality * (edge_bps / 100.0)
    df["mfe_pct"] = df["primary_excess_pct"] + np.abs(rng.normal(0, 2, n))
    df["mae_pct"] = df["primary_excess_pct"] - np.abs(rng.normal(0, 2, n))

    # The selector observes `quality` with noise scaled by its skill.
    seen = skill * quality + np.sqrt(max(1 - skill ** 2, 0)) * rng.normal(0, 1, n)
    take = seen > np.quantile(seen, 0.85)      # a 15% take rate
    return df, take


def _decisions(df, take, seed=0):
    rng = np.random.default_rng(seed)
    ai = [Decision(case_id=c, replay_id="R", decider="ai",
                   action="TAKE" if t else "SKIP",
                   confidence=float(np.clip(0.5 + 0.2 * t, 0, 1)),
                   tags=["chart_structure"] if t else ["no_edge_visible"])
          for c, t in zip(df["case_id"], take)]
    pool = [Decision(case_id=c, replay_id="R", decider="take_all",
                     action="TAKE", confidence=1.0) for c in df["case_id"]]
    rnd_mask = rng.random(len(df)) > 0.85
    rnd = [Decision(case_id=c, replay_id="R", decider="random_matched",
                    action="TAKE" if m else "SKIP", confidence=0.5)
           for c, m in zip(df["case_id"], rnd_mask)]
    return ai + pool + rnd


def _defn(**kw):
    base = dict(id="RPL_T", hypothesis_id="H001", idea="synthetic",
                primary_horizon=HORIZON, horizons=(5, 10, 20),
                baselines=("take_all", "random_matched"))
    base.update(kw)
    return OpportunityDef(**base)


def _run(seed, edge_bps=0.0, skill=0.0):
    df, take = _world(seed, edge_bps, skill)
    return E.evaluate(_decisions(df, take, seed), df, _defn())


# --------------------------------------------------------------------------
# recovery
# --------------------------------------------------------------------------

def test_a_planted_edge_is_recovered():
    """A selector that really does pick better cases must show up as one."""
    rep = _run(seed=1, edge_bps=120.0, skill=0.9)
    hl = rep["headline"]
    assert hl["excess_lift_bps"] > 40, hl
    assert hl["excess_lift_t"] > 3, hl
    assert hl["take_vs_skip_bps"] > hl["excess_lift_bps"], (
        "take-vs-skip must exceed take-vs-pool: the pool contains the takes")
    assert rep["verdict"]["failure_class"] == "SUCCESS", rep["verdict"]


def test_the_report_beats_the_random_arm_when_the_edge_is_real():
    rep = _run(seed=2, edge_bps=120.0, skill=0.9)
    lift = rep["baselines"]["random_matched"]["ai_minus_this"]
    assert lift["mean_diff_bps"] > 30, lift


def test_take_rate_and_arm_matching_are_reported():
    rep = _run(seed=3, edge_bps=100.0, skill=0.8)
    assert 10 <= rep["ai"]["take_rate_pct"] <= 20
    assert rep["ai"]["n_taken"] > 0
    assert rep["baselines"]["take_all"]["take_rate_pct"] == 100.0


# --------------------------------------------------------------------------
# the null — the control that decides whether this lab can trust itself
# --------------------------------------------------------------------------

def test_a_selector_with_no_information_reports_no_lift():
    rep = _run(seed=11, edge_bps=0.0, skill=0.0)
    assert rep["verdict"]["failure_class"] in ("NO_SIGNAL", "SIGNAL_TOO_SMALL")
    assert not rep["verdict"]["passed"]


def test_the_null_rejection_rate_is_near_the_nominal_five_percent():
    """The property that decides whether a reported edge means anything.

    A framework that clears its own bar on noise would emit a stream of
    confident wrong findings and spend the partition doing it. Run over many
    coin-flip selectors, the share that passes must stay near nominal — this is
    the check that the session pairing and the Hansen-Hodrick correction are
    actually doing their job on overlapping windows.
    """
    passes, big_t = 0, 0
    trials = 40
    for seed in range(trials):
        rep = _run(seed=100 + seed, edge_bps=0.0, skill=0.0)
        passes += bool(rep["verdict"]["passed"])
        t = rep["headline"]["excess_lift_t"]
        big_t += bool(t is not None and np.isfinite(t) and abs(t) > 1.96)
    assert passes <= 4, f"{passes}/{trials} null selectors cleared the bar"
    assert big_t <= 8, (
        f"|t|>1.96 on {big_t}/{trials} null runs; the overlap correction is "
        f"not binding")


def test_a_null_selector_does_not_beat_the_random_arm():
    diffs = []
    for seed in range(20):
        rep = _run(seed=300 + seed, edge_bps=0.0, skill=0.0)
        d = rep["baselines"]["random_matched"]["ai_minus_this"]["mean_diff_bps"]
        if d is not None and np.isfinite(d):
            diffs.append(d)
    assert abs(float(np.mean(diffs))) < 20, (
        f"a coin beat another coin by {np.mean(diffs):.1f} bps on average")


# --------------------------------------------------------------------------
# the machinery the contrasts rest on
# --------------------------------------------------------------------------

def test_contrasts_are_paired_within_the_session():
    """H020: controls from adjacent sessions tripled every contrast.

    Winners cluster on local market troughs, so a control drawn from a
    different day carries that day's market move into the difference.
    """
    dates = pd.bdate_range("2022-01-03", periods=40)
    rows = []
    for i, d in enumerate(dates):
        level = 100.0 * i          # a huge session effect, identical for both arms
        rows.extend([{"date": d, "primary_excess_pct": level + 1.0},
                     {"date": d, "primary_excess_pct": level - 1.0}])
    df = pd.DataFrame(rows)
    a = pd.Series([True, False] * len(dates))
    res = E.session_paired_contrast(df, a, ~a, "primary_excess_pct", lags=9)
    assert res["mean_diff_bps"] == pytest.approx(200.0, abs=1e-6), (
        "the session effect leaked into a within-session contrast")


def test_a_session_carrying_only_one_arm_is_excluded():
    """It says nothing about a difference, and its level would smuggle in."""
    df = pd.DataFrame({
        "date": pd.to_datetime(["2022-01-03", "2022-01-03", "2022-01-04"]),
        "primary_excess_pct": [1.0, -1.0, 500.0],
    })
    a = pd.Series([True, False, True])
    res = E.session_paired_contrast(df, a, ~a, "primary_excess_pct", lags=0)
    assert res["n_sessions"] == 1
    assert res["mean_diff_bps"] == pytest.approx(200.0, abs=1e-6)


def test_the_overlap_correction_is_actually_applied():
    rep = _run(seed=7, edge_bps=100.0, skill=0.8)
    c = rep["contrasts"]["take_vs_pool"]
    assert c["hac_lags"] == HORIZON - 1
    assert abs(c["t"]) < abs(c["naive_t"]), (
        "the corrected t must be smaller than the naive one on overlapping "
        "windows, or the correction is not binding")


def test_a_bar_the_definition_did_not_name_cannot_rescue_a_result():
    """A bar applied only when it is passed is not a bar."""
    df, take = _world(5, edge_bps=0.0, skill=0.0)
    defn = _defn(pass_criterion={"min_excess_lift_bps": 500.0})
    rep = E.evaluate(_decisions(df, take, 5), df, defn)
    assert [c["criterion"] for c in rep["verdict"]["checks"]] == \
        ["min_excess_lift_bps"]
    assert not rep["verdict"]["passed"]


def test_the_sample_caveat_is_always_stated():
    rep = _run(seed=9, edge_bps=100.0, skill=0.8)
    caveat = rep["verdict"]["sample_caveat"]
    assert "sessions" in caveat and "invents independent observations" in caveat


def test_costs_are_charged_on_levels_and_not_on_lifts():
    """Two selections both pay the round trip, so it cancels in a difference."""
    rep = _run(seed=13, edge_bps=100.0, skill=0.8)
    taken = rep["ai"]["taken"]
    assert taken["net_of_costs_pct"] == pytest.approx(
        taken["mean"] - 0.40, abs=1e-6)


def test_calibration_needs_three_distinct_confidence_values():
    """A line through two points is exact by construction.

    A judge that only ever says 0.6 or 0.7 would produce a slope that means
    nothing — and could still clear a calibration bar with it.
    """
    rep = _run(seed=17, edge_bps=100.0, skill=0.8)
    # Only taken cases are read, and in this fixture they all share one value.
    assert rep["calibration"]["distinct_confidences"] < 3
    assert "slope_bps_per_unit" not in rep["calibration"]

    df, take = _world(17, 100.0, 0.8)
    rng = np.random.default_rng(0)
    ai = [Decision(case_id=c, replay_id="R", decider="ai",
                   action="TAKE" if t else "SKIP",
                   confidence=round(float(rng.uniform(0.3, 0.9)), 2))
          for c, t in zip(df["case_id"], take)]
    pool = [Decision(case_id=c, replay_id="R", decider="take_all",
                     action="TAKE", confidence=1.0) for c in df["case_id"]]
    rep = E.evaluate(ai + pool, df, _defn(baselines=("take_all",)))
    assert "slope_bps_per_unit" in rep["calibration"]
    assert rep["calibration"]["buckets"]


def test_a_replay_that_took_nothing_is_not_a_finding():
    df, _ = _world(21)
    take = np.zeros(len(df), dtype=bool)
    rep = E.evaluate(_decisions(df, take), df, _defn())
    assert rep["verdict"]["failure_class"] == "INSUFFICIENT_SAMPLE"
    assert not rep["verdict"]["passed"]
