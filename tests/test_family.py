"""Tests for `src/family.py`.

This module decides what gets spent on the only clean out-of-sample window this
project has, so the tests are aimed at the things that would corrupt that
decision rather than at coverage:

1. **The purge.** Six blocks of a 30-session hold are only six independent
   periods if no trade's holding window crosses a boundary. If the purge is off
   by one the blocks share information and "positive in five of six" means
   nothing.
2. **The window guards.** A holdout frame that reaches one session into the
   exploration window is a silently part-in-sample result, and the whole point
   of the split is that a breach must raise rather than shrink the frame.
3. **The frozen-definition hash.** Editing a rule after freezing and before
   running the holdout is the failure mode the freeze exists to prevent.
4. **Two-sided book arithmetic.** A short's daily mark is the negation of the
   underlying's, and the round-trip cost is charged twice — once at each end,
   not once per day held.
5. **Causality of the score.** Every feature a frozen rule ranks on must be a
   D-1 quantity. This is the third time in this project a lookahead has been
   found in something that did not look like a price (H015, the `median_vol_20`
   denominator); a test is cheaper than a fourth.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src import asof, family, shotgun
from src.shotgun import ExitConfig


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _frame(n_sessions=12, n_names=4, start="2024-01-01"):
    dates = pd.bdate_range(start, periods=n_sessions)
    rows = []
    for i, d in enumerate(dates):
        for j in range(n_names):
            rows.append({"symbol": f"S{j}", "date": d, "sector": f"SEC{j % 2}",
                         "entry_px_adj": 100.0, "running_low_t_adj": 100.0,
                         "running_high_t_adj": 100.0, "atr_pct": 2.0,
                         "median_tv_20_cr": 10.0, "close_raw": 100.0,
                         "size_tier_rank": 500, "dist_52w_high": -float(j),
                         "deliv_pct": float(j), "f": float(j + i * 0.01)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# the purge
# --------------------------------------------------------------------------

def test_purged_blocks_contain_every_holding_window():
    """No entry may be close enough to a boundary for its hold to cross it."""
    f = _frame(n_sessions=120, n_names=2)
    blocks = family.purged_blocks(f, n_blocks=4, purge=family.HOLD)
    sessions = np.sort(f["date"].unique())
    pos = {s: i for i, s in enumerate(sessions)}
    idx = f["date"].map(pos).to_numpy()
    edges = np.linspace(0, len(sessions), 5).astype(int)
    for b in range(4):
        inside = idx[blocks == b]
        if len(inside) == 0:
            continue
        assert inside.min() >= edges[b]
        # the last entry plus a full hold still lands inside the block
        assert inside.max() + family.HOLD <= edges[b + 1] - 1


def test_purge_drops_the_end_of_each_block_not_the_start():
    f = _frame(n_sessions=40, n_names=1)
    blocks = family.purged_blocks(f, n_blocks=2, purge=5)
    sessions = np.sort(f["date"].unique())
    kept = {b: f.loc[blocks == b, "date"].max() for b in (0, 1)}
    assert f.loc[blocks == 0, "date"].min() == sessions[0]
    assert kept[0] < sessions[len(sessions) // 2 - 1]


# --------------------------------------------------------------------------
# window guards
# --------------------------------------------------------------------------

def test_window_guard_raises_rather_than_filtering():
    f = _frame(n_sessions=3)
    lo, hi = f["date"].min(), f["date"].max()
    family.window_guard(f, lo, hi, "ok")
    with pytest.raises(family.WindowBreach):
        family.window_guard(f, lo, hi - pd.Timedelta(days=1), "short")


def test_holdout_window_ends_before_the_exploration_window_with_a_full_purge():
    start, end = family.holdout_window()
    assert start < end < family.EXPLORE_START
    from src import context
    _, mkt = context.load()
    sess = np.sort(mkt["date"].unique())
    gap = int(((sess >= np.datetime64(end)) &
               (sess < np.datetime64(family.EXPLORE_START))).sum())
    assert gap == family.HOLD + 1     # `end` itself plus HOLD sessions of purge


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------

def test_composite_signs_flip_the_preference():
    f = _frame(n_sessions=2, n_names=4)
    up = family.composite(f, (("f", 1),))
    dn = family.composite(f, (("f", -1),))
    assert np.allclose(up.to_numpy(), -dn.to_numpy())


def test_top_n_selects_within_the_session_not_across_it():
    f = _frame(n_sessions=5, n_names=4)
    rule = family.Rule(name="r", axis="t", thesis="", features=(("f", 1),), long_n=2)
    longs, _ = family.sides(f, rule)
    per_day = f[longs].groupby("date").size()
    assert (per_day == 2).all()


def test_per_sector_cap_thins_before_the_top_n_cut():
    """One name per sector, then the top N — never the other way round."""
    f = _frame(n_sessions=3, n_names=4)      # SEC0: S0,S2  SEC1: S1,S3
    rule = family.Rule(name="r", axis="t", thesis="", features=(("f", 1),),
                       long_n=2, per_sector=1)
    longs, _ = family.sides(f, rule)
    picked = f[longs]
    assert (picked.groupby(["date", "sector"]).size() == 1).all()
    assert (picked.groupby("date").size() == 2).all()


def test_gate_restricts_selection_without_shrinking_the_pool():
    f = _frame(n_sessions=4, n_names=4)
    f["mkt_vs_ema50_pct"] = np.where(f["date"] == f["date"].min(), -1.0, 1.0)
    rule = family.Rule(name="r", axis="t", thesis="", features=(("f", 1),),
                       long_n=2, gate="mkt_below_ema50")
    longs, _ = family.sides(f, rule)
    assert f.loc[longs, "date"].nunique() == 1


# --------------------------------------------------------------------------
# book arithmetic
# --------------------------------------------------------------------------

def _one_trade_paths(closes, monkeypatch, entry=100.0):
    """One tradeable row per session, so the book has a full calendar.

    The book indexes sessions off the frame it is given and truncates a trade at
    the frame's last session — which is correct (a window cannot mark a position
    it has no sessions for) but makes a one-row frame a bad test bed for the
    cost arithmetic.
    """
    n = len(closes)
    dates = pd.bdate_range("2024-01-01", periods=n)
    c = np.asarray(closes, dtype=float)
    bars = pd.DataFrame({"symbol": "AAA", "date": dates, "open": c,
                         "high": c, "low": c, "close": c})
    trade = pd.DataFrame({"symbol": "AAA", "date": dates,
                          "entry_px_adj": entry, "running_low_t_adj": entry,
                          "running_high_t_adj": entry, "atr_pct": 2.0})
    monkeypatch.setattr(pd, "read_parquet", lambda *a, **k: bars.copy())
    return trade, shotgun.build_paths(trade, horizon=n - 1, verbose=False)


def test_short_book_return_is_the_negation_of_the_long_book(monkeypatch):
    trade, paths = _one_trade_paths([100, 102, 104], monkeypatch)
    cfg = ExitConfig(stop_atr=None, target_pct=None, trail_ema=None, time_stop=2)
    sl = shotgun.simulate(paths, cfg)
    ss = shotgun.simulate(paths, family.replace(cfg, direction=-1))
    one = np.array([True, False, False])
    zero = np.zeros(3, bool)
    rl, _ = family.book(trade, paths, sl, ss, one, zero, cost_pct=0.0)
    rs, _ = family.book(trade, paths, sl, ss, zero, one, cost_pct=0.0)
    assert np.allclose(rl[:1], -rs[:1])


def test_cost_is_charged_twice_not_once_per_day(monkeypatch):
    trade, paths = _one_trade_paths([100, 100, 100, 100], monkeypatch)
    cfg = ExitConfig(stop_atr=None, target_pct=None, trail_ema=None, time_stop=3)
    sl = shotgun.simulate(paths, cfg)
    ss = shotgun.simulate(paths, family.replace(cfg, direction=-1))
    one = np.array([True, False, False, False])
    zero = np.zeros(4, bool)
    r, w = family.book(trade, paths, sl, ss, one, zero, cost_pct=1.0)
    assert r[w > 0].sum() == pytest.approx(-0.01, abs=1e-9)


def test_market_book_matches_the_books_own_calendar_span():
    """A block's market comparison must not be measured over the whole window."""
    f = _frame(n_sessions=60, n_names=1)
    sessions = np.sort(f["date"].unique())
    curve = pd.Series(np.linspace(0, 0.6, len(sessions)), index=sessions)
    live = np.zeros(len(sessions), bool)
    live[:30] = True
    whole = family.market_book(f, curve)
    part = family.market_book(f, curve, live=live)
    assert part["sessions"] == 30 and whole["sessions"] == 60
    assert part["total_pct"] < whole["total_pct"]


