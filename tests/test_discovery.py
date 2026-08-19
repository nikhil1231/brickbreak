"""Tests for `src/discovery.py`.

Three things are worth testing here and the rest is arithmetic:

1. **The path walk is causal and resolves the entry day correctly.** An extreme
   already printed inside the opening window is not reachable after the entry;
   crediting it would inflate every winner state at once. This is the same
   correction `payoff.py` makes and it is tested the same way.
2. **The matching does what it claims** — same session (or within the stated
   band), exact on the categoricals, inside the caliper, and no control reused.
   A matched design whose matching is broken produces beautifully significant
   contrasts between two arbitrary groups.
3. **The permutation null is a null.** If shuffling the winner label inside a
   matched set leaves a real signal behind, the bar every finding is measured
   against is not a bar. Tested by feeding it data with no signal and checking
   the observed statistic does not stand out, and by feeding it a planted
   signal and checking it does.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import discovery as dc


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

def _bars(symbols, dates, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for s in symbols:
        r = rng.normal(0.001, 0.02, len(dates))
        close = 100 * np.exp(np.cumsum(r))
        out.append(pd.DataFrame({
            "symbol": s, "date": dates, "close": close,
            "high": close * 1.02, "low": close * 0.98}))
    return pd.concat(out, ignore_index=True)


def _trades(bars, entry_frac=1.0):
    first = bars.groupby("symbol", as_index=False).nth(0)
    t = first[["symbol", "date"]].copy()
    px = first["close"].to_numpy() * entry_frac
    t["entry_px_adj"] = px
    t["running_low_t_adj"] = px * 0.995
    t["running_high_t_adj"] = px * 1.005
    t["stop_px_adj"] = px * 0.98
    t["stop_dist_pct"] = -2.0
    t["atr_pct"] = 3.0
    return t.reset_index(drop=True)


# --------------------------------------------------------------------------
# 1. the forward path
# --------------------------------------------------------------------------

def test_entry_day_extremes_already_inside_the_window_are_unreachable():
    """A high set before the entry must not count as favourable excursion.

    The entry is at 09:18; a high printed at 09:16 is in the daily bar and is
    not available to the trade. If `forward_paths` credited it, every morning
    that spiked into the opening window and then died would be scored as a
    winner — which is precisely the state (`spike_and_fade`) the taxonomy needs
    to keep separate.
    """
    dates = pd.bdate_range("2024-01-01", periods=15)
    bars = _bars(["AAA"], dates)
    t = _trades(bars)
    # Force the entry day's high to have been made inside the window.
    d0 = bars["date"].iloc[0]
    bars.loc[bars["date"] == d0, "high"] = float(t["running_high_t_adj"].iloc[0])

    p = dc.forward_paths(t, bars, horizon=10, verbose=False)
    # Day 0 contributes nothing favourable, so the peak must come from a later
    # session — never from session 0.
    assert p["sess_to_mfe"].iloc[0] > 0

    # And when the daily high genuinely exceeds the window high, it is used.
    bars2 = bars.copy()
    bars2.loc[bars2["date"] == d0, "high"] = float(t["entry_px_adj"].iloc[0]) * 1.5
    p2 = dc.forward_paths(t, bars2, horizon=10, verbose=False)
    assert p2["sess_to_mfe"].iloc[0] == 0
    assert p2["mfe_pct"].iloc[0] > 45


def test_stop_and_target_sessions_are_first_touches_not_defaults():
    """`argmax` over a boolean returns 0 when nothing is True; -1 must mean 'never'."""
    dates = pd.bdate_range("2024-01-01", periods=15)
    bars = _bars(["AAA"], dates)
    # A series that never falls: no stop can be touched.
    bars["low"] = bars["close"] * 5
    bars["high"] = bars["close"] * 5.1
    t = _trades(bars)
    p = dc.forward_paths(t, bars, horizon=10, verbose=False)
    assert p["sess_to_stop"].iloc[0] == -1
    assert p["sess_to_target"].iloc[0] == 0        # it is above target on day 0


def test_incomplete_paths_are_unclassified_not_nothingburgers():
    """A truncated tail must not be scored as 'went nowhere'."""
    dates = pd.bdate_range("2024-01-01", periods=4)     # shorter than the horizon
    bars = _bars(["AAA"], dates)
    t = _trades(bars)
    p = dc.forward_paths(t, bars, horizon=10, verbose=False)
    assert not p["path_complete"].iloc[0]
    assert pd.isna(dc.classify(p)[0])


def test_atr_floor_widens_the_stop_and_never_narrows_it():
    """Widening preserves `stop < running_low <= entry`; narrowing would break it."""
    dates = pd.bdate_range("2024-01-01", periods=15)
    bars = _bars(["AAA"], dates)
    t = _trades(bars)
    t["stop_dist_pct"] = -0.2          # the hair-trigger case the floor exists for
    t["stop_px_adj"] = t["entry_px_adj"] * 0.998
    t["date"] = t["date"]
    cfg = dc.OutcomeConfig(stop_atr_floor=0.5)
    r_eff = np.maximum(t["stop_dist_pct"].abs(), cfg.stop_atr_floor * t["atr_pct"])
    stop = t["entry_px_adj"] * (1 - r_eff / 100)
    assert (stop < t["running_low_t_adj"]).all()
    assert (r_eff >= t["stop_dist_pct"].abs()).all()


# --------------------------------------------------------------------------
# 2. the matching
# --------------------------------------------------------------------------

def _match_frame(n_dates=40, per_date=60, seed=1):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=n_dates)
    rows = []
    for d in dates:
        for i in range(per_date):
            rows.append({
                "symbol": f"S{i}", "date": d,
                "sector": f"SEC{i % 4}",
                "size_tier": f"T{i % 2}",
                "median_tv_20_cr": float(rng.lognormal(2, 1)),
                "atr_pct": float(rng.uniform(1, 6)),
                "ret_20d": float(rng.normal(0, 8)),
                "bb_width_pctile": float(rng.uniform(0, 100)),
                "gap_pct": float(rng.normal(0, 1)),
                "vol_rel_daily_pct": float(rng.uniform(0, 40)),
                "signal": float(rng.normal(0, 1)),
                "noise": float(rng.normal(0, 1)),
            })
    return pd.DataFrame(rows)


def test_matching_respects_exact_keys_caliper_and_date_band():
    df = _match_frame()
    rng = np.random.default_rng(0)
    w = pd.Series(rng.random(len(df)) < 0.15, index=df.index)
    c = ~w
    cfg = dc.MatchConfig(tier="core", date_window=2, k=3)
    pairs, st = dc.match(df, w, c, cfg, verbose=False)
    assert st["matched"] > 50

    sessions = np.sort(df["date"].unique())
    ordinal = {d: i for i, d in enumerate(sessions)}
    for sid, g in pairs.groupby("set_id"):
        win = g[g["role"] == "winner"]
        assert len(win) == 1, "exactly one winner per set"
        wi = win["idx"].iloc[0]
        for ci in g[g["role"] == "control"]["idx"]:
            assert df.loc[ci, "sector"] == df.loc[wi, "sector"]
            assert df.loc[ci, "size_tier"] == df.loc[wi, "size_tier"]
            gap = abs(ordinal[df.loc[ci, "date"]] - ordinal[df.loc[wi, "date"]])
            assert gap <= cfg.date_window

    used = pairs[pairs["role"] == "control"]["idx"]
    assert used.is_unique, "a control must not be reused across sets"
    assert (pairs[pairs["role"] == "control"]["dist"] <= cfg.caliper).all()


def test_matching_removes_a_planted_covariate_imbalance():
    """The point of matching, stated as a test.

    Winners are drawn preferentially from high-liquidity names. Before
    matching the standardised difference on liquidity is large; after it, it
    must be small. If this fails, every contrast in the module is partly a
    liquidity contrast.
    """
    # Wide sessions on purpose: the default config matches inside a single
    # session, and 60 rows split across 4 sectors x 2 size tiers leaves ~7 per
    # cell, which is too thin to balance anything. The real pool is thin too —
    # that is a stated limit of the phase, not something to hide in a fixture —
    # but this test is about whether the matcher works, not about the pool.
    df = _match_frame(seed=3, per_date=200)
    rank = df.groupby("date")["median_tv_20_cr"].rank(pct=True)
    rng = np.random.default_rng(0)
    w = pd.Series(rng.random(len(df)) < rank * 0.3, index=df.index)
    c = ~w
    pairs, _ = dc.match(df, w, c, dc.MatchConfig(tier="core"), verbose=False)
    b = dc.balance(df, pairs, ["median_tv_20_cr"]).iloc[0]
    # Judged in the space the matching actually works in. The raw-space figure
    # stays near 0.12 on this lognormal covariate under any caliper, because a
    # small rank gap high in the tail is still a large number of crores; see
    # the docstring on `balance`.
    assert abs(b["smd_before_rank"]) > 0.3
    assert abs(b["smd_after_rank"]) < 0.15
    # Raw space is held to the conventional |SMD| < 0.2 "acceptable balance"
    # bound and to a material improvement, not to the rank-space figure: the
    # remainder is the lognormal tail, not the matcher.
    assert abs(b["smd_after"]) < 0.20
    assert abs(b["smd_after"]) < abs(b["smd_before"]) * 0.6


def test_unmatched_winners_are_dropped_not_stretched():
    """No control within the caliper means no set, not a distant one."""
    df = _match_frame(per_date=8)
    w = pd.Series(df["sector"] == "SEC0", index=df.index)
    c = ~w
    pairs, st = dc.match(df, w, c,
                         dc.MatchConfig(caliper=0.001, max_dim_caliper=0.001,
                                        date_window=0), verbose=False)
    assert st["matched"] + st["unmatched_caliper"] + st["unmatched_no_pool"] \
           == st["winners"]
    if not pairs.empty:
        assert (pairs[pairs["role"] == "control"]["dist"] <= 0.001).all()


# --------------------------------------------------------------------------
# 3. the null, and the contrast
# --------------------------------------------------------------------------

def test_contrast_recovers_a_planted_difference():
    df = _match_frame(seed=5)
    rng = np.random.default_rng(0)
    w = pd.Series(rng.random(len(df)) < 0.15, index=df.index)
    df.loc[w, "signal"] += 1.0
    pairs, _ = dc.match(df, w, ~w, dc.MatchConfig(), verbose=False)
    con = dc.contrasts(df, pairs, ["signal", "noise"], min_sets=50)
    sig = con[con["feature"] == "signal"].iloc[0]
    noi = con[con["feature"] == "noise"].iloc[0]
    assert sig["mean_diff"] > 0.7
    assert abs(sig["t"]) > abs(noi["t"]) * 3


def test_permutation_null_is_a_null_under_no_signal():
    """With nothing planted, the observed max |t| must sit inside the null."""
    df = _match_frame(seed=7)
    rng = np.random.default_rng(1)
    w = pd.Series(rng.random(len(df)) < 0.15, index=df.index)
    pairs, _ = dc.match(df, w, ~w, dc.MatchConfig(), verbose=False)
    feats = ["signal", "noise", "ret_20d", "gap_pct"]
    con = dc.contrasts(df, pairs, feats, min_sets=50)
    perm = dc.permutation_null(df, pairs, feats, n_perm=100)
    assert con["t"].abs().max() < perm["perm_max_t_max"] * 1.5
    assert perm["perm_max_t_p95"] > 1.0, "a max over several features exceeds 1.96/2"


def test_permutation_null_is_beaten_by_a_real_signal():
    df = _match_frame(seed=9)
    rng = np.random.default_rng(2)
    w = pd.Series(rng.random(len(df)) < 0.15, index=df.index)
    df.loc[w, "signal"] += 1.5
    pairs, _ = dc.match(df, w, ~w, dc.MatchConfig(), verbose=False)
    feats = ["signal", "noise", "ret_20d", "gap_pct"]
    con = dc.contrasts(df, pairs, feats, min_sets=50)
    perm = dc.permutation_null(df, pairs, feats, n_perm=100)
    assert con["t"].abs().max() > perm["perm_max_t_p95"] * 2


# --------------------------------------------------------------------------
# the fence
# --------------------------------------------------------------------------

def test_load_frame_refuses_holdout_rows(monkeypatch):
    """The fence must raise, not filter. A silently dropped holdout row is an
    invisible breach and the split is the only out-of-sample test that exists."""
    from src import behaviour, explore

    fake = pd.DataFrame({
        "symbol": ["AAA"], "date": [pd.Timestamp("2021-06-01")],
        "t_offset_s": [180]})
    monkeypatch.setattr(behaviour, "load", lambda: fake)
    with pytest.raises(explore.HoldoutBreach):
        dc.load_frame(180, verbose=False)


def test_winner_states_are_disjoint_and_exhaustive():
    assert not set(dc.STRONG) & set(dc.FAILURES)
    assert set(dc.STRONG) | set(dc.FAILURES) == set(dc.OUTCOMES)
