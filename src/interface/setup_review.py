"""Generic, outcome-sealed setup-review queues for the primary web app.

A queue is any frozen case bundle beneath the research store whose manifest
contains ``review_schema``.  The interface sees only ``cases.jsonl`` and never
the private identity file. Human work is checkpointed as a draft and appended
to the frozen annotation table only as one complete pass over the case set.
"""
from __future__ import annotations

import csv
import fcntl
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from ..core import config


REVIEW_ROOT = config.METADATA_DIR / "research_store"
ANNOTATOR_PATTERN = re.compile(r"[A-Za-z0-9_.-]+")


class SetupReviewError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    try:
        frame.to_csv(name, index=False)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def _locked(bundle: Path) -> Iterator[None]:
    path = bundle / ".review.lock"
    with path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _safe_annotator(value: str) -> str:
    value = str(value or "").strip()
    if not value or not ANNOTATOR_PATTERN.fullmatch(value):
        raise SetupReviewError(
            "Reviewer ID may contain only letters, numbers, dot, dash and underscore.")
    return value


def _bundles() -> dict[str, Path]:
    found: dict[str, Path] = {}
    if not REVIEW_ROOT.exists():
        return found
    for manifest_path in REVIEW_ROOT.rglob("manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        schema = manifest.get("review_schema")
        if not isinstance(schema, dict) or not schema.get("review_id"):
            continue
        bundle = manifest_path.parent
        if not (bundle / "cases.jsonl").is_file():
            continue
        review_id = str(schema["review_id"])
        if review_id in found:
            raise SetupReviewError(f"duplicate review queue ID: {review_id}", 500)
        found[review_id] = bundle
    return found


def _bundle(review_id: str) -> Path:
    try:
        return _bundles()[review_id]
    except KeyError as exc:
        raise SetupReviewError(f"unknown setup-review queue: {review_id}", 404) from exc


def _load(review_id: str) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    bundle = _bundle(review_id)
    manifest = json.loads((bundle / "manifest.json").read_text())
    if manifest.get("outcome_accessed") is not False:
        raise SetupReviewError("review queue is not outcome-sealed", 409)
    cases = [json.loads(line) for line in (bundle / "cases.jsonl").read_text().splitlines()
             if line.strip()]
    ready = [case for case in cases if case.get("case_status") == "ready"]
    if len(ready) != int(manifest.get("ready_cases", -1)):
        raise SetupReviewError("review queue case count does not match manifest", 500)
    return bundle, manifest, ready


def _draft_path(bundle: Path, annotator: str) -> Path:
    return bundle / "human_drafts" / f"{annotator}.json"


def _draft(bundle: Path, manifest: dict[str, Any], annotator: str) -> dict[str, Any]:
    path = _draft_path(bundle, annotator)
    identity = {
        "schema_version": "setup_review.draft.v1",
        "review_id": manifest["review_schema"]["review_id"],
        "annotator": annotator,
        "case_set_hash": manifest["case_set_hash"],
        "prompt_hash": manifest["annotation_prompt_hash"],
        "annotations": {},
    }
    if not path.exists():
        return identity
    value = json.loads(path.read_text())
    for key in identity:
        if key != "annotations" and value.get(key) != identity[key]:
            raise SetupReviewError("saved draft belongs to a different frozen queue", 409)
    if not isinstance(value.get("annotations"), dict):
        raise SetupReviewError("saved review draft is malformed", 500)
    return value


def _annotations(bundle: Path) -> pd.DataFrame:
    path = bundle / "annotations.csv"
    if not path.exists():
        return pd.DataFrame()
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        return pd.DataFrame.from_records(
            list(reader), columns=list(reader.fieldnames or []))


def _is_finalized(bundle: Path, annotator: str) -> bool:
    frame = _annotations(bundle)
    if frame.empty:
        return False
    if not {"annotator", "annotator_kind"}.issubset(frame.columns):
        raise SetupReviewError("annotation table is missing identity columns", 500)
    return bool((
        frame["annotator"].astype(str).eq(annotator)
        & frame["annotator_kind"].astype(str).eq("human")
    ).any())


def _field_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields = manifest["review_schema"].get("fields", [])
    if not isinstance(fields, list) or not fields:
        raise SetupReviewError("review queue has no field schema", 500)
    result = {str(field.get("name")): field for field in fields
              if isinstance(field, dict) and field.get("name")}
    if len(result) != len(fields):
        raise SetupReviewError("review field names are missing or duplicated", 500)
    return result


def _validate_values(manifest: dict[str, Any], values: Any) -> dict[str, Any]:
    if not isinstance(values, dict):
        raise SetupReviewError("annotation values must be an object")
    fields = _field_map(manifest)
    if extra := set(values) - set(fields):
        raise SetupReviewError(f"unknown annotation fields: {sorted(extra)}")
    clean: dict[str, Any] = {}
    for name, field in fields.items():
        value = values.get(name)
        field_type = str(field.get("type"))
        required = bool(field.get("required", False))
        required_when = field.get("required_when")
        if isinstance(required_when, dict):
            required = all(values.get(k) == v for k, v in required_when.items())
        if value is None or value == "":
            if required:
                raise SetupReviewError(f"{field.get('label', name)} is required")
            clean[name] = None
            continue
        if field_type == "boolean":
            if not isinstance(value, bool):
                raise SetupReviewError(f"{field.get('label', name)} must be yes or no")
            clean[name] = value
        elif field_type in ("number", "scale"):
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise SetupReviewError(f"{field.get('label', name)} must be numeric") from exc
            minimum, maximum = field.get("min"), field.get("max")
            if minimum is not None and number < float(minimum):
                raise SetupReviewError(f"{field.get('label', name)} is below its minimum")
            if maximum is not None and number > float(maximum):
                raise SetupReviewError(f"{field.get('label', name)} is above its maximum")
            clean[name] = number
        elif field_type == "choice":
            options = [str(option["value"] if isinstance(option, dict) else option)
                       for option in field.get("options", [])]
            if str(value) not in options:
                raise SetupReviewError(
                    f"{field.get('label', name)} must be one of {options}")
            clean[name] = str(value)
        elif field_type == "text":
            text = str(value).strip()
            max_length = int(field.get("max_length", 1000))
            if len(text) > max_length:
                raise SetupReviewError(
                    f"{field.get('label', name)} exceeds {max_length} characters")
            clean[name] = text
        else:
            raise SetupReviewError(f"unsupported review field type: {field_type}", 500)
    _check_invariants(manifest, clean)
    return clean


def _check_invariants(manifest: dict[str, Any], values: dict[str, Any]) -> None:
    """Enforce declared cross-field rules before a value is ever stored.

    A schema can say that three prices must be strictly ordered but not which
    way, which is how a long and a short are the same rule. H058 needs exactly
    that: a stop below the entry means long and above it means short, so the
    only illegal arrangement is an entry that is not between the other two.
    Checking it in the browser is what makes the reviewer fast; checking it
    here is what makes the frozen table trustworthy.
    """
    for invariant in manifest["review_schema"].get("invariants", []) or []:
        when = invariant.get("when") or {}
        if any(values.get(key) != value for key, value in when.items()):
            continue
        names = list(invariant.get("fields", []))
        ordered = [values.get(name) for name in names]
        if any(value is None for value in ordered):
            continue  # required/required_when already decides what may be blank
        rule = str(invariant.get("rule"))
        if rule != "strictly_ordered":
            raise SetupReviewError(f"unsupported review invariant: {rule}", 500)
        rising = all(a < b for a, b in zip(ordered, ordered[1:]))
        falling = all(a > b for a, b in zip(ordered, ordered[1:]))
        if rising or (falling and invariant.get("either_direction")):
            continue
        raise SetupReviewError(str(invariant.get("message")
                                   or f"{names} must be strictly ordered"))


def _recency_key(manifest: dict[str, Any], review_id: str) -> tuple[str, str]:
    """Sort key placing the newest queue first.

    `created` is stamped at freeze time, but the bundles frozen before that
    field existed do not carry one. Those fall back to the review id, which for
    this project's H0xx naming happens to be chronological -- a coincidence, so
    it is the fallback rather than the rule, and an empty `created` sorts below
    any real one under the descending order used here.
    """
    return (str(manifest.get("created", "")), review_id)


def list_queues() -> dict[str, Any]:
    queues = []
    order = sorted(
        _bundles(),
        key=lambda rid: _recency_key(_load(rid)[1], rid),
        reverse=True)
    for review_id in order:
        _, manifest, cases = _load(review_id)
        schema = manifest["review_schema"]
        annotations = _annotations(_bundle(review_id))
        humans = 0
        if not annotations.empty:
            if not {"annotator", "annotator_kind"}.issubset(annotations.columns):
                raise SetupReviewError("annotation table is missing identity columns", 500)
            humans = int(annotations.loc[
                annotations["annotator_kind"].astype(str).eq("human"),
                "annotator"].nunique())
        queues.append({
            "review_id": review_id,
            "title": schema.get("title", review_id),
            "description": schema.get("description", ""),
            "case_count": len(cases),
            "human_passes": humans,
            "outcome_accessed": False,
        })
    return {"queues": queues}


def queue(review_id: str, annotator: str) -> dict[str, Any]:
    annotator = _safe_annotator(annotator)
    bundle, manifest, cases = _load(review_id)
    draft = _draft(bundle, manifest, annotator)
    saved = draft["annotations"]
    finalized = _is_finalized(bundle, annotator)
    return {
        "review_id": review_id,
        "schema": manifest["review_schema"],
        "case_set_hash": manifest["case_set_hash"],
        "prompt_hash": manifest["annotation_prompt_hash"],
        "outcome_accessed": False,
        "annotator": annotator,
        "finalized": finalized,
        "progress": {"completed": len(saved), "total": len(cases)},
        "cases": [{
            "case_id": case["case_id"],
            "case_status": case["case_status"],
            "reviewed": case["case_id"] in saved,
        } for case in cases],
    }


def case(review_id: str, case_id: str, annotator: str) -> dict[str, Any]:
    annotator = _safe_annotator(annotator)
    bundle, manifest, cases = _load(review_id)
    selected = next((case for case in cases if case["case_id"] == case_id), None)
    if selected is None:
        raise SetupReviewError(f"unknown case: {case_id}", 404)
    draft = _draft(bundle, manifest, annotator)
    finalized = _is_finalized(bundle, annotator)
    payload = {
        "review_id": review_id,
        "case_id": case_id,
        "case_hash": selected.get("case_hash"),
        "sidecar": selected.get("sidecar", {}),
        "media": {
            "kind": "image",
            "url": f"/api/setup-reviews/{review_id}/charts/{case_id}.png",
            "sha256": selected.get("chart_sha256"),
        },
        "draft": draft["annotations"].get(case_id, {}).get("values"),
        "finalized": finalized,
        "judgements_locked": not finalized,
        "outcome_accessed": False,
    }
    if finalized:
        # A bundle may carry ground truth for its own cases -- which line was
        # real, what happened next. It is served only here, after the reviewer
        # has frozen a complete pass, for the same reason model answers are:
        # a reviewer who can see the answer is not producing data.
        reveal = selected.get("reveal")
        if isinstance(reveal, dict):
            payload["reveal"] = reveal
        frame = _annotations(bundle)
        visible = frame[
            frame["case_id"].astype(str).eq(case_id)
            & (
                frame["annotator"].astype(str).eq(annotator)
                | frame["annotator_kind"].astype(str).eq("model")
            )
        ].copy()
        visible["_review_order"] = visible["annotator_kind"].astype(str).ne("human")
        visible = visible.sort_values(["_review_order", "annotator"], kind="stable")
        fields = _field_map(manifest)
        payload["judgements"] = [{
            "annotator": str(row["annotator"]),
            "annotator_kind": str(row["annotator_kind"]),
            "provider": _wire_text(row.get("provider")),
            "model": _wire_text(row.get("model")),
            "values": {
                name: _wire_field_value(field, row.get(name))
                for name, field in fields.items()
            },
        } for _, row in visible.iterrows()]
    return payload


def _wire_value(value: Any) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()) or (
            not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    return value.item() if hasattr(value, "item") else value


def _wire_text(value: Any) -> str:
    clean = _wire_value(value)
    return "" if clean is None else str(clean)


def _wire_field_value(field: dict[str, Any], value: Any) -> Any:
    clean = _wire_value(value)
    if clean is None:
        return None
    field_type = str(field.get("type"))
    if field_type == "boolean":
        text = str(clean).strip().lower()
        return text in {"true", "1", "yes"}
    if field_type in {"number", "scale"}:
        return float(clean)
    return str(clean)


def chart(review_id: str, case_id: str) -> bytes:
    bundle, _, cases = _load(review_id)
    selected = next((case for case in cases if case["case_id"] == case_id), None)
    if selected is None:
        raise SetupReviewError(f"unknown case: {case_id}", 404)
    path = bundle / "charts" / f"{case_id}.png"
    if not path.is_file():
        raise SetupReviewError("case image is missing", 500)
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != selected.get("chart_sha256"):
        raise SetupReviewError("case image hash mismatch", 500)
    return content


def save_draft(review_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    annotator = _safe_annotator(payload.get("annotator", ""))
    case_id = str(payload.get("case_id") or "")
    bundle, manifest, cases = _load(review_id)
    if case_id not in {case["case_id"] for case in cases}:
        raise SetupReviewError(f"unknown case: {case_id}", 404)
    values = _validate_values(manifest, payload.get("values"))
    with _locked(bundle):
        if _is_finalized(bundle, annotator):
            raise SetupReviewError("this human pass is finalized and immutable", 409)
        draft = _draft(bundle, manifest, annotator)
        draft["annotations"][case_id] = {
            "values": values,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_json(_draft_path(bundle, annotator), draft)
    return queue(review_id, annotator)


def finalize(review_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    annotator = _safe_annotator(payload.get("annotator", ""))
    bundle, manifest, cases = _load(review_id)
    with _locked(bundle):
        if _is_finalized(bundle, annotator):
            raise SetupReviewError("this human pass is already finalized", 409)
        draft = _draft(bundle, manifest, annotator)
        expected = {case["case_id"] for case in cases}
        observed = set(draft["annotations"])
        if observed != expected:
            raise SetupReviewError(
                f"complete every case before finalizing: {len(observed)}/{len(expected)}", 409)
        columns = list(manifest.get("annotation_columns", []))
        rows = []
        for case_item in cases:
            values = _validate_values(
                manifest, draft["annotations"][case_item["case_id"]]["values"])
            row = {
                "case_id": case_item["case_id"],
                "annotator": annotator,
                "annotator_kind": "human",
                "provider": "",
                "model": "",
                # Stamp the prompt this pass actually answered. Test identity is
                # (prompt hash, model, case-set hash), and a human pass left
                # blank cannot be checked against the bundle it came from --
                # editing the instructions and re-running would look identical.
                "prompt_hash": str(manifest.get("annotation_prompt_hash", "")),
                **values,
            }
            if set(row) != set(columns):
                raise SetupReviewError(
                    "review fields do not match the frozen annotation columns", 500)
            rows.append(row)
        path = bundle / "annotations.csv"
        existing = _annotations(bundle)
        combined = pd.concat(
            [existing, pd.DataFrame(rows, columns=columns)], ignore_index=True)
        _atomic_csv(path, combined)
        completion = {
            "review_id": review_id,
            "annotator": annotator,
            "annotator_kind": "human",
            "case_set_hash": manifest["case_set_hash"],
            "cases": len(rows),
            "finalized_at": datetime.now(timezone.utc).isoformat(),
            "outcome_accessed": False,
        }
        _atomic_json(bundle / "human_drafts" / f"{annotator}.finalized.json",
                     completion)
    return {**queue(review_id, annotator), "completion": completion}


__all__ = [
    "SetupReviewError", "case", "chart", "finalize", "list_queues", "queue",
    "save_draft",
]
