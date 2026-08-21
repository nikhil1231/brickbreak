"""Forward-return labelling.

These tests exist to pin the four ways a label goes quietly wrong: the split
that is not a crash, the forward window that reaches across months, the
excursion measured from a high that printed before entry, and the truncated
window that gets reported as a number anyway. Each is checked against a hand-
built panel where the right answer is known by construction.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.families.opening_window.labelling import (LabelConfig, attach_labels, by_bucket,
                           horizon_summary, report)


def _bars(symbols=("AAA", "BBB"), n=40, start="2024-01-01"):
    """A flat 100.00 series per symbol, adjusted == raw, so any label is 0%."""
    rows = []
    for s in symbols:
        d = pd.bdate_range(start, periods=n)
        rows.append(pd.DataFrame({
            "symbol": s, "series": "EQ", "date": d,
            "high": 100.0, "low": 100.0, "close": 100.0,
        }))
    return pd.concat(rows, ignore_index=True)


def _panel(bars, rows):
    """Candidate rows: (symbol, date_index, close_5m, adj_factor)."""
    out = []
    for sym, i, px, af in rows:
        d = bars[bars.symbol == sym].date.iloc[i]
        out.append({"symbol": sym, "date": d, "close_5m": px, "adj_factor": af,
                    "open_raw": px, "gap_pct": 0.0,
                    # Read at the same `t` as the entry, so it cannot exceed it.
                    "low_5m": px, "vol_5m_pct_of_median_daily": 5.0})
    return pd.DataFrame(out)


def test_flat_series_labels_to_zero():
    b = _bars()
    p = _panel(b, [("AAA", 0, 100.0, 1.0)])
    lab = attach_labels(p, b, LabelConfig(benchmark=False))
    for h in (1, 3, 5, 10):
        assert lab[f"fwd_ret_{h}d_pct"].iloc[0] == pytest.approx(0.0)
        assert lab[f"mfe_{h}d_pct"].iloc[0] == pytest.approx(0.0)


def test_split_in_the_forward_window_is_not_read_as_a_crash():
    """The trap that motivates `entry_px_adj`.

    A 1:10 split on day 5: raw prices fall 1000 -> 100, `adj_factor` moves 1.0
    -> 0.1 before the split so the adjusted series stays flat. The tick entry is
    raw (1000), so dividing an adjusted forward close by it reads -90%.
    """
    b = _bars(("AAA",), n=20)
    idx = b.index[:5]
    b.loc[idx, ["high", "low", "close"]] = 100.0   # adjusted: flat throughout
    b.loc[b.index[5:], ["high", "low", "close"]] = 100.0
    # Entry day is pre-split: raw 1000, factor 0.1 -> adjusted 100.
    p = _panel(b, [("AAA", 0, 1000.0, 0.1)])
    lab = attach_labels(p, b, LabelConfig(benchmark=False))

    assert lab["entry_px_adj"].iloc[0] == pytest.approx(100.0)
    assert lab["fwd_ret_10d_pct"].iloc[0] == pytest.approx(0.0)
    # The naive version, for contrast: this is the label that would have shipped.
    naive = (100.0 / lab["entry_px_raw"].iloc[0] - 1) * 100
    assert naive == pytest.approx(-90.0)


def test_forward_window_counts_the_symbols_own_sessions_not_candidate_rows():
    """A symbol is a candidate on scattered days; +1d must still mean +1 session.

    Two candidate rows six months apart. If the forward arrays were built on the
    candidate panel, the first row's "+1d" would be the second row's date.
    """
    b = _bars(("AAA",), n=200)
    b.loc[b.index[1], ["high", "low", "close"]] = 110.0     # the true +1d
    b.loc[b.index[150], ["high", "low", "close"]] = 500.0   # far-future candidate
    p = _panel(b, [("AAA", 0, 100.0, 1.0), ("AAA", 149, 100.0, 1.0)])
    lab = attach_labels(p, b, LabelConfig(horizons=(1,), benchmark=False))
    assert lab.sort_values("date")["fwd_ret_1d_pct"].iloc[0] == pytest.approx(10.0)


def test_entry_day_high_is_excluded_from_the_clean_excursion():
    """13.7% of real mornings peak before 09:20. The clean MFE must not see it."""
    b = _bars(("AAA",), n=20)
    b.loc[b.index[0], "high"] = 130.0        # entry-day spike, may predate entry
    p = _panel(b, [("AAA", 0, 100.0, 1.0)])
    lab = attach_labels(p, b, LabelConfig(horizons=(5,), benchmark=False))
    assert lab["mfe_5d_pct"].iloc[0] == pytest.approx(0.0)
    assert lab["mfe_5d_incl_d0_pct"].iloc[0] == pytest.approx(30.0)


def test_running_extremes_cover_the_whole_window_not_just_its_last_day():
    b = _bars(("AAA",), n=20)
    b.loc[b.index[2], "high"] = 120.0   # inside the 5d window, not at its end
    b.loc[b.index[3], "low"] = 80.0
    p = _panel(b, [("AAA", 0, 100.0, 1.0)])
    lab = attach_labels(p, b, LabelConfig(horizons=(1, 5), benchmark=False))
    assert lab["mfe_5d_pct"].iloc[0] == pytest.approx(20.0)
    assert lab["mae_5d_pct"].iloc[0] == pytest.approx(-20.0)
    # ...and the shorter horizon must not see either of them.
    assert lab["mfe_1d_pct"].iloc[0] == pytest.approx(0.0)


def test_truncated_windows_are_nan_not_short():
    """The last sessions of the panel have no +10d. They must not be labelled."""
    b = _bars(("AAA",), n=20)
    p = _panel(b, [("AAA", 18, 100.0, 1.0)])   # one session left
    lab = attach_labels(p, b, LabelConfig(benchmark=False))
    assert bool(lab["horizon_complete_1d"].iloc[0]) is True
    assert bool(lab["horizon_complete_10d"].iloc[0]) is False
    assert lab["fwd_ret_1d_pct"].notna().iloc[0]
    assert lab["fwd_ret_10d_pct"].isna().iloc[0]
    assert lab["mfe_10d_pct"].isna().iloc[0]


def test_benchmark_is_subtracted_and_kills_a_pure_market_move():
    """Every symbol rises 5%; the candidate's excess return is zero, not +5%."""
    b = _bars(("AAA", "BBB"), n=20)
    for s in ("AAA", "BBB"):
        m = (b.symbol == s) & (b.index >= b[b.symbol == s].index[1])
        b.loc[m, ["high", "low", "close"]] = 105.0
    p = _panel(b, [("AAA", 0, 100.0, 1.0)])
    cfg = LabelConfig(horizons=(1,), benchmark=True, bench_min_symbols=2)
    lab = attach_labels(p, b, cfg)
    assert lab["fwd_ret_1d_pct"].iloc[0] == pytest.approx(5.0)
    assert lab["bench_fwd_ret_1d_pct"].iloc[0] == pytest.approx(5.0)
    assert lab["excess_ret_1d_pct"].iloc[0] == pytest.approx(0.0)


