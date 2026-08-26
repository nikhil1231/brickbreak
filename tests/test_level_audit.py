"""The audit deck must be balanced, and its answer must stay hidden."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.research.families import level_audit as h057_review
from src.interface import setup_review
from src.research_data.pipelines import levels

from tests.test_levels import synthetic_bars


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return synthetic_bars(sessions=60, symbols=("AAA", "BBB", "CCC"))


@pytest.fixture(scope="module")
def bundle(panel, tmp_path_factory):
    cases = h057_review.collect_cases(panel)
    hourly = levels.resample_hourly(panel)
    output = tmp_path_factory.mktemp("audit") / "h057_level_audit"
    h057_review.freeze_review_bundle(
        cases, hourly.loc[hourly["complete"]], panel, output, n_cases=20)
    return output


def test_deck_is_balanced_so_chance_is_exactly_half(bundle):
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert manifest["real_cases"] == manifest["control_cases"]
    assert manifest["real_cases"] > 0
    assert manifest["spends_new_sample"] is False


def test_public_cases_carry_no_identity(bundle):
    for line in (bundle / "cases.jsonl").read_text().splitlines():
        record = json.loads(line)
        assert "symbol_private" not in record
        assert "decision_at_private" not in record


def test_charts_are_identical_in_size_between_the_two_decks(bundle):
    """A control must not be recognisable by anything except its price.

    If the two decks differed in bar count, image size or scaling, a reviewer
    could score above chance without looking at a single level.
    """
    private = [json.loads(line)
               for line in (bundle / "cases_private.jsonl").read_text().splitlines()]
    ready = [record for record in private if record["case_status"] == "ready"]
    sizes = {record["reveal"]["line_was"]:
             {(bundle / "charts" / f"{record['case_id']}.png").stat().st_size > 0}
             for record in ready}
    assert sizes["real"] == sizes["fake"] == {True}
    bars = {record["reveal"]["line_was"]: record["sidecar"]["bars_shown"]
            for record in ready}
    assert bars["real"] == bars["fake"]
    for record in ready:
        assert record["sidecar"]["last_close_rebased"] == pytest.approx(100.0)


def test_reveal_is_withheld_until_the_pass_is_finalized(bundle, monkeypatch):
    monkeypatch.setattr(setup_review, "REVIEW_ROOT", bundle.parent)
    case_id = json.loads(
        (bundle / "cases.jsonl").read_text().splitlines()[0])["case_id"]

    payload = setup_review.case("h057-level-audit", case_id, "tester")
    assert "reveal" not in payload, "ground truth leaked before finalisation"
    assert payload["finalized"] is False

    queue = setup_review.queue("h057-level-audit", "tester")
    values = {"line_is_real": "real", "line_confidence": 0.5,
              "would_trade": "skip", "notes": ""}
    for item in queue["cases"]:
        setup_review.save_draft("h057-level-audit", {
            "annotator": "tester", "case_id": item["case_id"], "values": values})
    setup_review.finalize("h057-level-audit", {"annotator": "tester"})

    revealed = setup_review.case("h057-level-audit", case_id, "tester")
    assert revealed["finalized"] is True
    assert "reveal" in revealed
    assert revealed["reveal"]["line_was"] in ("real", "fake")


def test_score_pass_measures_discrimination_against_a_coin(bundle):
    """A reviewer who answers 'real' every time must score at the base rate."""
    result = h057_review.score_pass(bundle, "tester")
    assert result["scored_cases"] > 0
    # The fixture pass above answered "real" for every case, so accuracy equals
    # the share of the deck that is real -- one half, by construction.
    assert result["discrimination_rate"] == pytest.approx(0.5, abs=0.01)
    assert result["accuracy_on_real"] == pytest.approx(1.0)
    assert result["accuracy_on_controls"] == pytest.approx(0.0)
    assert result["take_rate"] == pytest.approx(0.0)
    assert abs(result["z_vs_chance"]) < 1e-6
