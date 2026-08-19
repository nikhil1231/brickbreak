"""Joining opening-window features to daily candidates.

The cases that matter here are the ones where a plausible-looking join is
silently wrong: a renamed ticker that drops out, and a gap computed off the
first tick instead of the opening print.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.opening_join import (
    add_gap_fields, add_volume_context, build_panel, coverage,
)


def _feat(rows):
    return pd.DataFrame([{"symbol": s, "date": pd.Timestamp(d), "open_px": o,
                          "vol_5m": v, "high_5m": o, "low_5m": o, "close_5m": o}
                         for s, d, o, v in rows])


def _bars(rows):
    return pd.DataFrame([{"symbol": s, "date": pd.Timestamp(d), "open_raw": o,
                          "prev_close_raw": pc, "high_raw": o, "low_raw": o,
                          "close_raw": o, "volume": 1000, "turnover": 1e6,
                          "adj_factor": 1.0}
                         for s, d, o, pc in rows])


# ----------------------------------------------------------------- gap fields

def test_gap_uses_the_opening_print_not_the_first_tick():
    """MINDACORP 2024-05-21: bhavcopy opened it at 405.05 against a 430.75
    close — a 6% gap down — while the first captured tick is 434.00, which
    reads as a gap up. The two must not be conflated."""
    f = _feat([("MINDACORP", "2024-05-21", 434.00, 12684)])
    b = _bars([("MINDACORP", "2024-05-21", 405.05, 430.75)])
    d = add_gap_fields(f, b)
    assert d.loc[0, "gap_pct"] == pytest.approx(-5.966, abs=1e-3)
    assert d.loc[0, "gap_pct_tick"] == pytest.approx(0.754, abs=1e-3)
    # opposite signs: this is the whole reason both are carried
    assert d.loc[0, "gap_pct"] < 0 < d.loc[0, "gap_pct_tick"]


def test_open_drift_is_the_move_from_the_print_to_the_first_tick():
    f = _feat([("X", "2024-05-21", 110.0, 100)])
    b = _bars([("X", "2024-05-21", 100.0, 100.0)])
    d = add_gap_fields(f, b)
    assert d.loc[0, "open_drift_pct"] == pytest.approx(10.0)


def test_gap_is_flat_when_the_open_equals_the_previous_close():
    f = _feat([("X", "2024-05-21", 100.0, 100)])
    b = _bars([("X", "2024-05-21", 100.0, 100.0)])
    d = add_gap_fields(f, b)
    assert d.loc[0, "gap_pct"] == pytest.approx(0.0)
    assert d.loc[0, "open_drift_pct"] == pytest.approx(0.0)


# -------------------------------------------------------------------- volume

def test_opening_volume_is_scaled_by_a_denominator_defined_every_day():
    f = _feat([("X", "2024-05-21", 100.0, 5_000)])
    m = pd.DataFrame([{"symbol": "X", "date": pd.Timestamp("2024-05-21"),
                       "median_vol_20": 50_000, "median_tv_20_cr": 5.0}])
    d = add_volume_context(f, m)
    assert d.loc[0, "vol_5m_pct_of_median_daily"] == pytest.approx(10.0)


def test_self_referential_volume_carries_its_own_observation_count():
    """`vol_5m_rel_own` averages only over days the symbol was already a
    candidate, so the count of prior observations travels with it."""
    rows = [("X", f"2024-05-{d:02d}", 100.0, 1_000) for d in range(1, 8)]
    f = _feat(rows)
    m = pd.DataFrame([{"symbol": "X", "date": pd.Timestamp(f"2024-05-{d:02d}"),
                       "median_vol_20": 10_000, "median_tv_20_cr": 5.0}
                      for d in range(1, 8)])
    d = add_volume_context(f, m)
    assert d.iloc[0]["n_prior_open_obs"] == 0
    assert pd.isna(d.iloc[0]["vol_5m_rel_own"])      # no history yet
    assert d.iloc[-1]["n_prior_open_obs"] == 6
    assert d.iloc[-1]["vol_5m_rel_own"] == pytest.approx(1.0)


# ---------------------------------------------------------------------- join

def test_join_defaults_to_inner_so_missing_ticks_are_not_zero_volume():
    cands = pd.DataFrame([{"symbol": "X", "date": pd.Timestamp("2024-05-21")},
                          {"symbol": "Y", "date": pd.Timestamp("2024-05-21")}])
    f = _feat([("X", "2024-05-21", 100.0, 5_000)])
    b = _bars([("X", "2024-05-21", 100.0, 100.0), ("Y", "2024-05-21", 50.0, 50.0)])
    m = pd.DataFrame([{"symbol": s, "date": pd.Timestamp("2024-05-21"),
                       "median_vol_20": 10_000, "median_tv_20_cr": 5.0}
                      for s in ("X", "Y")])
    panel = build_panel(cands, f, b, m)
    assert list(panel["symbol"]) == ["X"]


def test_coverage_is_reported_only_inside_the_tick_window():
    """Candidates from years with no pull would otherwise drag the percentage
    down and describe the pull's date range rather than the join."""
    cands = pd.DataFrame([{"symbol": "X", "date": pd.Timestamp(d)}
                          for d in ("2020-01-02", "2024-05-21", "2024-05-22")])
    f = _feat([("X", "2024-05-21", 100.0, 5_000), ("X", "2024-05-22", 100.0, 5_000)])
    cov = coverage(cands, f)
    assert cov["candidates_total"] == 3
    assert cov["candidates_in_window"] == 2
    assert cov["matched"] == 2
    assert cov["matched_pct"] == 100.0


def test_unmatched_candidates_are_attributed_to_a_reason():
    cands = pd.DataFrame([{"symbol": s, "date": pd.Timestamp("2024-05-21")}
                          for s in ("X", "Y", "Z")])
    f = _feat([("X", "2024-05-21", 100.0, 5_000)])
    man = pd.DataFrame([{"symbol": "Y", "date": pd.Timestamp("2024-05-21"),
                         "status": "empty"}])
    cov = coverage(cands, f, manifest=man, rmap=pd.DataFrame())
    assert cov["unmatched"] == 2
    assert cov["unmatched_reasons"] == {"empty": 1, "never_requested": 1}
