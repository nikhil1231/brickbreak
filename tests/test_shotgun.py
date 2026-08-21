"""Tests for `src.research.opening_window.shotgun`.

This module became load-bearing the moment it produced a positive result, so the
things that would make that result fake are tested directly:

1. **The short leg.** Mirroring the price axis is easy to get subtly wrong, and
   the natural-looking `exit / entry - 1` returns the *long* P&L for a short.
   A sweep that reported longs' returns under a short label would have found
   "alpha" in a bull market on the first try.
2. **Gap-through fills.** A stop sweep that assumes every stop fills exactly at
   its level is a sweep over an instrument that never gaps, and wide stops look
   better than they are.
3. **`trail_from`.** Trailing from entry rather than from the target is a
   completely different rule — it exits 47% of trades at a median hold of 2
   sessions against 5 — and conflating them broke the first validation against
   `payoff.simulate`.
4. **The benchmark sign.** Alpha is `r - m` for a long and `r + m` for a short.
   Getting this wrong inverted an entire sweep before it was caught.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.opening_window import shotgun as sg


def _frame(closes, opens=None, highs=None, lows=None, entry=100.0):
    """One symbol, one trade, a hand-written forward path."""
    n = len(closes)
    dates = pd.bdate_range("2024-01-01", periods=n)
    c = np.asarray(closes, dtype=float)
    df = pd.DataFrame({
        "symbol": "AAA", "date": dates,
        "open": c if opens is None else np.asarray(opens, dtype=float),
        "high": c if highs is None else np.asarray(highs, dtype=float),
        "low": c if lows is None else np.asarray(lows, dtype=float),
        "close": c,
    })
    trade = pd.DataFrame({
        "symbol": ["AAA"], "date": [dates[0]], "entry_px_adj": [entry],
        "running_low_t_adj": [entry], "running_high_t_adj": [entry],
        "atr_pct": [2.0],
    })
    return df, trade


def _paths(bars, trade, monkeypatch, horizon=10):
    """`build_paths` reads the panel from disk; feed it the synthetic one."""
    monkeypatch.setattr(pd, "read_parquet", lambda *a, **k: bars.copy())
    return sg.build_paths(trade, horizon=horizon, verbose=False)


# --------------------------------------------------------------------------
# direction
# --------------------------------------------------------------------------

def test_short_pnl_is_the_negative_of_the_long_pnl(monkeypatch):
    """A falling stock must pay a short and cost a long, symmetrically."""
    bars, trade = _frame([100, 98, 96, 94, 92, 90, 90, 90, 90, 90, 90])
    p = _paths(bars, trade, monkeypatch)
    base = dict(stop_atr=None, target_pct=None, trail_ema=None, time_stop=5)
    lng = sg.simulate(p, sg.ExitConfig(**base, direction=1))["ret_pct"][0]
    sht = sg.simulate(p, sg.ExitConfig(**base, direction=-1))["ret_pct"][0]
    assert lng == pytest.approx(-10.0, abs=1e-6)
    assert sht == pytest.approx(+10.0, abs=1e-6)


def test_short_stop_is_above_the_entry(monkeypatch):
    """For a short, adverse is *up*. A rising stock must stop the short out.

    The session opens *below* the 102 stop and trades through it intraday, so
    the fill is at the stop. A session that opened above it would fill at the
    open instead — that is the gap-through case, tested separately.
    """
    bars, trade = _frame(closes=[100, 104, 110, 115, 120, 125],
                         opens=[100, 101, 110, 115, 120, 125],
                         highs=[100, 105, 111, 116, 121, 126],
                         lows=[100, 101, 109, 114, 119, 124])
    p = _paths(bars, trade, monkeypatch, horizon=5)
    # 1 x ATR = 2%, so the stop sits at 102 and session 1 trades through it.
    r = sg.simulate(p, sg.ExitConfig(stop_atr=1.0, target_pct=None,
                                     trail_ema=None, time_stop=5, direction=-1))
    assert r["reason"][0] == "stop"
    assert r["ret_pct"][0] == pytest.approx(-2.0, abs=1e-6)


# --------------------------------------------------------------------------
# fills
# --------------------------------------------------------------------------

def test_a_session_gapping_through_the_stop_fills_at_the_open(monkeypatch):
    """The stop is not a guaranteed price. Ignoring this flatters wide stops."""
    # Day 1 opens at 90, far below a 98 stop, and never trades back up.
    bars, trade = _frame(closes=[100, 90, 90, 90, 90, 90],
                         opens=[100, 90, 90, 90, 90, 90],
                         highs=[100, 91, 91, 91, 91, 91],
                         lows=[100, 89, 89, 89, 89, 89])
    p = _paths(bars, trade, monkeypatch, horizon=5)
    r = sg.simulate(p, sg.ExitConfig(stop_atr=1.0, target_pct=None,
                                     trail_ema=None, time_stop=5, direction=1))
    assert r["reason"][0] == "stop"
    # Filled at 90, not at the 98 stop.
    assert r["ret_pct"][0] == pytest.approx(-10.0, abs=1e-6)


def test_entry_day_extremes_inside_the_window_cannot_trigger_an_exit(monkeypatch):
    """The H004 error again: a low printed before the entry is not reachable.

    The distinction is carried by `running_low_t_adj`. When the day's low equals
    the opening window's running low, the low happened *inside* the window,
    before the position existed, and cannot fill a stop. When the day's low is
    strictly below it, the low came after the entry and can.
    """
    bars, trade = _frame(closes=[100, 100, 100, 100, 100, 100],
                         lows=[80, 100, 100, 100, 100, 100],
                         highs=[100, 100, 100, 100, 100, 100])
    # The window itself made the 80: unreachable after a 100 entry.
    trade.loc[0, "running_low_t_adj"] = 80.0
    p = _paths(bars, trade, monkeypatch, horizon=5)
    r = sg.simulate(p, sg.ExitConfig(stop_atr=1.0, target_pct=None,
                                     trail_ema=None, time_stop=5, direction=1))
    assert r["reason"][0] != "stop", "an entry-day low before the entry hit the stop"

    # Same bars, but the window low was 100, so the 80 printed after entry.
    trade.loc[0, "running_low_t_adj"] = 100.0
    p2 = _paths(bars, trade, monkeypatch, horizon=5)
    r2 = sg.simulate(p2, sg.ExitConfig(stop_atr=1.0, target_pct=None,
                                       trail_ema=None, time_stop=5, direction=1))
    assert r2["reason"][0] == "stop"


# --------------------------------------------------------------------------
# the trail
# --------------------------------------------------------------------------

def test_trail_from_target_cannot_exit_before_the_target(monkeypatch):
    """Under the stated rule the trail arms only on the remainder."""
    # Drifts down steadily: an entry-armed trail fires early, a target-armed
    # one never arms because the target is never reached.
    bars, trade = _frame([100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90])
    p = _paths(bars, trade, monkeypatch)
    tgt = sg.simulate(p, sg.ExitConfig(stop_atr=None, target_pct=50.0,
                                       trail_ema=10, trail_from="target",
                                       time_stop=10))
    ent = sg.simulate(p, sg.ExitConfig(stop_atr=None, target_pct=50.0,
                                       trail_ema=10, trail_from="entry",
                                       time_stop=10))
    assert tgt["reason"][0] == "time"
    assert ent["reason"][0] == "trail"
    assert ent["held"][0] < tgt["held"][0]


def test_target_scales_out_and_the_remainder_keeps_running(monkeypatch):
    """Half at the target, half to the time stop — the blend, not one or other."""
    bars, trade = _frame([100, 120, 130, 140, 150, 160])
    p = _paths(bars, trade, monkeypatch, horizon=5)
    r = sg.simulate(p, sg.ExitConfig(stop_atr=None, target_pct=15.0,
                                     scale_out=0.5, trail_ema=None, time_stop=5))
    assert r["reason"][0] == "target"
    # 0.5 * 15% + 0.5 * 60% = 37.5%
    assert r["ret_pct"][0] == pytest.approx(37.5, abs=1e-6)


# --------------------------------------------------------------------------
# the benchmark
# --------------------------------------------------------------------------

def test_benchmark_sign_follows_the_position():
    """Alpha is r - m for a long and r + m for a short.

    Subtracting the market from a short charges it for the market twice, and in
    a single rising sample that is enough to rank shorts by how badly the market
    did rather than by anything they earned.
    """
    dates = pd.bdate_range("2024-01-01", periods=5)
    curve = pd.Series(np.log([1.0, 1.01, 1.02, 1.03, 1.04]), index=dates)
    paths = {"date": np.array([dates[0]])}
    sim = {"ret_pct": np.array([5.0]), "held": np.array([2])}
    lng = sg.attach_excess(paths, sim, curve, direction=1)[0]
    sht = sg.attach_excess(paths, sim, curve, direction=-1)[0]
    m = (np.exp(curve.iloc[2] - curve.iloc[0]) - 1) * 100
    assert lng == pytest.approx(5.0 - m, abs=1e-9)
    assert sht == pytest.approx(5.0 + m, abs=1e-9)


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------

def test_top_n_per_day_selects_within_each_session_and_respects_the_gate():
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2024-01-01", periods=10)
    df = pd.DataFrame({"date": np.repeat(dates, 20),
                       "score": rng.random(200),
                       "ok": rng.random(200) < 0.5})
    m = sg.top_n_per_day(df, "score", 3)
    assert m.sum() == 30
    assert (df[m].groupby("date").size() == 3).all()
    # The chosen rows are the session's highest scores.
    for d0, g in df[m].groupby("date"):
        assert g["score"].min() >= df[df["date"] == d0]["score"].nlargest(3).min()

    gated = sg.top_n_per_day(df, "score", 3, gate=df["ok"].to_numpy())
    assert df.loc[gated, "ok"].all(), "a gated-out row was selected"


def test_top_n_never_exceeds_what_a_thin_session_offers():
    dates = pd.bdate_range("2024-01-01", periods=3)
    df = pd.DataFrame({"date": np.repeat(dates, 2), "score": np.arange(6.0)})
    m = sg.top_n_per_day(df, "score", 5)
    assert m.sum() == 6
