"""The resolver is the piece the whole result rests on, so it is pinned hard.

The first three tests are the defects review found in the first version. All
three flattered the result, which is why they are first.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.research.families import setup_grind, setup_grind_outcome as out

NC = {**setup_grind.EXECUTION_RULES, "cost_bps_round_trip": 0.0}


def _path(rows, rolled=None):
    """Bars as fractions of the decision close, which is 1.0."""
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"]) / 100.0
    frame["rolled"] = rolled if rolled is not None else False
    frame["session"] = pd.date_range("2024-01-02", periods=len(frame), freq="B")
    return frame


# --------------------------------------------------------------------------
# The three defects.
# --------------------------------------------------------------------------

def test_a_fill_that_gaps_through_its_own_stop_is_not_a_profit():
    """Entered at 92 with a stop at 94, the old resolver booked +0.5R."""
    r = out.resolve_trade(_path([[92, 99, 91, 95]]), -0.01, -0.03, 0.03, rules=NC)
    assert r["outcome"] == "invalidated_at_fill"
    assert r["r"] == 0.0


def test_a_gap_down_through_the_stop_exits_at_the_open_not_the_stop():
    """The old resolver recorded -1.00R where the tape offered -3.00R."""
    path = _path([[101, 103, 100, 102], [90, 91, 88, 89]])
    r = out.resolve_trade(path, 0.02, -0.02, 0.10, rules=NC)
    assert r["outcome"] == "stop"
    assert r["r"] == pytest.approx((90 - 102) / 4)


def test_both_barriers_in_one_session_takes_the_stop_and_it_is_a_loss():
    r = out.resolve_trade(_path([[101, 112, 97, 100]]), 0.02, -0.02, 0.10, rules=NC)
    assert r["outcome"] == "stop"
    assert r["r"] < 0


def test_a_stop_outcome_can_never_be_profitable():
    """The invariant that would have caught the first defect on day one."""
    with pytest.raises(out.ResolutionError, match="stop-out produced"):
        out._check("stop", +0.5)
    out._check("stop", -1.0)
    out._check("target", +2.0)


# --------------------------------------------------------------------------
# Ordinary behaviour.
# --------------------------------------------------------------------------

def test_a_long_reaching_its_target_pays_the_drawn_reward_to_risk():
    path = _path([[101, 103, 100, 102], [102, 111, 101, 110]])
    r = out.resolve_trade(path, 0.02, -0.02, 0.10, rules=NC)
    assert r["outcome"] == "target"
    assert r["r"] == pytest.approx(2.0)


def test_an_entry_never_reached_scores_zero_rather_than_vanishing():
    r = out.resolve_trade(_path([[99, 100, 98, 99]] * 10), 0.02, -0.02, 0.10, rules=NC)
    assert r["outcome"] == "no_fill" and r["r"] == out.NO_FILL_R == 0.0


def test_the_entry_window_closes_after_three_sessions():
    late = _path([[99, 100, 98, 99]] * 3 + [[102, 111, 101, 110]])
    assert out.resolve_trade(late, 0.02, -0.02, 0.10,
                             rules=NC)["outcome"] == "no_fill"


def test_a_gap_through_a_breakout_entry_fills_at_the_worse_open():
    r = out.resolve_trade(_path([[106, 111, 105, 110]]), 0.02, -0.02, 0.10, rules=NC)
    assert r["outcome"] == "target"
    assert r["r"] == pytest.approx((110 - 106) / 4)


def test_a_short_is_read_from_the_stop_sitting_above_the_entry():
    path = _path([[99, 100, 97, 98], [98, 99, 89, 90]])
    r = out.resolve_trade(path, -0.02, 0.02, -0.10, rules=NC)
    assert r["outcome"] == "target"
    assert r["r"] == pytest.approx(2.0)


def test_it_times_out_at_the_registered_hold_and_marks_to_the_close():
    flat = _path([[102, 103, 101, 102]] + [[102, 103, 101, 103]] * 20)
    r = out.resolve_trade(flat, 0.02, -0.02, 0.10, rules=NC)
    assert r["outcome"] == "time_exit"
    assert r["sessions_held"] == NC["max_hold_sessions"] + 1


def test_every_roll_inside_the_hold_is_charged_as_its_own_round_trip():
    rolled = [False, True, False, True] + [False] * 18
    flat = _path([[102, 103, 101, 102]] + [[102, 103, 101, 102]] * 21, rolled=rolled)
    paid = out.resolve_trade(flat, 0.02, -0.02, 0.10)
    free = out.resolve_trade(flat, 0.02, -0.02, 0.10, rules=NC)
    charged = free["r"] - paid["r"]
    assert paid["rolls"] == 2
    # one entry round trip plus two rolls
    assert charged == pytest.approx(0.0010 * 3 / 0.04, rel=1e-6)


# --------------------------------------------------------------------------
# The continuous futures path.
# --------------------------------------------------------------------------

def test_a_roll_does_not_print_a_profit_the_holder_never_earned():
    """The near contract steps down at the roll; the position does not."""
    frame = pd.DataFrame({
        "session": pd.date_range("2024-01-02", periods=4, freq="B"),
        "near_expiry": ["2024-01-25", "2024-01-25", "2024-02-29", "2024-02-29"],
        "futures_open": [100.0, 100.0, 96.0, 96.0],
        "futures_high": [101.0, 101.0, 97.0, 97.0],
        "futures_low": [99.0, 99.0, 95.0, 95.0],
        # a 4-point step at the roll, with cash flat throughout
        "futures_close": [100.0, 100.0, 96.0, 96.0],
        "underlying_close": [99.8, 99.8, 99.8, 99.8],
    })
    path = out.continuous_futures(frame)
    assert bool(path["rolled"].iloc[2])
    # Cash was flat across the roll, so the continuous path must be flat too.
    assert path["close"].iloc[3] == pytest.approx(path["close"].iloc[0])


def test_pairs_use_every_same_session_skip_and_exclude_repeats():
    private = {
        "T1": {"decision_at_private": "2024-01-02", "is_repeat_private": False},
        "S1": {"decision_at_private": "2024-01-02", "is_repeat_private": False},
        "S2": {"decision_at_private": "2024-01-02", "is_repeat_private": False},
        "T2": {"decision_at_private": "2024-01-03", "is_repeat_private": False},
        "R1": {"decision_at_private": "2024-01-02", "is_repeat_private": True},
    }
    marks = pd.DataFrame([
        {"case_id": c, "action": a, "entry_atr": 1, "stop_atr": -1,
         "target_atr": 3, "conviction": 2}
        for c, a in [("T1", "take"), ("S1", "skip"), ("S2", "skip"),
                     ("T2", "take"), ("R1", "take")]])
    pairs = out.build_pairs(marks, private)
    assert set(pairs["take_case_id"]) == {"T1", "T2"}      # repeat excluded
    row = pairs.set_index("take_case_id").loc["T1"]
    assert sorted(row["control_case_ids"]) == ["S1", "S2"]  # every skip, not one
    # A take in a session with no skips is kept and reported, not dropped.
    assert pairs.set_index("take_case_id").loc["T2", "control_case_ids"] == []