def test_thin_sessions_do_not_get_a_benchmark():
    b = _bars(("AAA", "BBB"), n=20)
    p = _panel(b, [("AAA", 0, 100.0, 1.0)])
    cfg = LabelConfig(horizons=(1,), benchmark=True, bench_min_symbols=50)
    lab = attach_labels(p, b, cfg)
    assert lab["bench_fwd_ret_1d_pct"].isna().all()
    assert lab["excess_ret_1d_pct"].isna().all()


def test_suspension_is_flagged_as_a_stale_window():
    b = _bars(("AAA",), n=20)
    keep = b.index[:2].tolist() + b.index[10:].tolist()
    b = b.loc[keep].reset_index(drop=True)
    b.loc[b.index[2:], "date"] = b.loc[b.index[2:], "date"] + pd.Timedelta(days=200)
    p = _panel(b, [("AAA", 0, 100.0, 1.0)])
    lab = attach_labels(p, b, LabelConfig(horizons=(3,), benchmark=False))
    assert bool(lab["stale_window_3d"].iloc[0]) is True


def test_entry_slippage_measures_the_cost_of_waiting_for_the_window():
    b = _bars(("AAA",), n=20)
    p = _panel(b, [("AAA", 0, 101.0, 1.0)])
    p["open_raw"] = 100.0
    lab = attach_labels(p, b, LabelConfig(horizons=(1,), benchmark=False))
    assert lab["entry_slippage_pct"].iloc[0] == pytest.approx(1.0)


def test_summary_and_buckets_report_what_they_measured():
    b = _bars(("AAA", "BBB"), n=40)
    rng = np.random.default_rng(0)
    b[["high", "low", "close"]] = b[["high", "low", "close"]].mul(
        rng.normal(1, 0.02, len(b)), axis=0)
    b["high"] = b[["high", "low", "close"]].max(axis=1)
    b["low"] = b[["high", "low", "close"]].min(axis=1)
    p = _panel(b, [("AAA", i, 100.0, 1.0) for i in range(20)])
    cfg = LabelConfig(horizons=(1, 5), benchmark=False)
    lab = attach_labels(p, b, cfg)

    rows = horizon_summary(lab, cfg)
    assert [r["horizon_d"] for r in rows] == [1, 5]
    assert all(0 <= r["hit_rate_pct"] <= 100 for r in rows)
    assert rows[0]["n"] == int(lab["fwd_ret_1d_pct"].notna().sum())

    buckets = by_bucket(lab, "gap_pct", [-np.inf, 0, np.inf], cfg)
    assert sum(r["n"] for r in buckets) == len(lab)

    rep = report(lab, cfg, save=False)
    assert rep["entry_basis"] == "close_5m"
    assert rep["rows"] == len(lab)


