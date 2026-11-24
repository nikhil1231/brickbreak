"""The extracted bracket simulator, and the entry-day rule that makes it exact.

`alpha_eval.trade_sim` was lifted out of the opening-window family on
2026-08-22. Two things have to hold afterwards:

1. the family's recorded measurements are unchanged — its wrapper must produce
   what the original produced, which is what pins the extraction; and
2. the generalisation is *exact* rather than approximate. Entry timing decides
   which of the entry day's extremes the position could have met, and every
   branch of that decision is a certainty, not an assumption. Getting it wrong
   is the H004 error (a stop above an entry), which this project has shipped
   once already.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.alpha_eval import trade_sim


def _flat_bars(symbols=("AAA",), n=30, start=100.0, step=0.0):
    dates = pd.bdate_range("2024-01-01", periods=n)
    rows = []
    for s in symbols:
        px = start
        for d in dates:
            rows.append({"symbol": s, "date": d, "open": px, "high": px * 1.02,
                         "low": px * 0.98, "close": px})
            px *= (1.0 + step)
    return pd.DataFrame(rows), dates


def test_entry_at_the_open_can_meet_the_entry_day_low():
    """Filled on the opening print, the whole session is post-entry.

    A stop below the entry day's low must be reachable that same day. Treating
    the entry day as unreachable is the bias that flatters every stop.
    """
    bars, dates = _flat_bars(n=20)
    # low is 98; a stop at 99 sits above it and must fill on the entry day.
    trades = pd.DataFrame([{"symbol": "AAA", "date": dates[2],
                            "entry_px_adj": 100.0, "stop_px_adj": 99.0}])
    out = trade_sim.simulate(trades, bars, entry_timing="open")
    assert out["exit_reason"].iloc[0] == trade_sim.STOP
    assert out["sessions_held"].iloc[0] == 0


def test_entry_at_the_close_cannot_meet_the_entry_day_low():
    """Filled on the close, none of date D is reachable — the mirror case."""
    bars, dates = _flat_bars(n=20)
    trades = pd.DataFrame([{"symbol": "AAA", "date": dates[2],
                            "entry_px_adj": 100.0, "stop_px_adj": 99.0}])
    out = trade_sim.simulate(trades, bars, entry_timing="close")
    # It still stops out — but not until the following session, not on D.
    assert out["sessions_held"].iloc[0] >= 1


def test_intraday_window_without_its_extremes_is_refused():
    """The opening-window mode is exact *because* of those columns.

    Silently defaulting them would reintroduce H004 — reading the low and the
    entry price at different moments — with no visible symptom.
    """
    bars, dates = _flat_bars(n=20)
    trades = pd.DataFrame([{"symbol": "AAA", "date": dates[2],
                            "entry_px_adj": 100.0, "stop_px_adj": 99.0}])
    with pytest.raises(ValueError, match="running_low_t"):
        trade_sim.simulate(trades, bars, entry_timing="intraday_window")


def test_unknown_entry_timing_is_refused():
    bars, dates = _flat_bars(n=20)
    trades = pd.DataFrame([{"symbol": "AAA", "date": dates[2],
                            "entry_px_adj": 100.0, "stop_px_adj": 99.0}])
    with pytest.raises(ValueError, match="entry_timing"):
        trade_sim.simulate(trades, bars, entry_timing="whenever")


def test_a_gap_below_the_stop_fills_at_the_open_not_the_stop():
    """A stop is not a fill. This is where much of the real loss lives."""
    dates = pd.bdate_range("2024-01-01", periods=10)
    rows = []
    for i, d in enumerate(dates):
        px = 100.0 if i < 3 else 80.0        # a gap down on session 3
        rows.append({"symbol": "AAA", "date": d, "open": px, "high": px,
                     "low": px, "close": px})
    bars = pd.DataFrame(rows)
    trades = pd.DataFrame([{"symbol": "AAA", "date": dates[2],
                            "entry_px_adj": 100.0, "stop_px_adj": 95.0}])
    out = trade_sim.simulate(trades, bars, entry_timing="close")
    assert out["exit_reason"].iloc[0] == trade_sim.STOP_GAP
    # Filled at 80, not at the 95 stop that never traded.
    assert out["payoff_ret_pct"].iloc[0] == pytest.approx(-20.0, abs=1e-6)


def test_the_bracket_is_a_width_not_a_number():
    """A session touching both levels is undetermined, and must be reported so."""
    dates = pd.bdate_range("2024-01-01", periods=15)
    rows = []
    for d in dates:
        # A wide session that reaches both a -5% stop and a +15% target.
        rows.append({"symbol": "AAA", "date": d, "open": 100.0, "high": 116.0,
                     "low": 94.0, "close": 100.0})
    bars = pd.DataFrame(rows)
    trades = pd.DataFrame([{"symbol": "AAA", "date": dates[1],
                            "entry_px_adj": 100.0, "stop_px_adj": 95.0}])
    summary, pes, opt = trade_sim.bracket(trades, bars, entry_timing="open",
                                          min_symbols=1)
    assert summary["trades_whose_outcome_the_data_cannot_resolve"] == 1
    assert summary["share_unresolved_pct"] == 100.0
    assert summary["optimistic"]["mean_pct"] > summary["pessimistic"]["mean_pct"]
    assert summary["bracket_width_pct"] > 0
    assert summary["entry_timing"] == "open"
