"""Characterisation of the candidate pool.

These tests pin the two claims the next phase will lean on: that the joint-mass
grid counts what it says it counts, and that the censoring check actually
detects a boundary atom rather than reporting a number that looks plausible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.families.opening_window.characterize import censoring_check, describe, joint_mass, report


def _panel(n=500, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "symbol": [f"S{i%20}" for i in range(n)],
        "date": pd.bdate_range("2024-01-01", periods=n),
        "gap_pct": rng.normal(0.25, 0.8, n),
        "open_drift_pct": rng.normal(0, 0.4, n),
        "vol_5m_pct_of_median_daily": rng.lognormal(1.0, 1.0, n),
        "vol_5m_rel_own": rng.lognormal(0, 1, n),
        "om_low_vs_open_pct": -rng.exponential(0.3, n),
        "om_body_pct": rng.uniform(0, 100, n),
        "range_5m_pct": rng.lognormal(0, 0.5, n),
        "median_tv_20_cr": rng.lognormal(1, 1, n),
        "om_bars": rng.integers(1, 20, n),
    })


def test_describe_reports_every_measure_present():
    d = describe(_panel())
    assert {"gap_pct", "vol_5m_pct_of_median_daily", "om_low_vs_open_pct"} <= set(d)
    assert d["gap_pct"]["n"] == 500
    q = d["gap_pct"]["quantiles"]
    assert q["p05"] < q["p50"] < q["p95"]


def test_describe_skips_measures_that_are_entirely_missing():
    p = _panel()
    p["om_body_pct"] = np.nan
    assert "om_body_pct" not in describe(p)


def test_joint_mass_counts_the_intersection():
    p = _panel()
    rows = joint_mass(p, gap_bands=((0, 2),), vol_floors=(5,))
    expected = int((p.gap_pct.between(0, 2) & (p.vol_5m_pct_of_median_daily >= 5)).sum())
    assert rows[0]["n_days"] == expected
    assert rows[0]["pct_of_panel"] == pytest.approx(expected / len(p) * 100, abs=1e-3)


def test_joint_mass_shrinks_as_the_volume_floor_rises():
    p = _panel()
    rows = joint_mass(p, gap_bands=((0, 2),), vol_floors=(5, 10, 20))
    counts = [r["n_days"] for r in rows]
    assert counts == sorted(counts, reverse=True)


def test_censoring_check_finds_the_boundary_atom():
    """Half the rows placed exactly at zero must be reported as exactly half."""
    p = _panel()
    p.loc[p.index[:250], "om_low_vs_open_pct"] = 0.0
    c = censoring_check(p)
    assert c["pct_at_zero_overall"] == pytest.approx(50.0, abs=0.5)
    assert len(c["by_turnover_quintile"]) == 5


def test_censoring_check_reports_no_atom_when_there_is_none():
    p = _panel()
    p["om_low_vs_open_pct"] = -np.abs(p["om_low_vs_open_pct"]) - 0.01
    c = censoring_check(p)
    assert c["pct_at_zero_overall"] == 0.0


def test_the_measure_is_one_sided_by_construction():
    """`om_low` is a minimum over the same minute `om_open` starts, so a
    positive value would mean the low exceeded the open — impossible."""
    p = _panel()
    c = censoring_check(p)
    assert c["pct_positive"] == 0.0


def test_report_is_json_serialisable_and_self_describing():
    import json
    rep = report(_panel(), save=False)
    assert rep["panel_rows"] == 500
    assert set(rep) >= {"distributions", "gap_profile", "volume_profile",
                        "censoring", "joint_mass", "window"}
    json.dumps(rep, default=str)