def test_slippage_profile_splits_the_window_move_by_bucket():
    """The mechanism behind the headline result, so it gets pinned too."""
    from src.research.families.opening_window.labelling import slippage_profile
    b = _bars(("AAA",), n=20)
    p = _panel(b, [("AAA", i, 100.0, 1.0) for i in range(10)])
    p["open_raw"] = [100.0] * 5 + [50.0] * 5          # +0% then +100% slippage
    p["vol_5m_pct_of_median_daily"] = [1.0] * 5 + [30.0] * 5
    lab = attach_labels(p, b, LabelConfig(horizons=(1,), benchmark=False))
    rows = slippage_profile(lab, "vol_5m_pct_of_median_daily", [0, 10, np.inf])
    assert [r["n"] for r in rows] == [5, 5]
    assert rows[0]["mean_pct"] == pytest.approx(0.0)
    assert rows[1]["mean_pct"] == pytest.approx(100.0)
    assert rows[1]["pct_up"] == pytest.approx(100.0)


def test_stop_is_read_at_the_same_time_as_the_entry():
    """The corrected semantics. See H004.

    Entry is `close_5m`, the price at 09:20, so the running low must be the low
    *through* 09:20 (`low_5m`). Paired that way, `running_low <= entry` holds by
    construction and the stop is strictly below the entry — always, not usually.
    """
    b = _bars(("AAA",), n=20)
    p = _panel(b, [("AAA", 0, 100.0, 1.0), ("AAA", 1, 100.0, 1.0)])
    p["low_5m"] = [98.0, 99.5]
    lab = attach_labels(p, b, LabelConfig(horizons=(5,), benchmark=False,
                                          stop_buffer_pct=0.0)).sort_values("date")
    assert lab["low_to_entry_pct"].tolist() == pytest.approx([-2.0, -0.5])
    assert (lab["stop_dist_pct"] <= 0).all()
    # Flat series at 100: neither stop is reached.
    assert lab["stop_touched_5d"].tolist() == [False, False]


def test_a_running_low_above_the_entry_is_rejected_not_recorded():
    """The Phase 2.4 bug must fail loudly rather than produce a number.

    Pairing a low from one moment with a price from another is how a stop ends
    up above an entry; there is no market state in which that is real.
    """
    b = _bars(("AAA",), n=20)
    p = _panel(b, [("AAA", 0, 100.0, 1.0)])
    p["low_5m"] = 101.0                      # impossible at the same `t`
    with pytest.raises(AssertionError, match="same time"):
        attach_labels(p, b, LabelConfig(horizons=(5,), benchmark=False))


def test_the_setup_being_tight_does_not_make_the_stop_tight():
    """Open 100, running low 99.80, entry 103: low 0.2% under open, stop 3.2% under entry."""
    b = _bars(("AAA",), n=20)
    p = _panel(b, [("AAA", 0, 103.0, 1.0)])
    p["open_raw"] = 100.0
    p["low_5m"] = 99.80
    lab = attach_labels(p, b, LabelConfig(horizons=(5,), benchmark=False,
                                          stop_buffer_pct=0.1))
    assert (lab["low_5m"] / lab["open_raw"] - 1).iloc[0] * 100 == pytest.approx(-0.20)
    assert lab["stop_dist_pct"].iloc[0] == pytest.approx(-3.20, abs=0.02)


def test_stop_and_target_flags_use_the_adjusted_entry():
    b = _bars(("AAA",), n=20)
    b.loc[b.index[1:], "high"] = 120.0
    p = _panel(b, [("AAA", 0, 1000.0, 0.1)])     # raw 1000, adjusted 100
    p["low_5m"] = 990.0                          # raw, i.e. adjusted 99
    lab = attach_labels(p, b, LabelConfig(horizons=(5,), benchmark=False,
                                          target_pct=15.0, stop_buffer_pct=0.0))
    assert lab["stop_dist_pct"].iloc[0] == pytest.approx(-1.0)
    assert bool(lab["target_touched_5d"].iloc[0]) is True
