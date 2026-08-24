import json

import pandas as pd

from src.discretionary import pa_e0
from src.discretionary.pa_annotations import run_model_pass
from src.runner.agent import AgentResult


def _bundle(tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "charts").mkdir(parents=True)
    prompt_hash = __import__("hashlib").sha256(
        pa_e0.ANNOTATION_PROMPT.encode()).hexdigest()
    (bundle / "annotation_prompt.txt").write_text(pa_e0.ANNOTATION_PROMPT)
    cases = []
    for index in range(2):
        case_id = f"C{index}"
        chart = bundle / "charts" / f"{case_id}.png"
        chart.write_bytes(b"png" + bytes([index]))
        cases.append({
            "case_id": case_id, "case_status": "ready",
            "chart_sha256": __import__("hashlib").sha256(
                chart.read_bytes()).hexdigest(),
            "sidecar": {"last_close_rebased": 100.0, "atr_20_rebased": 1.0},
        })
    (bundle / "cases.jsonl").write_text(
        "".join(json.dumps(case) + "\n" for case in cases))
    (bundle / "manifest.json").write_text(json.dumps({
        "outcome_accessed": False, "ready_cases": 2,
        "annotation_prompt_hash": prompt_hash, "case_set_hash": "set",
    }))
    pd.DataFrame(columns=pa_e0.ANNOTATION_COLUMNS).to_csv(
        bundle / "annotations.csv", index=False)
    return bundle


def test_model_pass_is_sealed_resumable_and_published_only_when_complete(tmp_path):
    bundle = _bundle(tmp_path)
    seen = []

    def fake_agent(prompt, cwd, **kwargs):
        seen.append((list(cwd.iterdir()), kwargs))
        return AgentResult(
            ok=True, text=json.dumps({
                "zone_exists": True, "zone_center_atr_from_close": -0.2,
                "interaction": "retest", "stance": "long",
                "confidence": 0.7, "notes": "Repeated reactions below close.",
            }), returncode=0, duration_s=0.1)

    partial = run_model_pass(
        bundle, annotator="codex_luna_v1", provider="codex", model="luna",
        max_cases=1, agent_fn=fake_agent)
    assert partial["status"] == "partial" and partial["remaining"] == 1
    assert pd.read_csv(bundle / "annotations.csv").empty

    complete = run_model_pass(
        bundle, annotator="codex_luna_v1", provider="codex", model="luna",
        agent_fn=fake_agent)
    assert complete["status"] == "complete" and complete["failed_calls"] == 0
    rows = pd.read_csv(bundle / "annotations.csv")
    assert len(rows) == 2 and rows["annotator"].nunique() == 1
    assert all(contents == [] for contents, _ in seen)
    assert all(kwargs["allowed_tools"] == () for _, kwargs in seen)
    assert all(kwargs["sandbox"] == "read-only" for _, kwargs in seen)
    assert all(len(kwargs["image_paths"]) == 1 for _, kwargs in seen)


def test_malformed_model_reply_is_recorded_not_dropped(tmp_path):
    bundle = _bundle(tmp_path)

    def malformed_agent(prompt, cwd, **kwargs):
        return AgentResult(
            ok=True, text=json.dumps({
                "zone_exists": "boolean", "zone_center_atr_from_close": None,
                "interaction": "none", "stance": "neutral",
                "confidence": 0.0, "notes": "malformed",
            }), returncode=0, duration_s=0.1)

    result = run_model_pass(
        bundle, annotator="malformed", provider="codex", model="luna",
        agent_fn=malformed_agent)
    assert result["status"] == "complete" and result["failed_calls"] == 2
    rows = pd.read_csv(bundle / "annotations.csv")
    assert rows["notes"].str.startswith("CALL_FAILED:").all()
