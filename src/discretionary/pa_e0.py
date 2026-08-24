"""Outcome-free candidate, annotation, and structural gates for H055."""
from __future__ import annotations

import hashlib
import json
import math
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..alpha_eval.guards import assert_no_forward_labels
from .pa_adapter import PriceActionAdapter, PriceActionCaseError


class PriceActionE0Error(RuntimeError):
    pass


ANNOTATION_COLUMNS = (
    "case_id", "annotator", "annotator_kind", "provider", "model", "prompt_hash",
    "zone_exists",
    "zone_center_atr_from_close", "interaction", "stance", "confidence",
    "notes",
)
INTERACTIONS = {"rejection", "break", "retest", "none"}
STANCES = {"long", "neutral", "avoid"}
ANNOTATION_PROMPT = """Inspect only the anonymised chart and numeric sidecar for each case.
Do not infer or guess the instrument or calendar date. Record whether a relevant
support/resistance zone exists, its centre as signed ATR distance from the last
close, the current interaction (rejection, break, retest, none), stance (long,
neutral, avoid), confidence, and a short observed-facts note. Do not use or ask
for future prices. Complete every ready case; do not omit awkward cases.
"""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def generate_candidates(
    features: pd.DataFrame,
    *,
    max_distance_atr: float = 0.50,
    cooldown_sessions: int = 1,
) -> pd.DataFrame:
    """Broad, causal proximity rule with chronological cooldown.

    The first proximity event consumes the symbol's holding-window slot even
    when its source bar is unusable.  That failure remains in the population;
    a later prettier chart cannot replace it.
    """
    assert_no_forward_labels(features, context="price-action E0 candidates")
    required = {
        "symbol_asof", "session", "bar_end", "available_at",
        "support_zone_kind", "zone_distance_atr", "support_touch",
        "bullish_rejection", "bullish_flip_retest", "quality_flags",
    }
    if missing := required - set(features.columns):
        raise PriceActionE0Error(f"feature frame missing: {sorted(missing)}")
    if max_distance_atr <= 0 or cooldown_sessions < 0:
        raise PriceActionE0Error("invalid proximity or cooldown")

    work = features.copy()
    work["session"] = pd.to_datetime(work["session"], errors="raise").dt.normalize()
    work["bar_end"] = pd.to_datetime(work["bar_end"], errors="raise")
    work["available_at"] = pd.to_datetime(work["available_at"], errors="raise")
    distance = pd.to_numeric(work["zone_distance_atr"], errors="coerce")
    proximity = (
        work["support_zone_kind"].astype(str).ne("")
        & (distance.abs().le(max_distance_atr) | work["support_touch"].fillna(False))
    )
    work = work.loc[proximity].sort_values(
        ["bar_end", "symbol_asof"], kind="stable").copy()
    if work.empty:
        return pd.DataFrame(columns=[
            "symbol", "date", "decision_at", "generator_score",
            "generator_reason", "candidate_type", "case_status",
        ])

    session_order = {
        value: index for index, value in enumerate(sorted(work["session"].unique()))
    }
    keep: list[int] = []
    last_slot: dict[str, int] = {}
    for index, row in work.iterrows():
        symbol = str(row["symbol_asof"])
        slot = session_order[row["session"]]
        if symbol in last_slot and slot <= last_slot[symbol] + cooldown_sessions:
            continue
        keep.append(index)
        last_slot[symbol] = slot
    work = work.loc[keep].copy()
    work["symbol"] = work["symbol_asof"].astype(str)
    work["date"] = work["session"]
    work["decision_at"] = work["available_at"]
    work["generator_score"] = -distance.loc[work.index].abs()
    work["candidate_type"] = np.select(
        [work["bullish_flip_retest"].fillna(False),
         work["bullish_rejection"].fillna(False)],
        ["flip_retest", "bullish_rejection"], default="support_proximity")
    bad = work["quality_flags"].astype(str).str.contains(
        "invalid_price|invalid_ohlc|negative_volume|corporate_action", regex=True)
    work["case_status"] = np.where(bad, "source_failure", "pending")
    work["generator_reason"] = (
        "first causal support proximity within " + str(max_distance_atr)
        + " ATR after the registered cooldown")
    columns = [
        "symbol", "date", "decision_at", "generator_score",
        "generator_reason", "candidate_type", "case_status", "symbol_asof",
        "session", "bar_end", "available_at", "support_zone_kind",
        "support_zone_lower", "support_zone_upper", "support_zone_center",
        "atr_20", "zone_distance_atr", "quality_flags", "partition",
    ]
    return work[[column for column in columns if column in work.columns]].reset_index(drop=True)


