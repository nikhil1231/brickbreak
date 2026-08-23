"""The dispersion gate, and the calibration that makes it readable.

The first version of this module used the mean of per-session sample variances
and scored two independent random draws of the same panel at 0.84 and 1.53.
Heavy tails: the mean of sample variances is dominated by a few sessions and
does not converge at this sample size. So the null test is not a formality
here — it is the reason the estimator is the one it is.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.alpha_eval import spread as S


def _panel(n_sessions=400, n_names=300, seed=0, tail_df=3):
    """Heavy-tailed excess returns, session shocks, as the real panel has."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-04", periods=n_sessions)
    rows = []
    for d in dates:
        shock = rng.normal(0, 1.0)
        r = shock + rng.standard_t(tail_df, n_names) * 4.0
        for k in range(n_names):
            rows.append({"symbol": f"S{k:04d}", "date": d, "excess_pct": r[k]})
    return pd.DataFrame(rows)


def _sample_events(panel, n, seed=0):
    return panel.sample(n, random_state=seed)[["symbol", "date"]]


# --------------------------------------------------------------------------
# the null the estimator has to pass before anything else can be read
# --------------------------------------------------------------------------

def test_a_random_event_family_scores_one():
    p = _panel()
    rep = S.check(_sample_events(p, 4000, 0), p, label="random")
    assert 0.90 <= rep["dispersion_ratio"] <= 1.10, rep
    assert 0.90 <= rep["tail_ratio"] <= 1.10, rep


def test_two_independent_random_draws_agree():
    """The failure that killed the variance version, asserted so it stays dead."""
    p = _panel()
    a = S.check(_sample_events(p, 4000, 1), p, label="a")["dispersion_ratio"]
    b = S.check(_sample_events(p, 12000, 2), p, label="b")["dispersion_ratio"]
    assert abs(a - b) < 0.12, (a, b)


def test_a_random_family_is_read_as_nothing_to_select_on():
    p = _panel()
    rep = S.check(_sample_events(p, 12000, 3), p, label="random")
    assert "NOTHING TO SELECT ON" in rep["verdict"] or "MARGINAL" in rep["verdict"]


# --------------------------------------------------------------------------
# it has to see a real widening
# --------------------------------------------------------------------------

def test_a_family_whose_outcomes_fan_out_is_detected():
    p = _panel()
    rng = np.random.default_rng(9)
    idx = rng.choice(len(p), size=6000, replace=False)
    p = p.copy()
    p.iloc[idx, p.columns.get_loc("excess_pct")] *= 2.0
    rep = S.check(p.iloc[idx][["symbol", "date"]], p, label="widened")
    assert rep["dispersion_ratio"] > 1.5, rep
    assert "WORTH THE NEXT STAGE" in rep["verdict"]


def test_a_family_that_splits_into_two_groups_still_passes():
    """The case a gate built on means throws away: mean zero, all the spread."""
    p = _panel().copy()
    rng = np.random.default_rng(11)
    idx = rng.choice(len(p), size=6000, replace=False)
    sign = rng.choice([-1.0, 1.0], size=len(idx))
    p.iloc[idx, p.columns.get_loc("excess_pct")] += sign * 12.0
    ev = p.iloc[idx][["symbol", "date"]]
    assert abs(p.iloc[idx]["excess_pct"].mean()) < 1.0      # a mean test sees nothing
    rep = S.check(ev, p, label="two-sided")
    assert rep["dispersion_ratio"] > 1.4, rep


# --------------------------------------------------------------------------
# and it has to refuse what it cannot read
# --------------------------------------------------------------------------

def test_one_event_per_session_is_refused_not_scored():
    """The IPO shape. A within-session dispersion needs two names in the group."""
    p = _panel()
    one = p.groupby("date").head(1)[["symbol", "date"]]
    rep = S.check(one, p, label="thin")
    assert rep["events_per_session"] < 2.0
    assert "UNREADABLE" in rep["verdict"]


def test_a_family_with_no_controls_on_its_sessions_raises():
    p = _panel(n_sessions=20, n_names=4)
    with pytest.raises(S.SpreadError):
        S.check(p[["symbol", "date"]], p, label="everything")


def test_events_need_a_symbol_and_a_date():
    p = _panel(n_sessions=20)
    with pytest.raises(S.SpreadError, match="symbol"):
        S.check(pd.DataFrame({"date": [1, 2]}), p)


def test_outcomes_are_strictly_forward():
    bars = pd.DataFrame({
        "symbol": ["A"] * 30, "date": pd.bdate_range("2021-01-04", periods=30),
        "close": np.arange(100.0, 130.0)})
    out = S.outcomes(bars, horizon=10)
    assert len(out) == 20                       # last 10 have no forward window


