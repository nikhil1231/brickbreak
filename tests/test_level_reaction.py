"""The reaction test must find a planted effect and must find nothing in noise."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.research.families import level_reaction
from src.research_data.pipelines import levels

from tests.test_levels import synthetic_bars


@pytest.fixture(scope="module")
def bars() -> pd.DataFrame:
    return synthetic_bars(sessions=45)


@pytest.fixture(scope="module")
def reference(bars) -> pd.DataFrame:
    return level_reaction._reference_frame(bars, levels.LevelConfig())


def test_race_resolves_to_whichever_barrier_comes_first():
    """Constructed paths, known answers — the statistic must read the tape."""
    path = pd.DataFrame({
        "symbol": ["AAA"] * 4,
        "bar_end": pd.date_range("2023-01-02 10:20", periods=4, freq="5min"),
        "session": [pd.Timestamp("2023-01-02")] * 4,
        "open": [100.0] * 4, "close": [100.0] * 4,
        # atr 2.0 and barrier 0.5 put the barriers at 99 and 101. Bar 1 takes
        # out 99 only; bar 2 takes out 101. Keeping them in separate bars is
        # what makes the expected answer unambiguous.
        "high": [100.5, 100.8, 104.0, 104.0],
        "low": [99.5, 98.9, 99.5, 96.0],
        "volume": [1000.0] * 4,
    })
    base = {
        "symbol": "AAA", "session": pd.Timestamp("2023-01-02"),
        "level_id": "L1", "detector": "anchor", "book": "real",
        "approach_at": pd.Timestamp("2023-01-02 10:15"),
        "reference_price": 100.0, "atr": 2.0, "distance_atr": 0.5,
    }
    # Approaching from below, the fall to 99 lands at bar 1 while the rise to
    # 101 lands at bar 2, so the path turns back before it carries on.
    below = level_reaction.race_barriers(
        pd.DataFrame([{**base, "approach_from": "below"}]), path, 0.5, 4)
    assert below["outcome"].iloc[0] == "rejection"
    # Approaching from above reverses which barrier is which.
    above = level_reaction.race_barriers(
        pd.DataFrame([{**base, "approach_from": "above"}]), path, 0.5, 4)
    assert above["outcome"].iloc[0] == "penetration"
    # A horizon that ends before either barrier resolves nothing.
    short = level_reaction.race_barriers(
        pd.DataFrame([{**base, "approach_from": "below"}]), path, 0.5, 1)
    assert short["outcome"].iloc[0] == "neither"


def test_both_barriers_inside_one_bar_is_ambiguous_not_guessed():
    path = pd.DataFrame({
        "symbol": ["AAA"], "bar_end": [pd.Timestamp("2023-01-02 10:20")],
        "session": [pd.Timestamp("2023-01-02")], "open": [100.0],
        "high": [105.0], "low": [95.0], "close": [100.0], "volume": [1.0],
    })
    event = pd.DataFrame([{
        "symbol": "AAA", "session": pd.Timestamp("2023-01-02"), "level_id": "L1",
        "detector": "anchor", "book": "real",
        "approach_at": pd.Timestamp("2023-01-02 10:15"), "approach_from": "below",
        "reference_price": 100.0, "atr": 2.0, "distance_atr": 0.5,
    }])
    scored = level_reaction.race_barriers(event, path, 0.5, 4)
    assert scored["outcome"].iloc[0] == "ambiguous"


def test_approaches_are_first_touches_only(bars, reference):
    hourly = levels.resample_hourly(bars)
    decisions = hourly.loc[hourly["complete"]]
    book = levels.detect_anchor(bars)
    events = level_reaction.find_approaches(decisions, book, reference)
    assert not events.empty
    assert set(events["approach_from"]) <= {"above", "below"}
    # One event per contiguous run of touching bars.
    counts = events.groupby(["symbol", "level_id"]).size()
    assert counts.max() < len(decisions)


def test_no_approach_is_dated_before_its_level_was_knowable(bars, reference):
    hourly = levels.resample_hourly(bars)
    decisions = hourly.loc[hourly["complete"]]
    for name in levels.DETECTORS:
        book = levels.DETECTORS[name](bars)
        events = level_reaction.find_approaches(decisions, book, reference)
        if events.empty:
            continue
        merged = events.merge(
            book[["level_id", "known_at"]], on="level_id", how="left")
        assert (pd.to_datetime(merged["approach_at"])
                >= pd.to_datetime(merged["known_at"])).all()


def test_permuted_geometry_preserves_distance_but_moves_the_price(bars, reference):
    book = levels.detect_anchor(bars)
    config = level_reaction.ReactionConfig(pseudo_per_real=30)
    fake = level_reaction.build_pseudo_book(
        book, reference, "permuted_geometry", config)
    assert not fake.empty

    def offsets(frame: pd.DataFrame) -> np.ndarray:
        work = frame.copy()
        work["session"] = pd.to_datetime(work["known_at"]).dt.normalize()
        merged = work.merge(reference, on=["symbol", "session"], how="left")
        merged = merged.loc[merged["atr"].gt(0)]
        return ((merged["center"] - merged["prior_close"]) / merged["atr"]) \
            .abs().dropna().to_numpy(float)

    real_offsets, fake_offsets = offsets(book), offsets(fake)
    # The control must look like the real book in distance-from-reference...
    assert abs(np.median(real_offsets) - np.median(fake_offsets)) < 0.75
    # ...while almost never landing on the same price.
    shared = set(np.round(book["center"], 4)) & set(np.round(fake["center"], 4))
    assert len(shared) / max(len(set(np.round(fake["center"], 4))), 1) < 0.05


def test_random_price_control_produces_a_book(bars, reference):
    book = levels.detect_multi_touch(bars)
    fake = level_reaction.build_pseudo_book(book, reference, "random_price")
    assert not fake.empty
    assert list(fake.columns) == list(levels.LEVEL_COLUMNS)


def test_unknown_control_is_refused(bars, reference):
    book = levels.detect_anchor(bars)
    with pytest.raises(level_reaction.ReactionError):
        level_reaction.build_pseudo_book(book, reference, "wishful_thinking")


def test_paired_contrast_drops_unpaired_symbol_sessions():
    summary = pd.DataFrame([
        {"symbol": "AAA", "session": pd.Timestamp("2023-01-02"),
         "detector": "anchor", "book": "real", "n_events": 3, "n_resolved": 3,
         "rejection_rate": 0.7},
        {"symbol": "AAA", "session": pd.Timestamp("2023-01-02"),
         "detector": "anchor", "book": "random_price", "n_events": 9,
         "n_resolved": 9, "rejection_rate": 0.5},
        # No control row exists for this session, so it cannot contribute.
        {"symbol": "BBB", "session": pd.Timestamp("2023-01-03"),
         "detector": "anchor", "book": "real", "n_events": 2, "n_resolved": 2,
         "rejection_rate": 0.9},
    ])
    contrast = level_reaction.paired_contrast(summary, "random_price")
    assert len(contrast) == 1
    assert contrast["contrast"].iloc[0] == pytest.approx(0.2)


def test_session_is_the_independent_unit_not_the_symbol_session():
    """Twenty symbols on one day are one observation, not twenty."""
    rows = [{"symbol": f"S{index}", "session": pd.Timestamp("2023-01-02"),
             "detector": "anchor", "contrast": 0.10} for index in range(20)]
    estimate = level_reaction.session_clustered_estimate(pd.DataFrame(rows))
    assert estimate["n_sessions"] == 1
    assert estimate["n_symbol_sessions"] == 20
    assert estimate["t_stat"] is None


def test_reaction_study_finds_nothing_in_a_random_walk(bars):
    """The null test. Synthetic bars contain no levels, so nothing may appear.

    This is the guard that matters most: a bug that manufactures an effect would
    make every later result meaningless, and it would look like success. The
    fixture is a driftless random walk, so the real book and the fake books are
    measuring the same nothing and the paired contrast must straddle zero.
    """
    config = level_reaction.ReactionConfig(
        pseudo_per_real=10, barrier_grid=(0.5,), horizon_grid=(24,))
    report = level_reaction.run_reaction_study(
        bars, detectors=("anchor", "multi_touch"), config=config)
    assert report["status"] == "complete"
    assert report["events"]["total"] > 0
    for cell in report["grid"]:
        if cell["t_stat"] is None:
            continue
        assert abs(cell["t_stat"]) < 3.0, (
            f"{cell['detector']}/{cell['control']} invented an effect in noise: "
            f"t={cell['t_stat']:.2f}")
    assert report["multiplicity"]["null_p"] > 0.01


def test_the_statistical_chain_detects_a_planted_barrier():
    """The power test: hand the chain a book that IS a real level.

    A test that only ever returns "nothing" is indistinguishable from a broken
    one, so the same approach/race/pairing code is run against a series with a
    genuine level in it: price is confined to a channel it cannot close through,
    and the real book sits exactly on the channel walls.

    The book is injected rather than detected, because this is a test of the
    measurement chain, not of any one detector's ability to find a wall — that
    question is what the study itself is for. An earlier version of this fixture
    floored the whole series instead of planting a local level, and the control
    correctly absorbed it: fake lines drawn anywhere in a globally floored series
    bounce exactly as often as real ones. That the control kills a global effect
    is the property everything else here depends on, so the fixture was fixed
    rather than the control.
    """
    rng = np.random.default_rng(3)
    low_wall, high_wall = 500.0, 512.0
    rows = []
    price = 506.0
    for symbol in ("CH1", "CH2"):
        for day in pd.bdate_range("2023-01-02", periods=60):
            start_at = day + pd.Timedelta(hours=9, minutes=15)
            for index in range(75):
                step = price + float(rng.normal(0, 1.0))
                close = min(max(step, low_wall + abs(float(rng.normal(0, 0.15)))),
                            high_wall - abs(float(rng.normal(0, 0.15))))
                high = min(high_wall - 0.02,
                           max(price, close) + abs(float(rng.normal(0, 0.25))))
                low = max(low_wall + 0.02,
                          min(price, close) - abs(float(rng.normal(0, 0.25))))
                rows.append({
                    "symbol": symbol, "session": day,
                    "bar_end": start_at + pd.Timedelta(minutes=5 * (index + 1)),
                    "open": price, "high": high, "low": low, "close": close,
                    "volume": float(rng.integers(500, 5000)),
                })
                price = close
    channel = pd.DataFrame(rows)
    assert (channel.groupby(["symbol", "session"])["low"].min() <= 500.5).mean() > 0.4

    config = level_reaction.ReactionConfig(
        pseudo_per_real=10, barrier_grid=(0.5,), horizon_grid=(24,))
    reference = level_reaction._reference_frame(channel, levels.LevelConfig())
    hourly = levels.resample_hourly(channel)
    decisions = hourly.loc[hourly["complete"]]
    path = levels._normalise_bars(channel)

    # A book that is the wall, re-emitted each session like a real detector.
    first_bar = channel.groupby(["symbol", "session"])["bar_end"].min()
    unit = reference.set_index(["symbol", "session"])["atr"]
    book_rows = []
    for (symbol, session), known_at in first_bar.items():
        atr = float(unit.get((symbol, session), np.nan))
        if not np.isfinite(atr) or atr <= 0:
            continue
        for wall, kind in ((low_wall, "support"), (high_wall, "resistance")):
            book_rows.append({
                "level_id": f"WALL_{symbol}_{session.date()}_{int(wall)}",
                "symbol": symbol, "detector": "wall", "kind": kind,
                "origin_at": known_at, "known_at": known_at,
                "valid_until": levels._session_end(known_at),
                "center": wall, "lower": wall - 0.25 * atr,
                "upper": wall + 0.25 * atr, "significance": 1.0,
                "source_sessions": 1,
            })
    book = pd.DataFrame(book_rows)[list(levels.LEVEL_COLUMNS)]

    events = [level_reaction.find_approaches(decisions, book, reference, config, "real")]
    for control in ("random_price", "permuted_geometry"):
        fake = level_reaction.build_pseudo_book(book, reference, control, config)
        assert not fake.empty, f"{control} produced no control levels"
        events.append(
            level_reaction.find_approaches(decisions, fake, reference, config, control))
    scored = level_reaction.race_barriers(
        pd.concat(events, ignore_index=True), path, 0.5, 24)
    summary = level_reaction.rejection_rate(scored)

    for control in ("random_price", "permuted_geometry"):
        contrast = level_reaction.paired_contrast(summary, control)
        estimate = level_reaction.session_clustered_estimate(contrast)
        assert estimate["mean_contrast"] > 0.05, (
            f"the chain could not see a channel wall against {control}: "
            f"{estimate['mean_contrast']}")
        assert estimate["t_stat"] > 3.0, (
            f"planted effect is not significant against {control}: "
            f"t={estimate['t_stat']}")
