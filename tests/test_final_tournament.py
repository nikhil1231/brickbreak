import numpy as np
import pandas as pd

from src.research.families.final_tournament import (
    _leg,
    _session_targets,
    hh_mean,
)


def test_session_targets_count_market_sessions_not_calendar_days():
    sessions = pd.DatetimeIndex(["2026-01-02", "2026-01-05", "2026-01-07"])
    got = _session_targets(sessions, 1)
    assert got.loc[pd.Timestamp("2026-01-02")] == pd.Timestamp("2026-01-05")
    assert got.loc[pd.Timestamp("2026-01-05")] == pd.Timestamp("2026-01-07")
    assert pd.isna(got.loc[pd.Timestamp("2026-01-07")])


def test_leg_has_equal_session_weight_despite_different_breadth():
    rows = pd.DataFrame({
        "session": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-02"]),
        "_row_id": [4, 8, 9],
    })
    ids, weights = _leg(rows, sign=-1.0)
    assert ids.tolist() == [4, 8, 9]
    assert np.allclose(weights, [-1.0, -0.5, -0.5])


def test_hansen_hodrick_is_rectangular_not_bartlett():
    x = pd.Series([1.0, 3.0, 2.0, 5.0, 4.0, 8.0, 7.0, 9.0])
    got = hh_mean(x, lag=2)
    e = x.to_numpy() - x.mean()
    n = len(e)
    long_run = (e @ e) / n
    long_run += 2 * (e[1:] @ e[:-1]) / n
    long_run += 2 * (e[2:] @ e[:-2]) / n
    expected = x.mean() / np.sqrt(long_run / n)
    assert np.isclose(got["t"], expected)
