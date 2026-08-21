"""Tests for the behavioural feature panel and the exploration guardrails.

The two things worth testing here are the two that would silently corrupt every
number downstream: a feature that peeks past `t`, and a scan that is handed
holdout data. Both are cheap to test and neither shows up as an error when it
goes wrong — a lookahead just makes the results better.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.opening_window import archetypes, behaviour, explore


def _ticks(symbol="AAA", day="2024-05-02", prices=None, vols=None, secs=None):
    """A synthetic morning, one bar per entry, on the 09:15 session grid."""
    prices = prices if prices is not None else [100, 101, 99, 102, 103]
    vols = vols if vols is not None else [10, 20, 30, 40, 50]
    secs = secs if secs is not None else [0, 30, 90, 150, 240]
    ts = pd.Timestamp(day) + pd.Timedelta("09:15:00") + pd.to_timedelta(secs, "s")
    return pd.DataFrame({
        "symbol": symbol, "security_id": symbol, "timestamp": ts,
        "open": prices, "high": prices, "low": prices, "close": prices,
        "volume": vols,
        "date": pd.Timestamp(day),
        "elapsed": np.asarray(secs, dtype=float),
    })


def _day_open(symbol="AAA", day="2024-05-02", px=100.0):
    return pd.DataFrame({"symbol": [symbol], "date": [pd.Timestamp(day)],
                         "day_open": [px]})


def _prep(ticks, cfg=None):
    cfg = cfg or behaviour.BehaviourConfig()
    return behaviour._prepare(ticks, _day_open(), cfg), cfg


# --------------------------------------------------------------------------
# causality
# --------------------------------------------------------------------------

def test_features_at_t_ignore_everything_after_t():
    """The defining property: appending later bars must not move a feature at `t`.

    This is the test that would have caught H004's pairing bug in a different
    guise, and it is the reason the module is built on cumulative statistics.
    """
    cfg = behaviour.BehaviourConfig()
    early = _ticks(prices=[100, 101, 99], vols=[10, 20, 30], secs=[0, 30, 90])
    # Same morning, then a violent move well after t=90s.
    late = _ticks(prices=[100, 101, 99, 500, 1], vols=[10, 20, 30, 999, 999],
                  secs=[0, 30, 90, 150, 240])

    pa, _ = _prep(early)
    pb, _ = _prep(late)
    fa = behaviour.features_at(pa, behaviour._bucket_table(pa, cfg), 90, cfg)
    fb = behaviour.features_at(pb, behaviour._bucket_table(pb, cfg), 90, cfg)

    for col in ("price_t", "running_low_t", "running_high_t", "n_ticks_t",
                "vol_t", "entry_vs_open_pct", "low_vs_open_pct",
                "time_above_open_frac", "vwap_t"):
        assert np.isclose(fa[col].iloc[0], fb[col].iloc[0], equal_nan=True), col


def test_running_low_never_exceeds_the_price_at_t():
    """`running_low_t <= price_t` by construction — the H004 invariant, restated.

    The running low includes the bar being priced at, so it cannot sit above it.
    A violation means the two were read at different moments.
    """
    cfg = behaviour.BehaviourConfig()
    p, _ = _prep(_ticks(prices=[100, 95, 97, 93, 110]))
    bt = behaviour._bucket_table(p, cfg)
    for t in cfg.offsets_s:
        f = behaviour.features_at(p, bt, t, cfg)
        if f.empty:
            continue
        assert (f["running_low_t"] <= f["price_t"] + 1e-9).all()
        assert (f["running_high_t"] >= f["price_t"] - 1e-9).all()


def test_check_causality_on_the_real_panel_sample():
    """Recompute from physically truncated ticks and require an exact match."""
    cfg = behaviour.BehaviourConfig()
    p, _ = _prep(_ticks())
    bt = behaviour._bucket_table(p, cfg)
    panel = pd.concat([behaviour.features_at(p, bt, t, cfg)
                       for t in (60, 120, 300)], ignore_index=True)
    res = behaviour.check_causality(panel, p, sample=len(panel))
    assert res["ok"], res["examples"]


# --------------------------------------------------------------------------
# the traps this module exists to avoid
# --------------------------------------------------------------------------

def test_shape_features_are_nan_on_a_morning_with_too_few_prints():
    """A thin morning must not produce a confident-looking shape number.

    This is the Phase 2.3 censoring problem in its general form: with three
    prints, "volume was evenly spread" describes the sampling rate, not the
    stock.
    """
    cfg = behaviour.BehaviourConfig(min_bars_for_shape=8)
    p, _ = _prep(_ticks(prices=[100, 101, 102], vols=[1, 1, 1], secs=[0, 60, 120]))
    f = behaviour.features_at(p, behaviour._bucket_table(p, cfg), 300, cfg)
    assert bool(f["sparse_t"].iloc[0])
    for col in ("vol_hhi", "active_bucket_frac", "path_efficiency"):
        assert pd.isna(f[col].iloc[0]), col


def test_time_above_open_is_dwell_weighted_not_tick_counted():
    """Occupancy must weight by how long price stayed, not by how often it printed.

    Otherwise a stock that prints ten times in one second while below its open
    outvotes one that sat above it for four minutes, and the feature becomes a
    liquidity measure — the exact failure it was written to replace.
    """
    cfg = behaviour.BehaviourConfig()
    # Above the open briefly, then a long stretch below it.
    t = _ticks(prices=[101, 101, 99, 99], vols=[1, 1, 1, 1], secs=[0, 5, 10, 300])
    p, _ = _prep(t)
    f = behaviour.features_at(p, behaviour._bucket_table(p, cfg), 300, cfg)
    assert f["time_above_open_frac"].iloc[0] < 0.10
    # Tick-counted would call this a coin flip; dwell-weighted knows better.
    assert f["ticks_above_open_frac"].iloc[0] == pytest.approx(0.5)


def test_volume_hhi_is_comparable_across_entry_times():
    """Evenly-spread volume scores ~0 whether two buckets have elapsed or ten.

    Without the normalisation the statistic falls with `t` mechanically, and
    every comparison across entry times reads the clock instead of the stock.
    """
    cfg = behaviour.BehaviourConfig()
    secs = list(range(0, 300, 5))
    p, _ = _prep(_ticks(prices=[100] * len(secs), vols=[10] * len(secs), secs=secs))
    bt = behaviour._bucket_table(p, cfg)
    vals = [behaviour.features_at(p, bt, t, cfg)["vol_hhi"].iloc[0]
            for t in (60, 150, 300)]
    assert all(abs(v) < 0.05 for v in vals), vals


def test_late_early_ratio_is_scale_free():
    """Doubling every share count must not move the shape statistic."""
    cfg = behaviour.BehaviourConfig()
    secs = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270]
    v = [5, 5, 5, 5, 5, 40, 40, 40, 40, 40]
    a, _ = _prep(_ticks(prices=[100] * 10, vols=v, secs=secs))
    b, _ = _prep(_ticks(prices=[100] * 10, vols=[x * 1000 for x in v], secs=secs))
    fa = behaviour.features_at(a, behaviour._bucket_table(a, cfg), 300, cfg)
    fb = behaviour.features_at(b, behaviour._bucket_table(b, cfg), 300, cfg)
    assert fa["vol_late_early_ratio"].iloc[0] == pytest.approx(
        fb["vol_late_early_ratio"].iloc[0], rel=1e-6)


# --------------------------------------------------------------------------
# the holdout fence
# --------------------------------------------------------------------------

def test_fence_raises_on_holdout_dates():
    """A breach must be loud. Silently filtering would make it invisible."""
    df = pd.DataFrame({"date": pd.to_datetime(["2022-01-05", "2024-01-05"])})
    with pytest.raises(explore.HoldoutBreach):
        explore.fence(df)


def test_fence_passes_inside_the_exploration_window():
    df = pd.DataFrame({"date": pd.to_datetime(["2023-09-01", "2026-01-05"])})
    assert explore.fence(df) is df


def test_fence_raises_when_it_cannot_verify():
    with pytest.raises(explore.HoldoutBreach):
        explore.fence(pd.DataFrame({"symbol": ["AAA"]}))


# --------------------------------------------------------------------------
# inference
# --------------------------------------------------------------------------

def test_clustered_t_is_smaller_than_naive_t_when_dates_are_correlated():
    """The correction has to actually bite, or it is decoration.

    Builds a panel where the whole cross-section moves together each session:
    the effective sample is the number of sessions, not the number of rows, and
    the naive statistic should be visibly overconfident.
    """
    rng = np.random.default_rng(0)
    dates = np.repeat(pd.date_range("2024-01-01", periods=50), 100)
    shock = rng.normal(0, 1, 50).repeat(100)
    y = pd.Series(shock + 0.05)
    s = explore.cluster_stats(y, pd.Series(dates))
    assert abs(s["t"]) < abs(s["naive_t"]) / 2
    assert s["n_dates"] == 50


def test_clustered_t_matches_naive_when_each_date_has_one_row():
    """With no clustering to correct for, the two estimators must agree."""
    rng = np.random.default_rng(1)
    dates = pd.date_range("2024-01-01", periods=300)
    y = pd.Series(rng.normal(0.1, 1, 300))
    s = explore.cluster_stats(y, pd.Series(dates))
    assert s["t"] == pytest.approx(s["naive_t"], rel=0.02)


def test_permutation_null_destroys_a_planted_cross_sectional_effect():
    """The null must break the thing being tested, or it can never reject.

    An earlier version shuffled date-level means and left each row's within-date
    deviation in place, which preserved the cross-sectional signal completely
    and made the test vacuous. This plants an obvious effect and requires the
    permuted maximum to fall well below the observed statistic.
    """
    rng = np.random.default_rng(2)
    n_dates, per = 120, 60
    dates = np.repeat(pd.date_range("2024-01-01", periods=n_dates), per)
    x = rng.normal(size=n_dates * per)
    y = 0.8 * x + rng.normal(size=n_dates * per)
    df = pd.DataFrame({"date": dates, "x": x, "y": y})
    masks = [pd.Series(df["x"] > 0.5), pd.Series(df["x"] < -0.5)]
    obs = max(abs(explore.cluster_stats(df["y"][m], df["date"][m])["t"]) for m in masks)
    res = explore.permutation_max(df, masks, "y", n_perm=30, seed=3)
    assert obs > res["perm_max_t_p95"] * 2


# --------------------------------------------------------------------------
# archetypes
# --------------------------------------------------------------------------

def test_every_row_gets_exactly_one_archetype():
    rng = np.random.default_rng(4)
    n = 500
    df = pd.DataFrame({
        "date": pd.Timestamp("2024-05-02"),
        "n_ticks_t": rng.integers(3, 80, n),
        "entry_vs_open_pct": rng.normal(0, 1, n),
        "high_vs_open_pct": rng.normal(0.5, 1, n).clip(0),
        "low_vs_open_pct": -rng.normal(0.5, 1, n).clip(0),
        "dd_from_high_pct": -rng.normal(0.4, 0.4, n).clip(0),
    })
    for c in ("vol_rel_daily_pct", "active_bucket_frac", "vol_hhi",
              "abs_path_efficiency", "churn_vs_atr", "move_per_vol", "range_pos"):
        df[c + "_xr"] = rng.uniform(size=n)
    lab = archetypes.assign(df)
    assert len(lab) == n
    assert not pd.Series(lab).isna().any()
    assert set(pd.Series(lab).unique()) <= set(archetypes.ARCHETYPES)


def test_inert_takes_precedence_over_every_other_label():
    """A morning with almost no prints cannot honestly be called anything else."""
    df = pd.DataFrame({
        "date": [pd.Timestamp("2024-05-02")],
        "n_ticks_t": [3],
        "entry_vs_open_pct": [1.5], "high_vs_open_pct": [2.0],
        "low_vs_open_pct": [-1.0], "dd_from_high_pct": [-0.5],
    })
    for c in ("vol_rel_daily_pct", "active_bucket_frac", "vol_hhi",
              "abs_path_efficiency", "churn_vs_atr", "move_per_vol", "range_pos"):
        df[c + "_xr"] = 0.99
    assert str(archetypes.assign(df)[0]) == "inert"