def test_a_book_that_sits_in_cash_is_charged_for_it():
    """The span convention: flat sessions earn nothing and still count.

    Under the old live-sessions-only convention a rule deployed half the time
    reported the return it made while deployed as if it had made it all year,
    which flatters a timing rule against an always-invested one and makes the
    two incomparable under one Sharpe bar.
    """
    r = np.full(100, 0.001)
    always = family.span_stats(r, np.ones(100))
    half = family.span_stats(r, np.tile([1.0, 0.0], 50))
    # the span ends on the last live session, so half of 99 sessions is 50.5%
    assert always["deployed_pct"] == 100.0
    assert half["deployed_pct"] == pytest.approx(50.5, abs=0.1)
    assert half["total_pct"] < always["total_pct"]
    assert half["cagr_pct"] < always["cagr_pct"]


# --------------------------------------------------------------------------
# the freeze
# --------------------------------------------------------------------------

def test_rules_hash_changes_when_a_definition_changes():
    a = family.Rule(name="r", axis="t", thesis="", features=(("f", 1),), long_n=5)
    b = family.replace(a, long_n=6)
    assert family.rules_hash([a]) != family.rules_hash([b])
    assert family.rules_hash([a]) == family.rules_hash([family.from_dict(a.to_dict())])


def test_holdout_refuses_a_family_that_was_edited_after_freezing(tmp_path):
    r = family.Rule(name="r", axis="t", thesis="", features=(("f", 1),), long_n=5)
    p = tmp_path / "frozen.json"
    p.write_text(json.dumps({"members": [r.to_dict()], "information_only": [],
                             "detail": {}, "pass_criterion": family.PASS_CRITERION,
                             "rules_hash": "deadbeefdeadbeef"}))
    # the guard fires on the *frozen* file, so point the loader at the fake one
    # rather than at the project's own — calling the real thing here would open
    # the holdout as a side effect of running the test suite.
    import src.family as fam
    orig = fam.load_frozen
    fam.load_frozen = lambda path=p: json.loads(p.read_text())
    try:
        with pytest.raises(RuntimeError, match="hash"):
            fam.holdout(verbose=False, path=tmp_path / "out.json")
    finally:
        fam.load_frozen = orig


