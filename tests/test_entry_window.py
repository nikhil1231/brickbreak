"""The opening window as a function of entry time.

The whole point of this module is one invariant — `stop < running_low_t <=
entry_price` — and the Phase 2.4 bug it exists to prevent. These tests pin the
invariant, pin the no-lookahead rule that makes it true, and pin the separation
between the setup measure and the risk measure that the same bug conflated.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.research.families.opening_window.entry_window import (WindowConfig, add_setup_and_stop, check_invariant,
                              profile, window_grid)


def _ticks(rows, symbol="AAA", day="2024-05-21"):
    """rows: (elapsed_seconds, open, high, low, close)."""
    base = pd.Timestamp(f"{day} 09:15:00")
    return pd.DataFrame({
        "symbol": symbol,
        "date": pd.Timestamp(day),
        "timestamp": [base + pd.Timedelta(seconds=s) for s, *_ in rows],
        "open": [r[1] for r in rows], "high": [r[2] for r in rows],
        "low": [r[3] for r in rows], "close": [r[4] for r in rows],
        "volume": 100,
    })


def _bars(day_open=100.0, symbol="AAA", day="2024-05-21"):
    return pd.DataFrame({"symbol": [symbol], "date": [pd.Timestamp(day)],
                         "open_raw": [day_open], "adj_factor": [1.0]})


def test_running_low_never_exceeds_the_entry_price():
    """The invariant, on a window that falls the whole way through."""
    t = _ticks([(0, 100, 100, 100, 100), (30, 99, 99, 98, 98), (60, 97, 97, 96, 96)])
    g = add_setup_and_stop(window_grid(t, WindowConfig(offsets_s=(30, 60))), _bars())
    assert check_invariant(g)["ok"]
    assert (g["running_low_t"] <= g["price_t"]).all()


def test_no_lookahead_past_the_entry_time():
    """A crash at 09:19 must not move the stop for an entry at 09:16."""
    t = _ticks([(0, 100, 100, 100, 100), (30, 100, 100, 100, 100),
                (240, 100, 100, 50, 50)])
    g = window_grid(t, WindowConfig(offsets_s=(60, 300)))
    at60 = g[g.t_offset_s == 60].iloc[0]
    at300 = g[g.t_offset_s == 300].iloc[0]
    assert at60["running_low_t"] == 100.0
    assert at300["running_low_t"] == 50.0


def test_the_users_worked_example():
    """open 100, running low 99.80, entry 103 -> low 0.2% under open, stop 3.2% under entry.

    The setup being tight says nothing about the stop being tight. This is the
    exact case the Phase 2.4 pairing bug got backwards.
    """
    cfg = WindowConfig(offsets_s=(60,), stop_buffer_pct=0.1)
    t = _ticks([(0, 100, 100, 99.80, 99.90), (60, 100, 103, 99.90, 103.0)])
    g = add_setup_and_stop(window_grid(t, cfg), _bars(day_open=100.0), cfg)
    r = g.iloc[0]
    assert r["running_low_t"] == pytest.approx(99.80)
    assert r["price_t"] == pytest.approx(103.0)
    assert r["low_vs_open_pct"] == pytest.approx(-0.20, abs=1e-6)
    assert r["stop_dist_pct"] == pytest.approx(-3.20, abs=0.02)
    assert check_invariant(g)["ok"]


def test_stop_sits_strictly_below_the_running_low():
    cfg = WindowConfig(offsets_s=(60,), stop_buffer_pct=0.5)
    t = _ticks([(0, 100, 100, 99.0, 100)])
    g = add_setup_and_stop(window_grid(t, cfg), _bars(), cfg)
    assert g["stop_px"].iloc[0] < g["running_low_t"].iloc[0]
    assert g["stop_px"].iloc[0] == pytest.approx(99.0 * 0.995)


def test_invariant_raises_when_the_low_is_read_at_a_different_time():
    """The Phase 2.4 bug, reproduced deliberately: it must not pass silently."""
    t = _ticks([(0, 100, 100, 100, 100), (240, 100, 100, 95, 95)])
    g = add_setup_and_stop(window_grid(t, WindowConfig(offsets_s=(300,))), _bars())
    # Splice in the first-minute low (100) against the 09:20 price (95), which
    # is exactly what pairing `om_low` with `close_5m` did.
    g.loc[:, "running_low_t"] = 100.0
    g.loc[:, "stop_px"] = 100.0 * 0.999
    with pytest.raises(AssertionError, match="different times"):
        check_invariant(g)


def test_running_low_is_monotone_non_increasing_in_t():
    t = _ticks([(0, 100, 100, 100, 100), (60, 100, 100, 99, 99),
                (120, 100, 100, 98, 98), (240, 100, 100, 97, 97)])
    g = window_grid(t, WindowConfig(offsets_s=(30, 60, 120, 300)))
    lows = g.sort_values("t_offset_s")["running_low_t"].tolist()
    assert lows == sorted(lows, reverse=True)


def test_setup_and_risk_are_independent_measures():
    """Same setup (low at the open), two very different stops."""
    cfg = WindowConfig(offsets_s=(60,), stop_buffer_pct=0.0)
    flat = _ticks([(0, 100, 100, 100, 100), (60, 100, 100, 100, 100.2)])
    run = _ticks([(0, 100, 100, 100, 100), (60, 100, 105, 100, 105.0)])
    gf = add_setup_and_stop(window_grid(flat, cfg), _bars(), cfg)
    gr = add_setup_and_stop(window_grid(run, cfg), _bars(), cfg)
    assert gf["low_vs_open_pct"].iloc[0] == pytest.approx(gr["low_vs_open_pct"].iloc[0])
    assert gf["stop_dist_pct"].iloc[0] == pytest.approx(-0.1996, abs=1e-3)
    assert gr["stop_dist_pct"].iloc[0] == pytest.approx(-4.7619, abs=1e-3)


def test_day_open_comes_from_the_bhavcopy_print_not_the_first_tick():
    """Phase 2.3 established these differ; using the tick would redefine the setup."""
    t = _ticks([(0, 104, 104, 103, 104)])       # first tick well above the auction print
    g = add_setup_and_stop(window_grid(t, WindowConfig(offsets_s=(60,))), _bars(day_open=100.0))
    assert g["day_open"].iloc[0] == 100.0
    assert g["low_vs_open_pct"].iloc[0] == pytest.approx(3.0)


def test_profile_reports_every_offset():
    t = _ticks([(0, 100, 100, 100, 100), (60, 100, 101, 99, 100),
                (240, 100, 102, 98, 101)])
    g = add_setup_and_stop(window_grid(t, WindowConfig(offsets_s=(30, 60, 300))), _bars())
    rows = profile(g)
    assert [r["t_offset_s"] for r in rows] == [30, 60, 300]
    assert all(r["n"] == 1 for r in rows)
