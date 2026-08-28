"""H058 Stage 0: the deck, its seals, and the report that scores it."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.research.families import setup_grind


def _bars(symbols=("AAA", "BBB", "CCC"), n=260, seed=3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    dates = pd.bdate_range("2021-01-01", periods=n)
    for index, symbol in enumerate(symbols):
        close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, n)))
        open_ = close * (1 + rng.normal(0, 0.004, n))
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
        frames.append(pd.DataFrame({
            "symbol": symbol, "date": dates, "open": open_, "high": high,
            "low": low, "close": close,
            "volume": rng.integers(10_000, 90_000, n).astype(float),
        }))
    return pd.concat(frames, ignore_index=True)


def _universe(bars: pd.DataFrame) -> pd.DataFrame:
    return bars[["symbol", "date"]].rename(columns={"date": "session"})


def _partitions(bars: pd.DataFrame, cut: int = 200) -> pd.DataFrame:
    dates = sorted(bars["date"].unique())
    early = set(dates[:cut])
    frame = bars[["symbol", "date"]].copy()
    frame["partition"] = np.where(frame["date"].isin(early), "train", "validation")
    return frame


def test_session_aligned_guard_rejects_the_as_of_panel_layout():
    """The as-of-open panel carries date D's open beside D-1's high and low.

    Those four numbers are not one candle, and drawing them as one puts the
    next session's opening print on a chart that must end at the decision bar.
    """
    bars = _bars()
    setup_grind.assert_session_aligned(bars)  # honest bars pass

    leaky = bars.copy()
    leaky["open"] = leaky.groupby("symbol")["open"].shift(-1)
    leaky = leaky.dropna(subset=["open"])
    with pytest.raises(setup_grind.SetupGrindError, match="not one session's OHLC"):
        setup_grind.assert_session_aligned(leaky)


def test_eligible_decisions_respects_the_partition_and_the_universe():
    bars = _bars()
    decisions = setup_grind.eligible_decisions(
        bars, _universe(bars), _partitions(bars), partition="validation")
    assert not decisions.empty
    assert set(decisions["symbol"]) <= {"AAA", "BBB", "CCC"}
    validation_dates = set(_partitions(bars).query("partition == 'validation'")["date"])
    assert set(decisions["date"]) <= validation_dates

    narrow = _universe(bars)
    narrow = narrow[narrow["symbol"] == "AAA"]
    only_aaa = setup_grind.eligible_decisions(
        bars, narrow, _partitions(bars), partition="validation")
    assert set(only_aaa["symbol"]) == {"AAA"}


def test_eligible_decisions_refuses_a_hand_written_window():
    bars = _bars()
    unpartitioned = bars[["symbol", "date"]].copy()
    with pytest.raises(setup_grind.SetupGrindError, match="splits.assign"):
        setup_grind.eligible_decisions(bars, _universe(bars), unpartitioned)


def test_repeats_sit_far_from_their_originals():
    bars = _bars(symbols=[f"S{i:02d}" for i in range(80)], n=260)
    decisions = setup_grind.eligible_decisions(
        bars, _universe(bars), _partitions(bars), partition="validation")
    deck = setup_grind.build_deck(decisions, n_unique=120, n_repeats=30)

    assert len(deck) == 150
    repeats = deck[deck["is_repeat"]]
    assert len(repeats) == 30
    gaps = repeats["slot"].astype(int) - repeats["repeat_of_slot"].astype(int)
    assert gaps.min() >= setup_grind.MIN_REPEAT_GAP
    # A repeat must be the same decision, drawn on a differently framed chart.
    for _, repeat in repeats.iterrows():
        source = deck.loc[deck["slot"] == repeat["repeat_of_slot"]].iloc[0]
        assert (repeat["symbol"], repeat["date"]) == (source["symbol"], source["date"])
        assert repeat["history_bars"] != source["history_bars"]


def test_frozen_bundle_hides_identity_and_which_cases_are_repeats(tmp_path):
    bars = _bars(symbols=[f"S{i:02d}" for i in range(20)], n=260)
    decisions = setup_grind.eligible_decisions(
        bars, _universe(bars), _partitions(bars), partition="validation")
    deck = setup_grind.build_deck(decisions, n_unique=20, n_repeats=5,
                                  max_per_symbol=2, min_repeat_gap=10)
    manifest = setup_grind.freeze_stage0_bundle(deck, bars, tmp_path / "bundle")

    assert manifest["outcome_accessed"] is False
    assert manifest["ready_cases"] == 25
    public = [json.loads(line) for line in
              (tmp_path / "bundle" / "cases.jsonl").read_text().splitlines()]
    for record in public:
        assert not any(key.endswith("_private") for key in record)
        # No symbol, no date, and nothing saying this chart has been seen before.
        assert "repeat" not in json.dumps(record)
    private = [json.loads(line) for line in
               (tmp_path / "bundle" / "cases_private.jsonl").read_text().splitlines()]
    assert sum(1 for record in private if record["is_repeat_private"]) == 5

    with pytest.raises(setup_grind.SetupGrindError, match="already exists"):
        setup_grind.freeze_stage0_bundle(deck, bars, tmp_path / "bundle")


def test_atr_comes_from_the_visible_window_only():
    """A future bar may not move a number the reviewer prices against."""
    bars = _bars(symbols=("AAA",), n=200)
    window = bars.head(140)
    before = setup_grind.true_range_atr(window)
    shocked = bars.copy()
    shocked.loc[150:, ["high", "close"]] *= 5.0
    after = setup_grind.true_range_atr(shocked.head(140))
    assert before == pytest.approx(after)


def test_a_deck_too_small_to_separate_its_repeats_is_refused():
    """Better to refuse than to quietly hand back a memory test."""
    bars = _bars(symbols=[f"S{i:02d}" for i in range(20)], n=260)
    decisions = setup_grind.eligible_decisions(
        bars, _universe(bars), _partitions(bars), partition="validation")
    with pytest.raises(setup_grind.SetupGrindError, match="cannot hold"):
        setup_grind.build_deck(decisions, n_unique=20, n_repeats=5,
                               min_repeat_gap=60)


def _pass(actions, *, annotator="owner", prompt="P", seconds=5.0):
    """One frozen human pass over a deck of `actions`, keyed by case id."""
    rows = []
    for case_id, action in actions.items():
        row = {"case_id": case_id, "annotator": annotator, "annotator_kind": "human",
               "provider": "", "model": "", "prompt_hash": prompt,
               "action": action, "notes": "", "seconds_elapsed": seconds,
               "entry_atr": None, "stop_atr": None, "target_atr": None,
               "conviction": None}
        if action == "take":
            row.update({"entry_atr": 0.5, "stop_atr": -0.5, "target_atr": 2.0,
                        "conviction": 2, "seconds_elapsed": 20.0})
        rows.append(row)
    return pd.DataFrame(rows)


def _stage0_fixture(tmp_path, n_unique=60, n_repeats=25):
    bars = _bars(symbols=[f"S{i:02d}" for i in range(60)], n=260)
    decisions = setup_grind.eligible_decisions(
        bars, _universe(bars), _partitions(bars), partition="validation")
    deck = setup_grind.build_deck(decisions, n_unique=n_unique, n_repeats=n_repeats,
                                  max_per_symbol=2, min_repeat_gap=10)
    manifest = setup_grind.freeze_stage0_bundle(deck, bars, tmp_path / "bundle")
    private = [json.loads(line) for line in
               (tmp_path / "bundle" / "cases_private.jsonl").read_text().splitlines()]
    return manifest, private


def test_report_scores_a_perfectly_consistent_pass_as_proceed(tmp_path):
    manifest, private = _stage0_fixture(tmp_path)
    slots = {record["slot_private"]: record["case_id"] for record in private}
    actions = {}
    for record in private:
        source = slots.get(record.get("repeat_of_slot_private"), record["case_id"])
        # Take every fourth decision, and answer a repeat the way its original
        # was answered -- a perfectly reproducible reviewer.
        actions[record["case_id"]] = (
            "take" if int(source.split("_")[-1]) % 4 == 0 else "skip")

    report = setup_grind.stage0_report(
        _pass(actions, prompt=manifest["annotation_prompt_hash"]),
        manifest, private, annotator="owner")
    assert report["outcome_accessed"] is False
    assert report["consistency"]["take_skip_kappa"] == pytest.approx(1.0)
    assert report["verdict"] == "proceed_full"
    # Counted over first showings only: a repeat is one decision, not two.
    originals = [record for record in private if not record["is_repeat_private"]]
    assert report["take_rate"]["first_showings"] == len(originals)
    assert report["take_rate"]["takes"] == sum(
        1 for record in originals if actions[record["case_id"]] == "take")


def test_report_stops_the_programme_on_a_coin_flipping_reviewer(tmp_path):
    manifest, private = _stage0_fixture(tmp_path)
    rng = np.random.default_rng(0)
    actions = {record["case_id"]: ("take" if rng.random() < 0.5 else "skip")
               for record in private}
    report = setup_grind.stage0_report(
        _pass(actions, prompt=manifest["annotation_prompt_hash"]),
        manifest, private, annotator="owner")
    assert report["verdict"] in ("stop", "redraw_deck", "inconclusive")


def test_report_refuses_a_pass_that_answered_a_different_prompt(tmp_path):
    manifest, private = _stage0_fixture(tmp_path)
    actions = {record["case_id"]: "skip" for record in private}
    frame = _pass(actions, prompt="a-different-prompt")
    with pytest.raises(setup_grind.SetupGrindError, match="different test"):
        setup_grind.stage0_report(frame, manifest, private, annotator="owner")


def test_report_flags_a_stop_on_the_wrong_side_of_the_entry(tmp_path):
    manifest, private = _stage0_fixture(tmp_path)
    actions = {record["case_id"]: "skip" for record in private}
    first = private[0]["case_id"]
    actions[first] = "take"
    frame = _pass(actions, prompt=manifest["annotation_prompt_hash"])
    frame.loc[frame["case_id"].eq(first), "stop_atr"] = 3.0  # above both others
    report = setup_grind.stage0_report(frame, manifest, private, annotator="owner")
    assert report["geometry_violations"] == [
        {"case_id": first, "problem": "entry_outside_stop_target"}]


def test_sizing_uses_the_measured_take_rate():
    """The whole point of Stage 0 is to replace the assumed rate with a real one."""
    slow = setup_grind.stage2_sizing(0.10, 5.0, 20.0)
    fast = setup_grind.stage2_sizing(0.40, 5.0, 20.0)
    for cheap, dear in zip(fast, slow):
        assert cheap["detectable_edge_r"] == dear["detectable_edge_r"]
        assert cheap["takes_needed"] == dear["takes_needed"]
        assert cheap["charts_needed"] < dear["charts_needed"]
        assert cheap["hours"] < dear["hours"]
    # A smaller detectable edge always costs more, never less.
    edges = [row["hours"] for row in slow]
    assert edges == sorted(edges)


def test_report_accepts_a_pass_the_interface_left_unstamped(tmp_path):
    """Human passes frozen before the hash was stamped are unverifiable, not wrong.

    Refusing them outright would have thrown away a completed grind; accepting
    them silently would hide that the pass cannot be tied to its prompt. It is
    accepted and flagged.
    """
    manifest, private = _stage0_fixture(tmp_path)
    actions = {record["case_id"]: "skip" for record in private}
    report = setup_grind.stage0_report(
        _pass(actions, prompt=""), manifest, private, annotator="owner")
    assert report["prompt_hash_unverified"] is True

    stamped = setup_grind.stage0_report(
        _pass(actions, prompt=manifest["annotation_prompt_hash"]),
        manifest, private, annotator="owner")
    assert stamped["prompt_hash_unverified"] is False
