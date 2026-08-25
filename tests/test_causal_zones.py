import numpy as np
import pandas as pd

from src.research_data.pipelines.causal_zones import (
    FEATURE_COLUMNS,
    ZoneConfig,
    annotate_corporate_actions,
    build_zone_state_machine,
)


def bars(closes, *, start="2026-01-02 09:15", symbol="TEST"):
    close = np.asarray(closes, dtype=float)
    times = pd.date_range(start, periods=len(close), freq="5min")
    return pd.DataFrame({
        "symbol_asof": symbol,
        "bar_start": times,
        "bar_end": times + pd.Timedelta(minutes=5),
        "available_at": times + pd.Timedelta(minutes=5),
        "open_raw": close - 0.05,
        "high_raw": close + 0.20,
        "low_raw": close - 0.20,
        "close_raw": close,
        "volume_raw": np.arange(len(close)) * 10 + 100,
        "quality_flags": "",
    })


def test_future_append_cannot_rewrite_any_past_feature():
    prefix = bars([10, 9.5, 9, 9.4, 9.8, 10.2, 9.9, 10.4])
    future = bars([50, 1, 75], start="2026-01-02 09:55")
    full = pd.concat([prefix, future], ignore_index=True)
    short_result = build_zone_state_machine(prefix)
    full_result = build_zone_state_machine(full).iloc[:len(prefix)].reset_index(drop=True)
    pd.testing.assert_frame_equal(
        short_result[list(FEATURE_COLUMNS)].reset_index(drop=True),
        full_result[list(FEATURE_COLUMNS)],
        check_dtype=False,
    )


def test_pivot_is_unknown_until_right_confirmation_bar_closes():
    frame = bars([10, 9, 8, 9, 10])
    result = build_zone_state_machine(frame, ZoneConfig(width_atr=0.10))
    assert pd.isna(result.loc[3, "support_known_at"])
    assert result.loc[4, "support_origin_at"] == frame.loc[2, "bar_end"]
    assert result.loc[4, "support_known_at"] == frame.loc[4, "bar_end"]
    assert result.loc[4, "support_known_at"] <= frame.loc[4, "available_at"]


def test_break_then_later_retest_is_causal():
    frame = bars([8, 9, 10, 9, 8, 10.8, 10.2])
    frame.loc[6, ["low_raw", "close_raw", "high_raw"]] = [9.95, 10.35, 10.45]
    result = build_zone_state_machine(
        frame, ZoneConfig(width_atr=0.10, break_atr=0.05, merge_atr=0.20))
    assert result.loc[5, "support_zone_kind"] == "flip_support"
    assert not bool(result.loc[5, "bullish_flip_retest"])
    assert bool(result.loc[6, "bullish_flip_retest"])
    assert result.loc[6, "support_broken_at"] == frame.loc[5, "bar_end"]


def test_support_break_then_retest_from_below_is_causal():
    frame = bars([10, 9, 8, 9, 10, 7.2, 7.65])
    frame.loc[6, ["low_raw", "close_raw", "high_raw"]] = [7.55, 7.65, 8.05]
    result = build_zone_state_machine(
        frame, ZoneConfig(width_atr=0.10, break_atr=0.05, merge_atr=0.20))
    assert result.loc[5, "resistance_zone_kind"] == "flip_resistance"
    assert not bool(result.loc[5, "bearish_flip_retest"])
    assert bool(result.loc[6, "bearish_flip_retest"])
    assert result.loc[6, "resistance_broken_at"] == frame.loc[5, "bar_end"]


def test_higher_timeframe_ema_excludes_a_forming_hour():
    sessions = pd.bdate_range("2025-01-01", periods=51)
    frames = []
    for index, day in enumerate(sessions):
        frame = bars(
            np.linspace(100 + index, 100.5 + index, 12),
            start=f"{day.date()} 09:15")
        frames.append(frame)
    result = build_zone_state_machine(pd.concat(frames, ignore_index=True))
    final_session = result["bar_start"].dt.normalize().eq(sessions[-1])
    rows = result.loc[final_session].reset_index(drop=True)
    assert rows.loc[:10, "htf_ema_50"].nunique(dropna=False) == 1
    assert pd.notna(rows.loc[11, "htf_ema_50"])
    assert rows.loc[11, "htf_ema_50"] != rows.loc[10, "htf_ema_50"]


def test_time_of_day_volume_denominator_excludes_current_session():
    sessions = pd.date_range("2026-01-01", periods=7, freq="D")
    frames = [bars([100], start=f"{day.date()} 09:15") for day in sessions]
    frame = pd.concat(frames, ignore_index=True)
    frame["volume_raw"] = [10, 20, 30, 40, 50, 600, 700]
    result = build_zone_state_machine(frame)
    # At the sixth observation the denominator is the median of the five prior
    # same-clock bars; its own 600 cannot enter it.
    assert result.loc[5, "tod_volume_median_20"] == 30
    assert result.loc[5, "lagged_time_of_day_volume_surprise"] == 20


def test_rolling_hour_does_not_bridge_the_overnight_gap():
    first = bars(range(13), start="2026-01-02 14:25")
    second = bars([20], start="2026-01-05 09:15")
    frame = pd.concat([first, second], ignore_index=True)
    result = build_zone_state_machine(frame)
    assert pd.notna(result.loc[12, "rolling_hour_trend_pct"])
    assert pd.isna(result.loc[13, "rolling_hour_trend_pct"])


def test_corporate_action_invalidates_old_zones():
    frame = bars([10, 9, 8, 9, 10, 10.1])
    frame.loc[5, "quality_flags"] = "corporate_action"
    result = build_zone_state_machine(frame)
    assert result.loc[4, "support_zone_kind"] == "support"
    assert result.loc[5, "support_zone_kind"] == ""


def test_adjustment_change_flags_only_the_first_bar_of_the_ex_session():
    frame = pd.concat([
        bars([10, 9, 8, 9, 10], start="2026-01-02 09:15"),
        bars([5, 5.1], start="2026-01-05 09:15"),
    ], ignore_index=True)
    frame["session"] = frame["bar_start"].dt.normalize()
    daily = pd.DataFrame({
        "symbol": ["TEST", "TEST"],
        "date": pd.to_datetime(["2026-01-02", "2026-01-05"]),
        "adj_factor": [1.0, 2.0],
    })
    flagged = annotate_corporate_actions(frame, daily)
    assert flagged.loc[5, "quality_flags"] == "corporate_action"
    assert flagged.loc[6, "quality_flags"] == ""
