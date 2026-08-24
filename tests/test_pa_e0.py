import pandas as pd

from src.discretionary import pa_e0
from src.research_data.pipelines.causal_zones import build_zone_state_machine


def feature_bars():
    rows = []
    for day, base in (("2026-01-02", 10.0), ("2026-01-05", 10.2),
                      ("2026-01-06", 10.1)):
        for index in range(12):
            close = base + [0, -.2, -.4, -.1, .1, .3, .15, .05, .2, .4, .25, .1][index]
            start = pd.Timestamp(day) + pd.Timedelta(hours=9, minutes=15 + 5 * index)
            rows.append({
                "symbol_asof": "TEST", "session": pd.Timestamp(day),
                "bar_start": start, "bar_end": start + pd.Timedelta(minutes=5),
                "available_at": start + pd.Timedelta(minutes=5),
                "open_raw": close - .03, "high_raw": close + .12,
                "low_raw": close - .12, "close_raw": close,
                "volume_raw": 100 + index, "quality_flags": "",
            })
    return build_zone_state_machine(pd.DataFrame(rows))


def test_e0_candidates_are_causal_and_cooldown_is_chronological():
    features = feature_bars()
    candidates = pa_e0.generate_candidates(
        features, max_distance_atr=2.0, cooldown_sessions=1)
    assert not candidates.empty
    assert candidates["decision_at"].equals(candidates["available_at"])
    dates = candidates["date"].sort_values().tolist()
    assert all((right - left).days >= 2 for left, right in zip(dates, dates[1:]))


def test_annotation_bundle_is_anonymised_and_future_stable(tmp_path):
    features = feature_bars()
    candidates = pa_e0.generate_candidates(
        features, max_distance_atr=2.0, cooldown_sessions=0)
    manifest = pa_e0.freeze_annotation_bundle(
        candidates, features, tmp_path / "bundle", n_cases=2, seed=1)
    public = (tmp_path / "bundle" / "cases.jsonl").read_text()
    assert manifest["ready_cases"] > 0
    assert "TEST" not in public
    assert "2026-01" not in public


def test_annotation_gate_requires_human_and_two_models_and_meets_bar():
    rows = []
    cases = (
        ("C1", 0.1, True, "retest", "long"),
        ("C2", float("nan"), False, "none", "neutral"),
        ("C3", 0.0, True, "rejection", "long"),
    )
    for case_id, centre, exists, interaction, stance in cases:
        for annotator, kind, offset in (
            ("human", "human", 0.0), ("model_a", "model", 0.05),
            ("model_b", "model", -0.05)):
            rows.append({
                "case_id": case_id, "annotator": annotator,
                "annotator_kind": kind, "zone_exists": exists,
                "provider": "" if kind == "human" else annotator,
                "model": "" if kind == "human" else "frozen_model",
                "prompt_hash": "" if kind == "human" else "frozen_prompt",
                "zone_center_atr_from_close": centre + offset,
                "interaction": interaction, "stance": stance,
                "confidence": 0.8, "notes": "",
            })
    report = pa_e0.annotation_agreement(
        pd.DataFrame(rows), expected_case_ids={"C1", "C2", "C3"},
        expected_prompt_hash="frozen_prompt")
    assert report["complete_design"]
    assert report["passed"]


def test_mde_uses_independent_blocks_not_bar_count():
    assert pa_e0.normal_approx_mde_bps(400) < 80
    assert pa_e0.normal_approx_mde_bps(25) > 80