def _stratified_sample(candidates: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    if n < 1:
        raise PriceActionE0Error("annotation case budget must be positive")
    if len(candidates) <= n:
        return candidates.copy().reset_index(drop=True)
    rng = np.random.default_rng(seed)
    groups = []
    for _, group in candidates.groupby("candidate_type", sort=True):
        indices = group.index.to_numpy(copy=True)
        rng.shuffle(indices)
        groups.append(indices)
    picked: list[int] = []
    offset = 0
    while len(picked) < n and groups:
        progressed = False
        for group in groups:
            if offset < len(group):
                picked.append(int(group[offset]))
                progressed = True
                if len(picked) == n:
                    break
        if not progressed:
            break
        offset += 1
    return candidates.loc[picked].sort_values(
        ["decision_at", "symbol"], kind="stable").reset_index(drop=True)


def freeze_annotation_bundle(
    candidates: pd.DataFrame,
    feature_bars: pd.DataFrame,
    output: Path,
    *,
    n_cases: int = 60,
    seed: int = 20260824,
    adapter: PriceActionAdapter | None = None,
) -> dict[str, Any]:
    """Freeze anonymised chart/table cases and an empty annotation template."""
    if output.exists():
        raise PriceActionE0Error(f"annotation bundle already exists: {output}")
    output.mkdir(parents=True, exist_ok=False)
    charts = output / "charts"
    charts.mkdir()
    selected = _stratified_sample(candidates, n_cases, seed)
    renderer = adapter or PriceActionAdapter()
    records: list[dict[str, Any]] = []
    failures = 0
    for index, row in selected.iterrows():
        case_id = f"PAE0_C{index:04d}"
        history = feature_bars[
            (feature_bars["symbol_asof"].astype(str) == str(row["symbol"]))
            & (pd.to_datetime(feature_bars["available_at"]) <= pd.Timestamp(row["decision_at"]))
        ]
        record = {
            "case_id": case_id,
            "candidate_type": str(row["candidate_type"]),
            "case_status": str(row["case_status"]),
            "decision_at_private": pd.Timestamp(row["decision_at"]).isoformat(),
            "symbol_private": str(row["symbol"]),
        }
        try:
            rendered = renderer.render_case(
                history, decision_at=row["decision_at"], anonymised=True)
            chart_path = charts / f"{case_id}.png"
            chart_path.write_bytes(rendered["chart_bytes"])
            record.update({
                "case_status": "ready",
                "case_hash": rendered["case_hash"],
                "chart_sha256": hashlib.sha256(rendered["chart_bytes"]).hexdigest(),
                "sidecar": rendered["sidecar"],
            })
        except PriceActionCaseError as exc:
            failures += 1
            record.update({"case_status": "source_failure", "error": str(exc)})
        records.append(record)

    (output / "cases_private.jsonl").write_text(
        "".join(_canonical(record) + "\n" for record in records))
    public = [
        {key: value for key, value in record.items()
         if key not in ("decision_at_private", "symbol_private")}
        for record in records
    ]
    (output / "cases.jsonl").write_text(
        "".join(_canonical(record) + "\n" for record in public))
    ready = [record for record in records if record["case_status"] == "ready"]
    pd.DataFrame(columns=ANNOTATION_COLUMNS).to_csv(
        output / "annotations.csv", index=False)
    (output / "annotation_prompt.txt").write_text(ANNOTATION_PROMPT)
    prompt_hash = hashlib.sha256(ANNOTATION_PROMPT.encode()).hexdigest()
    manifest = {
        "schema_version": "pa_e0_annotations.v1",
        "outcome_accessed": False,
        "seed": seed,
        "requested_cases": n_cases,
        "selected_cases": len(records),
        "ready_cases": len(ready),
        "source_failures": failures,
        "adapter_schema_hash": renderer.schema_hash,
        "case_set_hash": hashlib.sha256(
            "".join(record.get("case_hash", "FAILED") for record in records).encode()
        ).hexdigest(),
        "annotation_columns": list(ANNOTATION_COLUMNS),
        "annotation_prompt_hash": prompt_hash,
        "acceptance_bar": {"min_class_kappa": 0.40,
                           "max_median_zone_centre_disagreement_atr": 0.50},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    raise PriceActionE0Error(f"invalid zone_exists value: {value!r}")


def _kappa(left: pd.Series, right: pd.Series) -> float | None:
    if len(left) == 0:
        return None
    labels = sorted(set(left.astype(str)) | set(right.astype(str)))
    po = float((left.astype(str).to_numpy() == right.astype(str).to_numpy()).mean())
    pe = sum(float(left.astype(str).eq(label).mean())
             * float(right.astype(str).eq(label).mean()) for label in labels)
    return None if pe >= 1.0 else (po - pe) / (1.0 - pe)


def annotation_agreement(
    annotations: pd.DataFrame,
    *,
    expected_case_ids: set[str] | None = None,
    expected_prompt_hash: str | None = None,
) -> dict[str, Any]:
    missing = set(ANNOTATION_COLUMNS) - set(annotations.columns)
    if missing:
        raise PriceActionE0Error(f"annotations missing: {sorted(missing)}")
    data = annotations.dropna(subset=["case_id", "annotator", "annotator_kind"]).copy()
    if data.duplicated(["case_id", "annotator"]).any():
        raise PriceActionE0Error("an annotator may label a case only once")
    kinds = set(data["annotator_kind"].astype(str).str.lower())
    humans = data.loc[data["annotator_kind"].astype(str).str.lower().eq("human"),
                      "annotator"].nunique()
    model_rows = data[
        data["annotator_kind"].astype(str).str.lower().eq("model")].copy()
    model_rows["model_identity"] = (
        model_rows["provider"].astype(str) + "|" + model_rows["model"].astype(str)
        + "|" + model_rows["prompt_hash"].astype(str))
    models = model_rows["model_identity"].nunique()
    annotator_sets = [
        set(group["case_id"].astype(str))
        for _, group in data.groupby("annotator", sort=True)
    ]
    common_full_set = bool(annotator_sets) and all(
        case_set == annotator_sets[0] for case_set in annotator_sets)
    if expected_case_ids is not None:
        common_full_set = common_full_set and annotator_sets[0] == expected_case_ids
    model_metadata_complete = not model_rows.empty and (
        model_rows[["provider", "model", "prompt_hash"]].astype(str)
        .apply(lambda column: column.str.strip().ne("")).all().all())
    if expected_prompt_hash is not None:
        model_metadata_complete = model_metadata_complete and set(
            model_rows["prompt_hash"].astype(str)) == {expected_prompt_hash}
    complete_design = (
        humans >= 1 and models >= 2 and common_full_set and model_metadata_complete)
    data["zone_exists"] = data["zone_exists"].map(_bool)
    if not set(data["interaction"].astype(str)).issubset(INTERACTIONS):
        raise PriceActionE0Error(f"interaction must be one of {sorted(INTERACTIONS)}")
    if not set(data["stance"].astype(str)).issubset(STANCES):
        raise PriceActionE0Error(f"stance must be one of {sorted(STANCES)}")
    data["class_label"] = (
        data["zone_exists"].astype(str) + "|" + data["interaction"].astype(str)
        + "|" + data["stance"].astype(str))
    kappas: list[float] = []
    centre_differences: list[float] = []
    for left_name, right_name in combinations(sorted(data["annotator"].unique()), 2):
        left = data[data["annotator"].eq(left_name)]
        right = data[data["annotator"].eq(right_name)]
        paired = left.merge(right, on="case_id", suffixes=("_left", "_right"))
        value = _kappa(paired["class_label_left"], paired["class_label_right"])
        if value is not None:
            kappas.append(value)
        centres = paired[
            paired["zone_exists_left"] & paired["zone_exists_right"]].copy()
        left_c = pd.to_numeric(centres["zone_center_atr_from_close_left"], errors="coerce")
        right_c = pd.to_numeric(centres["zone_center_atr_from_close_right"], errors="coerce")
        centre_differences.extend((left_c - right_c).abs().dropna().tolist())
    median_kappa = float(np.median(kappas)) if kappas else None
    median_centre = float(np.median(centre_differences)) if centre_differences else None
    passed = bool(
        complete_design and median_kappa is not None and median_kappa >= 0.40
        and median_centre is not None and median_centre <= 0.50)
    return {
        "complete_design": complete_design,
        "annotator_kinds": sorted(kinds),
        "human_annotators": int(humans),
        "model_annotators": int(models),
        "common_complete_case_set": common_full_set,
        "annotated_cases": int(data["case_id"].nunique()),
        "pairwise_kappa_median": median_kappa,
        "zone_centre_disagreement_atr_median": median_centre,
        "passed": passed,
    }


def normal_approx_mde_bps(
    independent_blocks: int,
    *,
    assumed_block_sigma_bps: float = 400.0,
) -> float | None:
    """Transparent two-sided 5% / 80%-power design approximation."""
    if independent_blocks < 1:
        return None
    return (1.959964 + 0.841621) * assumed_block_sigma_bps / math.sqrt(
        independent_blocks)


def structural_report(
    features: pd.DataFrame,
    candidates: pd.DataFrame,
    *,
    acquisition_report: dict[str, Any],
    identity_report: dict[str, Any],
    annotations: pd.DataFrame | None = None,
    annotation_case_ids: set[str] | None = None,
    annotation_prompt_hash: str | None = None,
    intended_position_inr: float = 100_000.0,
    useful_effect_bps: float = 80.0,
) -> dict[str, Any]:
    """E0 report. It cannot read or accept forward-return fields."""
    assert_no_forward_labels(features, context="price-action E0 report")
    sessions = int(candidates["date"].nunique()) if not candidates.empty else 0
    mde = normal_approx_mde_bps(sessions)
    agreement = None if annotations is None or annotations.empty \
        else annotation_agreement(
            annotations, expected_case_ids=annotation_case_ids,
            expected_prompt_hash=annotation_prompt_hash)
    coverage_pass = bool(identity_report.get("identity_coverage_passed"))
    source_pass = (
        acquisition_report.get("pending", 1) == 0
        and acquisition_report.get("bad", 1) == 0
        and acquisition_report.get("session_coverage_pct", 0.0) >= 95.0)
    power_pass = mde is not None and mde <= useful_effect_bps
    annotation_pass = agreement is not None and agreement.get("passed", False)
    quality = features.get("quality_flags", pd.Series("", index=features.index)).astype(str)
    report = {
        "stage": "PA7_E0",
        "status": "passed" if all((coverage_pass, source_pass, power_pass,
                                     annotation_pass)) else "blocked",
        "outcome_accessed": False,
        "gates": {
            "identity_coverage": coverage_pass,
            "source_complete": source_pass,
            "representation_agreement": annotation_pass,
            "useful_effect_power": power_pass,
        },
        "source": acquisition_report,
        "bars": {
            "rows": int(len(features)),
            "sessions": int(features["session"].nunique()),
            "symbols": int(features["symbol_asof"].nunique()),
            "quality_flagged_rows": int(quality.ne("").sum()),
            "corporate_action_rows": int(quality.str.contains("corporate_action").sum()),
        },
        "representation": {
            "known_support_rows": int(features["support_zone_kind"].astype(str).ne("").sum()),
            "touch_rows": int(features["support_touch"].fillna(False).sum()),
            "bullish_rejections": int(features["bullish_rejection"].fillna(False).sum()),
            "flip_retests": int(features["bullish_flip_retest"].fillna(False).sum()),
            "zone_width_atr_median": float(np.nanmedian(
                (features["support_zone_upper"] - features["support_zone_lower"])
                / features["atr_20"])) if features["support_zone_center"].notna().any()
                else None,
        },
        "candidates": {
            "rows": int(len(candidates)), "sessions": sessions,
            "symbols": int(candidates["symbol"].nunique()) if not candidates.empty else 0,
            "source_failures": int(candidates["case_status"].eq("source_failure").sum())
            if not candidates.empty else 0,
            "per_session": candidates.groupby("date").size().describe().to_dict()
            if not candidates.empty else {},
        },
        "power": {
            "independent_blocks": sessions,
            "assumed_block_sigma_bps": 400.0,
            "mde_bps_5pct_two_sided_80pct_power": mde,
            "useful_effect_bps": useful_effect_bps,
        },
        "capacity": {
            "intended_position_inr": intended_position_inr,
            "max_fraction_of_lagged_median_traded_value": 0.02,
            "minimum_required_lagged_median_traded_value_inr": intended_position_inr / 0.02,
            "universe_floor_inr": 30_000_000.0,
            "passed_by_construction": intended_position_inr / 0.02 <= 30_000_000.0,
            "round_trip_cost_floor_bps": 40.0,
        },
        "annotations": agreement,
    }
    return report


__all__ = [
    "ANNOTATION_COLUMNS", "PriceActionE0Error", "annotation_agreement",
    "freeze_annotation_bundle", "generate_candidates", "normal_approx_mde_bps",
    "structural_report",
]
