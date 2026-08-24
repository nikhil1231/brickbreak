import hashlib
import json

import pandas as pd
import pytest

from src.interface import setup_review


COLUMNS = [
    "case_id", "annotator", "annotator_kind", "provider", "model",
    "prompt_hash", "decision", "confidence", "notes",
]


def make_bundle(tmp_path, monkeypatch):
    root = tmp_path / "research_store"
    bundle = root / "family" / "bundle"
    charts = bundle / "charts"
    charts.mkdir(parents=True)
    cases = []
    for index in range(2):
        case_id = f"CASE_{index}"
        content = b"\x89PNG\r\n" + bytes([index])
        (charts / f"{case_id}.png").write_bytes(content)
        cases.append({
            "case_id": case_id,
            "case_status": "ready",
            "case_hash": f"hash-{index}",
            "chart_sha256": hashlib.sha256(content).hexdigest(),
            "sidecar": {"feature": index},
        })
    (bundle / "cases.jsonl").write_text(
        "".join(json.dumps(case) + "\n" for case in cases))
    schema = {
        "review_id": "generic-review",
        "title": "Generic review",
        "description": "A test queue",
        "fields": [
            {"name": "decision", "label": "Decision", "type": "choice",
             "required": True, "options": ["take", "skip"]},
            {"name": "confidence", "label": "Confidence", "type": "scale",
             "required": True, "min": 0, "max": 1},
            {"name": "notes", "label": "Notes", "type": "text",
             "required": True, "max_length": 100},
        ],
    }
    manifest = {
        "outcome_accessed": False,
        "ready_cases": 2,
        "case_set_hash": "frozen-cases",
        "annotation_prompt_hash": "frozen-prompt",
        "annotation_columns": COLUMNS,
        "review_schema": schema,
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    pd.DataFrame(columns=COLUMNS).to_csv(bundle / "annotations.csv", index=False)
    monkeypatch.setattr(setup_review, "REVIEW_ROOT", root)
    return bundle


def values(decision="take"):
    return {"decision": decision, "confidence": 0.7, "notes": "visible facts"}


def test_generic_review_queue_drafts_resume_and_finalize(tmp_path, monkeypatch):
    bundle = make_bundle(tmp_path, monkeypatch)

    listed = setup_review.list_queues()["queues"]
    assert listed == [{
        "review_id": "generic-review", "title": "Generic review",
        "description": "A test queue", "case_count": 2, "human_passes": 0,
        "outcome_accessed": False,
    }]
    assert setup_review.queue("generic-review", "nikhil")["progress"] == {
        "completed": 0, "total": 2}

    updated = setup_review.save_draft("generic-review", {
        "annotator": "nikhil", "case_id": "CASE_0", "values": values()})
    assert updated["progress"]["completed"] == 1
    assert setup_review.case(
        "generic-review", "CASE_0", "nikhil")["draft"] == values()
    assert setup_review.case(
        "generic-review", "CASE_0", "nikhil")["judgements_locked"] is True

    with pytest.raises(setup_review.SetupReviewError, match="1/2") as blocked:
        setup_review.finalize("generic-review", {"annotator": "nikhil"})
    assert blocked.value.status == 409

    setup_review.save_draft("generic-review", {
        "annotator": "nikhil", "case_id": "CASE_1", "values": values("skip")})
    final = setup_review.finalize("generic-review", {"annotator": "nikhil"})
    assert final["finalized"] is True
    rows = pd.read_csv(bundle / "annotations.csv")
    assert len(rows) == 2
    assert set(rows["annotator_kind"]) == {"human"}
    assert set(rows["annotator"]) == {"nikhil"}
    revealed = setup_review.case("generic-review", "CASE_0", "nikhil")
    assert revealed["judgements_locked"] is False
    assert revealed["judgements"][0]["values"] == values()

    with pytest.raises(setup_review.SetupReviewError, match="immutable"):
        setup_review.save_draft("generic-review", {
            "annotator": "nikhil", "case_id": "CASE_0", "values": values("skip")})


def test_review_chart_is_hash_verified(tmp_path, monkeypatch):
    bundle = make_bundle(tmp_path, monkeypatch)
    expected = (bundle / "charts" / "CASE_0.png").read_bytes()
    assert setup_review.chart("generic-review", "CASE_0") == expected
    (bundle / "charts" / "CASE_0.png").write_bytes(b"changed")
    with pytest.raises(setup_review.SetupReviewError, match="hash mismatch"):
        setup_review.chart("generic-review", "CASE_0")


def test_review_validation_is_manifest_driven(tmp_path, monkeypatch):
    make_bundle(tmp_path, monkeypatch)
    with pytest.raises(setup_review.SetupReviewError, match="Decision is required"):
        setup_review.save_draft("generic-review", {
            "annotator": "nikhil", "case_id": "CASE_0",
            "values": {"confidence": 0.5, "notes": "facts"}})
    with pytest.raises(setup_review.SetupReviewError, match="above its maximum"):
        setup_review.save_draft("generic-review", {
            "annotator": "nikhil", "case_id": "CASE_0",
            "values": {"decision": "take", "confidence": 2, "notes": "facts"}})


def test_model_judgements_stay_hidden_until_human_pass_is_frozen(tmp_path, monkeypatch):
    bundle = make_bundle(tmp_path, monkeypatch)
    model_rows = [{
        "case_id": case_id, "annotator": "model_a", "annotator_kind": "model",
        "provider": "codex", "model": "frozen-model", "prompt_hash": "prompt",
        "decision": "take", "confidence": 0.8, "notes": "model facts",
    } for case_id in ("CASE_0", "CASE_1")]
    pd.DataFrame(model_rows, columns=COLUMNS).to_csv(
        bundle / "annotations.csv", index=False)

    blind = setup_review.case("generic-review", "CASE_0", "nikhil")
    assert blind["judgements_locked"] is True
    assert "judgements" not in blind

    for case_id in ("CASE_0", "CASE_1"):
        setup_review.save_draft("generic-review", {
            "annotator": "nikhil", "case_id": case_id, "values": values("skip")})
    setup_review.finalize("generic-review", {"annotator": "nikhil"})
    revealed = setup_review.case("generic-review", "CASE_0", "nikhil")
    assert [row["annotator_kind"] for row in revealed["judgements"]] == [
        "human", "model"]
    assert revealed["judgements"][1]["values"]["notes"] == "model facts"