def test_compare_orders_by_dispersion():
    p = _panel()
    reps = [S.check(_sample_events(p, 4000, 4), p, label="flat")]
    q = p.copy()
    rng = np.random.default_rng(5)
    idx = rng.choice(len(q), size=4000, replace=False)
    q.iloc[idx, q.columns.get_loc("excess_pct")] *= 3.0
    reps.append(S.check(q.iloc[idx][["symbol", "date"]], q, label="wide"))
    assert S.compare(reps).iloc[0]["family"] == "wide"


# --------------------------------------------------------------------------
# the confound the gate must not be fooled by
# --------------------------------------------------------------------------

def _panel_with_vol(n_sessions=300, n_names=300, seed=0):
    """A panel where a fifth of the names are permanently jumpy."""
    rng = np.random.default_rng(seed)
    jumpy = {f"S{k:04d}" for k in range(n_names // 5)}
    dates = pd.bdate_range("2021-01-04", periods=n_sessions)
    rows = []
    for d in dates:
        shock = rng.normal(0, 1.0)
        for k in range(n_names):
            sym = f"S{k:04d}"
            scale = 9.0 if sym in jumpy else 3.0
            rows.append({"symbol": sym, "date": d,
                         "excess_pct": shock + rng.standard_t(4) * scale,
                         "vol_q": 1 if sym in jumpy else 0})
    return pd.DataFrame(rows), jumpy


def test_an_event_that_only_happens_in_jumpy_names_is_caught_by_matching():
    """The likeliest false positive for anything flow-related.

    An event family drawn entirely from high-volatility names fans outcomes out
    without carrying any information at all. Matched on the session alone the
    gate calls it a finding; matched on a volatility bucket it correctly reads
    as nothing. Measured on real bulk deals, this confound was worth about half
    the raw effect.
    """
    p, jumpy = _panel_with_vol()
    ev = p[p["symbol"].isin(jumpy)].sample(6000, random_state=0)[["symbol", "date"]]

    naive = S.check(ev, p, label="unmatched")["dispersion_ratio"]
    matched = S.check(ev, p, label="matched", match_on=("vol_q",))["dispersion_ratio"]

    assert naive > 1.5, naive                       # looks like a strong finding
    assert 0.90 <= matched <= 1.10, matched         # and is not one


def test_matching_does_not_erase_a_real_effect():
    """The other half: matching must not be so aggressive it kills the signal."""
    p, jumpy = _panel_with_vol()
    rng = np.random.default_rng(3)
    idx = rng.choice(len(p), size=6000, replace=False)
    p = p.copy()
    p.iloc[idx, p.columns.get_loc("excess_pct")] *= 2.5
    ev = p.iloc[idx][["symbol", "date"]]
    assert S.check(ev, p, label="real", match_on=("vol_q",))["dispersion_ratio"] > 1.6


def test_match_on_a_column_the_panel_lacks_is_refused():
    p, _ = _panel_with_vol(n_sessions=40)
    with pytest.raises(S.SpreadError, match="absent from the panel"):
        S.check(p.sample(400, random_state=0)[["symbol", "date"]], p,
                match_on=("size_tier",))


def test_persistence_reads_zero_when_event_sets_are_disjoint():
    """Different names every session: the differences cannot overlap."""
    dates = pd.bdate_range("2021-01-04", periods=200)
    ev = pd.DataFrame({"date": np.repeat(dates, 5),
                       "symbol": [f"S{i:05d}" for i in range(len(dates) * 5)]})
    rep = S.event_persistence(ev, horizon=10)
    assert rep["overlap_share"] == 0.0
    assert rep["effective_sessions_multiplier"] == 1.0


def test_persistence_reads_one_when_the_same_names_recur():
    """The same five names every session: a full overlap, sessions/horizon."""
    dates = pd.bdate_range("2021-01-04", periods=200)
    ev = pd.DataFrame({"date": np.repeat(dates, 5),
                       "symbol": [f"S{i%5:03d}" for i in range(len(dates) * 5)]})
    rep = S.event_persistence(ev, horizon=10)
    assert rep["overlap_share"] == 1.0
    assert rep["effective_sessions_multiplier"] == pytest.approx(0.1, abs=0.01)


def test_persistence_sits_between_for_a_partly_recurring_set():
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2021-01-04", periods=300)
    rows = []
    for d in dates:
        keep = [f"S{k:03d}" for k in range(2)]              # always present
        fresh = [f"F{rng.integers(0, 10_000)}" for _ in range(2)]
        rows += [{"date": d, "symbol": s} for s in keep + fresh]
    rep = S.event_persistence(pd.DataFrame(rows), horizon=10)
    assert 0.3 < rep["overlap_share"] < 0.8, rep