def test_holdout_refuses_to_overwrite_a_result_from_another_family(tmp_path):
    r = family.Rule(name="r", axis="t", thesis="", features=(("f", 1),), long_n=5)
    frozen = {"members": [r.to_dict()], "information_only": [], "detail": {},
              "pass_criterion": family.PASS_CRITERION,
              "rules_hash": family.rules_hash([r])}
    fp, op = tmp_path / "frozen.json", tmp_path / "out.json"
    fp.write_text(json.dumps(frozen))
    op.write_text(json.dumps({"rules_hash": "0000000000000000"}))
    import src.family as fam
    orig = fam.load_frozen
    fam.load_frozen = lambda path=fp: json.loads(fp.read_text())
    try:
        with pytest.raises(RuntimeError, match="spent"):
            fam.holdout(verbose=False, path=op)
    finally:
        fam.load_frozen = orig


# --------------------------------------------------------------------------
# causality
# --------------------------------------------------------------------------

def test_every_frozen_feature_is_a_d_minus_one_quantity():
    """No score may rank on something only knowable after the entry.

    `asof.KNOWN_AT_OPEN` lists what a morning rule may read on date D. This
    module enters *at* the opening print, so even the open itself is off limits
    as a feature, and every column any rule ranks on must be one the as-of panel
    lags — or a trailing context column, which `context.py` shifts by a session.
    """
    if not family.FROZEN_PATH.exists():
        pytest.skip("no frozen family yet")
    frozen = json.loads(family.FROZEN_PATH.read_text())
    import pyarrow.parquet as pq
    allowed = set(family.TRAILING_CTX)
    lagged = set(pq.ParquetFile(
        family.build_screen.METRICS_ASOF_PATH).schema_arrow.names) - set(asof.KNOWN_AT_OPEN)
    for spec in frozen["members"] + frozen["information_only"]:
        for col, _ in spec["features"]:
            assert col in allowed or col in lagged, (
                f"{spec['name']} ranks on {col!r}, which is not a D-1 quantity")
