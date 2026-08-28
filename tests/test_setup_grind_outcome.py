"""The resolver is the piece the whole result rests on, so it is pinned hard."""
from __future__ import annotations

import pandas as pd
import pytest

from src.research.families import setup_grind_outcome as out


def _future(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


NO_COST = {**{k: v for k, v in __import__(
    "src.research.families.setup_grind", fromlist=["x"]).EXECUTION_RULES.items()},
    "cost_bps_round_trip": 0.0}


def test_a_long_that_reaches_its_target_pays_the_drawn_reward_to_risk():
    # close 100, ATR 2%. entry +1 ATR = 102, stop -1 ATR = 98, target +5 = 110.
    # Risk is 4, reward 8, so a target hit is +2R before costs.
    future = _future([[101, 103, 100, 102],    # triggers at 102
                      [102, 111, 101, 110]])   # reaches 110
    r = out.resolve_trade(future, 100.0, 2.0, 1.0, -1.0, 5.0, rules=NO_COST)
    assert r["outcome"] == "target"
    assert r["r"] == pytest.approx(2.0)


def test_a_stop_and_a_target_in_one_session_takes_the_stop():
    """A daily bar cannot say which came first, and the registration says stop."""
    future = _future([[101, 112, 97, 100]])    # triggers, touches both
    r = out.resolve_trade(future, 100.0, 2.0, 1.0, -1.0, 5.0, rules=NO_COST)
    assert r["outcome"] == "stop"
    assert r["r"] == pytest.approx(-1.0)


def test_an_entry_never_reached_scores_zero_rather_than_vanishing():
    future = _future([[99, 100, 98, 99]] * 10)   # never trades up to 102
    r = out.resolve_trade(future, 100.0, 2.0, 1.0, -1.0, 5.0, rules=NO_COST)
    assert r["outcome"] == "no_fill"
    assert r["r"] == out.NO_FILL_R == 0.0


def test_the_entry_window_closes_after_three_sessions():
    late = _future([[99, 100, 98, 99]] * 3 + [[102, 111, 101, 110]])
    assert out.resolve_trade(
        late, 100.0, 2.0, 1.0, -1.0, 5.0, rules=NO_COST)["outcome"] == "no_fill"


def test_a_gap_through_a_breakout_entry_fills_at_the_worse_open():
    """Filling at the level would book a profit the tape never offered."""
    future = _future([[106, 111, 105, 110]])   # gaps open past the 102 entry
    r = out.resolve_trade(future, 100.0, 2.0, 1.0, -1.0, 5.0, rules=NO_COST)
    assert r["outcome"] == "target"
    assert r["r"] == pytest.approx((110 - 106) / 4)   # filled at 106, not 102


def test_a_short_is_read_from_the_stop_sitting_above_the_entry():
    # entry 98, stop 102, target 90: a short. Risk 4, reward 8.
    future = _future([[99, 100, 97, 98],       # trades down through 98
                      [98, 99, 89, 90]])
    r = out.resolve_trade(future, 100.0, 2.0, -1.0, 1.0, -5.0, rules=NO_COST)
    assert r["outcome"] == "target"
    assert r["r"] == pytest.approx(2.0)


def test_it_times_out_at_the_registered_hold_and_marks_to_the_close():
    flat = _future([[102, 103, 101, 102]] + [[102, 103, 101, 103]] * 20)
    r = out.resolve_trade(flat, 100.0, 2.0, 1.0, -1.0, 5.0, rules=NO_COST)
    assert r["outcome"] == "time_exit"
    assert r["sessions_held"] == NO_COST["max_hold_sessions"] + 1
    assert r["r"] == pytest.approx((103 - 102) / 4)


def test_costs_come_out_of_the_r_multiple():
    future = _future([[101, 103, 100, 102], [102, 111, 101, 110]])
    free = out.resolve_trade(future, 100.0, 2.0, 1.0, -1.0, 5.0, rules=NO_COST)
    paid = out.resolve_trade(future, 100.0, 2.0, 1.0, -1.0, 5.0)
    assert paid["r"] < free["r"]
    assert free["r"] - paid["r"] == pytest.approx(0.0010 * 102 / 4, rel=1e-6)


def test_pairs_take_a_control_from_the_same_session_and_skip_repeats():
    private = {
        "T1": {"decision_at_private": "2024-01-02", "is_repeat_private": False},
        "S1": {"decision_at_private": "2024-01-02", "is_repeat_private": False},
        "T2": {"decision_at_private": "2024-01-03", "is_repeat_private": False},
        "R1": {"decision_at_private": "2024-01-02", "is_repeat_private": True},
    }
    marks = pd.DataFrame([
        {"case_id": "T1", "action": "take", "entry_atr": 1, "stop_atr": -1,
         "target_atr": 3, "conviction": 2},
        {"case_id": "S1", "action": "skip", "entry_atr": None, "stop_atr": None,
         "target_atr": None, "conviction": None},
        {"case_id": "T2", "action": "take", "entry_atr": 1, "stop_atr": -1,
         "target_atr": 3, "conviction": 2},
        {"case_id": "R1", "action": "take", "entry_atr": 1, "stop_atr": -1,
         "target_atr": 3, "conviction": 2},
    ])
    pairs = out.build_pairs(marks, private, seed=1)
    # T2's session has no skip, so it cannot be paired; R1 is a repeat.
    assert list(pairs["take_case_id"]) == ["T1"]
    assert list(pairs["control_case_id"]) == ["S1"]
