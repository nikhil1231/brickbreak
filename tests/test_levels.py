"""Causality, timeframe portability and detector behaviour for level books."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research_data.pipelines import levels


def synthetic_bars(sessions: int = 40, symbols: tuple[str, ...] = ("AAA", "BBB"),
                   seed: int = 7, bars_per_session: int = 75) -> pd.DataFrame:
    """A deterministic five-minute panel with a real session structure."""
    rng = np.random.default_rng(seed)
    rows = []
    days = pd.bdate_range("2023-01-02", periods=sessions)
    for symbol in symbols:
        price = 500.0
        for day in days:
            start = day + pd.Timedelta(hours=9, minutes=15)
            for index in range(bars_per_session):
                step = float(rng.normal(0, 0.6))
                open_price = price
                close = max(1.0, price + step)
                high = max(open_price, close) + abs(float(rng.normal(0, 0.2)))
                low = min(open_price, close) - abs(float(rng.normal(0, 0.2)))
                bar_end = start + pd.Timedelta(minutes=5 * (index + 1))
                rows.append({
                    "symbol": symbol, "session": day, "bar_end": bar_end,
                    "open": open_price, "high": high, "low": low, "close": close,
                    "volume": float(rng.integers(500, 5000)),
                })
                price = close
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def bars() -> pd.DataFrame:
    return synthetic_bars()


@pytest.mark.parametrize("detector", sorted(levels.DETECTORS))
def test_levels_are_knowable_only_after_their_inputs_closed(bars, detector):
    book = levels.DETECTORS[detector](bars)
    assert not book.empty, f"{detector} produced no levels on the fixture"
    known = pd.to_datetime(book["known_at"])
    origin = pd.to_datetime(book["origin_at"])
    assert (known >= origin).all(), f"{detector} knows a level before it existed"


@pytest.mark.parametrize("detector", sorted(levels.DETECTORS))
def test_future_bars_cannot_change_an_already_knowable_level(bars, detector):
    """The append test: truncating the future must not move a past level."""
    cutoff = pd.Timestamp("2023-02-01")
    truncated = bars.loc[bars["session"] < cutoff]
    full_book = levels.DETECTORS[detector](bars)
    part_book = levels.DETECTORS[detector](truncated)

    horizon = pd.to_datetime(part_book["known_at"]).max()
    columns = ["symbol", "detector", "center", "lower", "upper", "known_at"]
    full_view = full_book.loc[
        pd.to_datetime(full_book["known_at"]) <= horizon, columns]
    part_view = part_book.loc[
        pd.to_datetime(part_book["known_at"]) <= horizon, columns]
    numeric = ["center", "lower", "upper"]
    full_view = full_view.sort_values(columns).reset_index(drop=True)
    part_view = part_view.sort_values(columns).reset_index(drop=True)
    full_view[numeric] = full_view[numeric].astype(float).round(9)
    part_view[numeric] = part_view[numeric].astype(float).round(9)
    pd.testing.assert_frame_equal(full_view, part_view)


def test_session_atr_is_lagged(bars):
    """The scaling unit must not contain the session it scales."""
    atr = levels.session_atr(bars)
    first = atr.groupby("symbol", sort=False).head(1)
    assert first["session_atr"].isna().all()
    merged = atr.sort_values(["symbol", "session"]).copy()
    # A session whose own range explodes must not change its own ATR.
    spiked = bars.copy()
    target = spiked["session"].max()
    mask = spiked["session"].eq(target)
    spiked.loc[mask, "high"] = spiked.loc[mask, "high"] * 5
    after = levels.session_atr(spiked).sort_values(["symbol", "session"])
    pd.testing.assert_series_equal(
        merged["session_atr"].reset_index(drop=True),
        after["session_atr"].reset_index(drop=True))


def test_anchor_levels_recover_the_prior_session_extremes(bars):
    book = levels.detect_anchor(bars)
    single = bars.loc[bars["symbol"] == "AAA"]
    daily = single.groupby("session").agg(high=("high", "max"), low=("low", "min"))
    sessions = list(daily.index)
    prior, target = sessions[5], sessions[6]
    centers = book.loc[
        (book["symbol"] == "AAA")
        & (pd.to_datetime(book["known_at"]).dt.normalize() == target),
        "center"].to_numpy(float)
    assert np.isclose(centers, daily.loc[prior, "high"], atol=1e-6).any()
    assert np.isclose(centers, daily.loc[prior, "low"], atol=1e-6).any()


def test_significance_detectors_are_timeframe_portable(bars):
    """A level defined by where trading happened survives a bar-size change.

    `fractal` is excluded because it is defined by a bar pattern and is expected
    to change — that difference is the reason it is only a baseline.
    """
    hourly = levels.resample_hourly(bars).rename(columns={"bucket_start": "_drop"})
    hourly = hourly[["symbol", "session", "bar_end", "open", "high", "low",
                     "close", "volume"]]
    for detector in ("anchor", "multi_touch"):
        fine = levels.DETECTORS[detector](bars)
        coarse = levels.DETECTORS[detector](hourly)
        fine_centers = set(np.round(fine["center"].to_numpy(float), 4))
        coarse_centers = set(np.round(coarse["center"].to_numpy(float), 4))
        overlap = len(fine_centers & coarse_centers) / max(len(fine_centers), 1)
        assert overlap > 0.80, f"{detector} lost {1 - overlap:.0%} of levels"


def test_fractal_is_not_timeframe_portable(bars):
    """States the incumbent's defect as a test rather than as an opinion."""
    hourly = levels.resample_hourly(bars)[
        ["symbol", "session", "bar_end", "open", "high", "low", "close", "volume"]]
    fine = set(np.round(levels.detect_fractal(bars)["center"].to_numpy(float), 4))
    coarse = set(np.round(levels.detect_fractal(hourly)["center"].to_numpy(float), 4))
    overlap = len(fine & coarse) / max(len(fine), 1)
    assert overlap < 0.50


def test_hourly_buckets_are_session_aligned_and_flag_partials(bars):
    hourly = levels.resample_hourly(bars)
    offsets = (hourly["bucket_start"] - hourly["session"]).dt.total_seconds() / 60
    assert set(np.unique(offsets)) <= {555.0, 615.0, 675.0, 735.0, 795.0, 855.0, 915.0}
    complete = hourly.loc[hourly["complete"]]
    assert (complete["five_minute_bars"] == 12).all()
    assert (~hourly["complete"]).any(), "a 375-minute session must leave a partial"


def test_multi_touch_requires_distinct_sessions(bars):
    book = levels.detect_multi_touch(bars)
    assert (book["source_sessions"] >= 2).all()
    assert (book["significance"] >= 2).all()


def test_volume_profile_nodes_sit_inside_the_traded_range(bars):
    book = levels.detect_volume_profile(bars)
    assert not book.empty
    for symbol, group in book.groupby("symbol"):
        traded = bars.loc[bars["symbol"] == symbol]
        assert group["center"].min() >= traded["low"].min() - 1e-6
        assert group["center"].max() <= traded["high"].max() + 1e-6


def test_unknown_detector_is_refused(bars):
    with pytest.raises(levels.LevelError):
        levels.build_level_book(bars, detectors=("not_a_detector",))
