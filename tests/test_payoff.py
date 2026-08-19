"""Tests for the stop/target/trail payoff simulator (H017).

Every case here is a hand-built price path with a known right answer. The
simulator's failure mode is not an exception — it is a plausible-looking
expectancy computed from the wrong exit, so the exits have to be pinned
individually.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import payoff


def _bars(closes, opens=None, highs=None, lows=None, symbol="AAA"):
    n = len(closes)
    opens = opens if opens is not None else closes
    highs = highs if highs is not None else [max(o, c) for o, c in zip(opens, closes)]
    lows = lows if lows is not None else [min(o, c) for o, c in zip(opens, closes)]
    return pd.DataFrame({
        "symbol": symbol,
        "date": pd.bdate_range("2024-01-01", periods=n),
        "open": np.asarray(opens, dtype=float),
        "high": np.asarray(highs, dtype=float),
        "low": np.asarray(lows, dtype=float),
        "close": np.asarray(closes, dtype=float),
    })


def _trade(bars, entry=100.0, stop=98.0, rl=99.0, rh=101.0, i=0):
    return pd.DataFrame([{
        "symbol": "AAA", "date": bars["date"].iloc[i],
        "entry_px_adj": entry, "stop_px_adj": stop,
        "running_low_t": rl, "running_high_t": rh,
    }])


def _run(bars, trade, optimistic=False, cfg=None):
    cfg = cfg or payoff.PayoffConfig()
    out = payoff.simulate(trade, bars, cfg, optimistic=optimistic, verbose=False)
    return out.iloc[0]


# --------------------------------------------------------------------------
# the entry day, resolved against the opening window
# --------------------------------------------------------------------------

def test_entry_day_low_set_inside_the_window_cannot_stop_the_trade():
    """If the day's low was printed before entry, the stop was not hit that day.

    `low_D == low_t` means price never traded below the running low after the
    entry, and the stop sits below that low by construction. Counting it as a
    stop is the H004 pairing error in a new costume.
    """
    # Day 0 low equals the running low through t (99), so it happened pre-entry.
    b = _bars([100, 101, 102], opens=[100, 100.5, 101.5],
              highs=[101, 102, 103], lows=[99, 100, 101])
    r = _run(b, _trade(b, entry=100, stop=98, rl=99))
    assert r["exit_reason"] != payoff.STOP
    assert r["sessions_held"] > 0


def test_entry_day_low_set_after_entry_does_stop_the_trade():
    """A day low *below* the running low can only have printed after entry."""
    b = _bars([100, 101], opens=[100, 100], highs=[101, 102], lows=[97, 100])
    r = _run(b, _trade(b, entry=100, stop=98, rl=99))
    assert r["exit_reason"] == payoff.STOP
    assert r["sessions_held"] == 0
    assert r["payoff_ret_pct"] == pytest.approx(-2.0)


def test_entry_day_high_set_inside_the_window_cannot_fill_the_target():
    """Symmetric to the low: a pre-entry high is not reachable from the entry."""
    cfg = payoff.PayoffConfig(target_pct=15.0)
    # Day 0 high (116) equals the window high, so the +15% level printed before
    # entry and cannot be sold into.
    b = _bars([100, 100], opens=[100, 100], highs=[116, 101], lows=[99.5, 99.5])
    r = _run(b, _trade(b, entry=100, stop=98, rl=99, rh=116), cfg=cfg)
    assert not str(r["exit_reason"]).startswith("target")


# --------------------------------------------------------------------------
# gap-through: a stop is not a fill
# --------------------------------------------------------------------------

def test_a_session_opening_below_the_stop_fills_at_the_open():
    """The loss is the gap, not the stop level. This is where the losses live."""
    b = _bars([100, 90], opens=[100, 92], highs=[101, 93], lows=[99.5, 89])
    r = _run(b, _trade(b, entry=100, stop=98, rl=99))
    assert r["exit_reason"] == payoff.STOP_GAP
    assert r["payoff_ret_pct"] == pytest.approx(-8.0)      # filled at 92, not 98


def test_a_session_opening_above_the_target_fills_the_half_at_the_open():
    cfg = payoff.PayoffConfig(target_pct=15.0)
    b = _bars([100, 130, 131], opens=[100, 130, 131],
              highs=[100.5, 131, 132], lows=[99.6, 129, 130])
    r = _run(b, _trade(b, entry=100, stop=98, rl=99), cfg=cfg)
    assert bool(r["target_filled"])
    # Half sold at 130 (not at the 115 target), so the trade must beat +15%.
    assert r["payoff_ret_pct"] > 15.0


# --------------------------------------------------------------------------
# the ordering ambiguity, which is the whole reason for a bracket
# --------------------------------------------------------------------------

def test_a_session_touching_both_stop_and_target_brackets():
    """The one thing a daily bar cannot say. Both answers must be produced."""
    cfg = payoff.PayoffConfig(target_pct=15.0)
    b = _bars([100, 105, 105], opens=[100, 104, 105],
              highs=[100.5, 118, 106], lows=[99.6, 97, 104])
    pes = _run(b, _trade(b, entry=100, stop=98, rl=99), optimistic=False, cfg=cfg)
    opt = _run(b, _trade(b, entry=100, stop=98, rl=99), optimistic=True, cfg=cfg)
    assert pes["exit_reason"] == payoff.STOP
    assert not bool(pes["target_filled"])
    assert bool(opt["target_filled"])
    assert opt["payoff_ret_pct"] > pes["payoff_ret_pct"]


def test_stop_and_target_on_different_sessions_is_not_ambiguous():
    """Across sessions the order is known, so the two runs must agree.

    This is the distinction H006 missed: touching both *within ten sessions*
    creates no ambiguity at all. Only touching both *in the same session* does.
    """
    cfg = payoff.PayoffConfig(target_pct=15.0)
    b = _bars([100, 116, 100, 99], opens=[100, 116, 108, 99],
              highs=[100.5, 117, 109, 100], lows=[99.6, 115, 99, 97])
    pes = _run(b, _trade(b, entry=100, stop=98, rl=99), optimistic=False, cfg=cfg)
    opt = _run(b, _trade(b, entry=100, stop=98, rl=99), optimistic=True, cfg=cfg)
    assert pes["payoff_ret_pct"] == pytest.approx(opt["payoff_ret_pct"])


# --------------------------------------------------------------------------
# scale-out, breakeven and the trail
# --------------------------------------------------------------------------

def test_half_is_sold_at_the_target_and_the_rest_keeps_running():
    """A pure +15% exit would return +15%; scaling out and trailing must not."""
    cfg = payoff.PayoffConfig(target_pct=15.0, scale_out_frac=0.5, trail_ema=10)
    closes = [100, 116, 125, 130, 135, 90]
    b = _bars(closes, opens=closes,
              highs=[c + 1 for c in closes], lows=[c - 1 for c in closes])
    r = _run(b, _trade(b, entry=100, stop=98, rl=99), cfg=cfg)
    assert str(r["exit_reason"]).startswith("target")
    # Half at 115, half exited later well above it: strictly better than +15%
    # would be wrong, and strictly equal to +15% would mean no scale-out.
    assert r["payoff_ret_pct"] != pytest.approx(15.0)


def test_the_trail_executes_at_the_next_open_not_the_signal_close():
    """A close below the EMA is a signal; the earliest fill is the next open.

    Exiting at the signal close hands the strategy a price it could not have
    got, and on a gap-down that difference is the entire result.
    """
    # Prices stay far above the entry throughout, so the breakeven stop can
    # never fire and the trail is the only thing under test.
    closes = [100, 130, 140, 150, 130, 125]      # day 4 closes under the EMA
    opens = [100, 130, 140, 150, 131, 120]       # then day 5 gaps down hard
    b = _bars(closes, opens=opens,
              highs=[max(o, c) + 1 for o, c in zip(opens, closes)],
              lows=[min(o, c) - 1 for o, c in zip(opens, closes)])
    slow = payoff.PayoffConfig(target_pct=15.0, trail_ema=3, trail_exec_next_open=True)
    fast = payoff.PayoffConfig(target_pct=15.0, trail_ema=3, trail_exec_next_open=False)
    a = _run(b, _trade(b, entry=100, stop=98, rl=99), cfg=slow)
    c = _run(b, _trade(b, entry=100, stop=98, rl=99), cfg=fast)
    assert a["payoff_ret_pct"] < c["payoff_ret_pct"]


def test_a_trade_that_never_resolves_is_reported_not_silently_closed():
    cfg = payoff.PayoffConfig(target_pct=15.0, max_sessions=3)
    b = _bars([100, 100.2, 100.1, 100.3, 100.2],
              opens=[100, 100.2, 100.1, 100.3, 100.2],
              highs=[100.4] * 5, lows=[99.7] * 5)
    r = _run(b, _trade(b, entry=100, stop=98, rl=99), cfg=cfg)
    assert r["exit_reason"] in (payoff.TIMEOUT, payoff.OPEN_AT_END)


# --------------------------------------------------------------------------
# benchmarking over a variable horizon
# --------------------------------------------------------------------------

def test_benchmark_is_compounded_over_the_trade_s_own_holding_window():
    """A variable-horizon rule cannot be judged against a fixed-horizon market.

    A rule that holds winners for thirty sessions and losers for two would look
    brilliant against a flat five-day comparison in a rising market, purely from
    the holding periods.
    """
    dates = pd.bdate_range("2024-01-01", periods=12)
    rows = []
    for s in ("AAA", "BBB"):
        px = 100.0
        for d in dates:
            px *= 1.01                       # a steadily rising market
            rows.append({"symbol": s, "date": d, "open": px, "high": px,
                         "low": px, "close": px})
    bars = pd.DataFrame(rows)
    sim = pd.DataFrame([
        {"symbol": "AAA", "date": dates[0], "payoff_ret_pct": 5.0, "sessions_held": 2},
        {"symbol": "AAA", "date": dates[0], "payoff_ret_pct": 5.0, "sessions_held": 10},
    ])
    monkey = payoff.daily_market_return
    payoff.daily_market_return = lambda b, min_symbols=50: monkey(b, min_symbols=1)
    try:
        out = payoff.attach_benchmark(sim, bars)
    finally:
        payoff.daily_market_return = monkey
    # The ten-session trade must be measured against ten sessions of market.
    assert out["bench_over_hold_pct"].iloc[1] > out["bench_over_hold_pct"].iloc[0]
    assert out["payoff_excess_pct"].iloc[1] < out["payoff_excess_pct"].iloc[0]


def test_a_session_with_too_few_priced_names_is_unknown_not_flat():
    """An unmeasured market must not be scored as a 0% market.

    Filling a missing benchmark session with zero quietly credits the strategy
    with beating a market nobody observed, and the error compounds across every
    trade whose window spans that session.
    """
    dates = pd.bdate_range("2024-01-01", periods=6)
    rows = [{"symbol": "AAA", "date": d, "open": 100.0, "high": 100.0,
             "low": 100.0, "close": 100.0} for d in dates]
    bars = pd.DataFrame(rows)                    # one symbol: never enough
    sim = pd.DataFrame([{"symbol": "AAA", "date": dates[0],
                         "payoff_ret_pct": 5.0, "sessions_held": 3}])
    out = payoff.attach_benchmark(sim, bars)
    assert pd.isna(out["bench_over_hold_pct"].iloc[0])
    assert pd.isna(out["payoff_excess_pct"].iloc[0])
