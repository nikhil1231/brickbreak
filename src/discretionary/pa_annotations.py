"""Sealed, resumable model annotation passes for the H055 E0 fidelity set."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from ..runner import agent
from . import pa_e0


class PriceActionAnnotationError(RuntimeError):
    pass


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                dir=str(path.parent))
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
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                dir=str(path.parent))
    os.close(fd)
    try:
        frame.to_csv(name, index=False)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _safe_annotator(value: str) -> str:
    if not value or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise PriceActionAnnotationError(f"unsafe annotator identity: {value!r}")
    return value


def _prompt(case: dict[str, Any]) -> str:
    return (
        pa_e0.ANNOTATION_PROMPT
        + "\nThe attached image and the JSON sidecar below are the entire case."
        + " Return ONLY one JSON object with exactly these keys:\n"
        + json.dumps({
            "zone_exists": "boolean",
            "zone_center_atr_from_close": "number, or null if no zone",
            "interaction": "rejection | break | retest | none",
            "stance": "long | neutral | avoid",
            "confidence": "number from 0 to 1",
            "notes": "one short observed-facts sentence",
        }, indent=2)
        + f"\ncase_id={case['case_id']}\nsidecar="
        + json.dumps(case["sidecar"], sort_keys=True, separators=(",", ":"))
    )


def _parse_reply(text: str) -> dict[str, Any]:
    match = _JSON_OBJECT.search(text or "")
    if not match:
        raise PriceActionAnnotationError("model reply contains no JSON object")
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise PriceActionAnnotationError(f"invalid model JSON: {exc}") from exc
    required = {
        "zone_exists", "zone_center_atr_from_close", "interaction", "stance",
        "confidence", "notes",
    }
    if set(payload) != required:
        raise PriceActionAnnotationError(
            f"model JSON keys differ: missing={sorted(required - set(payload))}, "
            f"extra={sorted(set(payload) - required)}")
    exists = pa_e0._bool(payload["zone_exists"])
    interaction = str(payload["interaction"]).strip().lower()
    stance = str(payload["stance"]).strip().lower()
    if interaction not in pa_e0.INTERACTIONS:
        raise PriceActionAnnotationError(f"invalid interaction: {interaction!r}")
    if stance not in pa_e0.STANCES:
        raise PriceActionAnnotationError(f"invalid stance: {stance!r}")
    try:
        confidence = float(payload["confidence"])
    except (TypeError, ValueError) as exc:
        raise PriceActionAnnotationError("confidence is not numeric") from exc
    if not np.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise PriceActionAnnotationError("confidence must lie in [0, 1]")
    centre: float | None = None
    if exists:
        try:
            centre = float(payload["zone_center_atr_from_close"])
        except (TypeError, ValueError) as exc:
            raise PriceActionAnnotationError(
                "zone centre must be numeric when a zone exists") from exc
        if not np.isfinite(centre):
            raise PriceActionAnnotationError("zone centre must be finite")
    return {
        "zone_exists": exists,
        "zone_center_atr_from_close": centre,
        "interaction": interaction,
        "stance": stance,
        "confidence": confidence,
        "notes": str(payload["notes"]).strip()[:500],
    }


def _load_bundle(bundle: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest_path = bundle / "manifest.json"
    cases_path = bundle / "cases.jsonl"
    prompt_path = bundle / "annotation_prompt.txt"
    if not all(path.is_file() for path in (manifest_path, cases_path, prompt_path)):
        raise PriceActionAnnotationError(f"incomplete annotation bundle: {bundle}")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("outcome_accessed") is not False:
        raise PriceActionAnnotationError("annotation bundle is not outcome-free")
    prompt_hash = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    if prompt_hash != manifest.get("annotation_prompt_hash"):
        raise PriceActionAnnotationError("annotation prompt hash mismatch")
    cases = [json.loads(line) for line in cases_path.read_text().splitlines()
             if line.strip()]
    ready = [case for case in cases if case.get("case_status") == "ready"]
    if len(ready) != int(manifest.get("ready_cases", -1)):
        raise PriceActionAnnotationError("ready-case count differs from manifest")
    for case in ready:
        chart = bundle / "charts" / f"{case['case_id']}.png"
        if not chart.is_file() or hashlib.sha256(chart.read_bytes()).hexdigest() \
                != case.get("chart_sha256"):
            raise PriceActionAnnotationError(
                f"chart hash mismatch for {case.get('case_id')}")
        if any(key in case.get("sidecar", {}) for key in (
                "zone_distance_atr", "zone_overlap_frac",
                "rejection_strength_atr", "support_zone_kind",
                "support_touch_count")):
            raise PriceActionAnnotationError(
                f"coded zone leaked into blind case {case['case_id']}")
    return manifest, ready


def run_model_pass(
    bundle: Path,
    *,
    annotator: str,
    provider: str,
    model: str,
    max_cases: int | None = None,
    timeout_s: int = 300,
    agent_fn: Callable[..., agent.AgentResult] = agent.run_agent,
) -> dict[str, Any]:
    """Run or resume one frozen model pass and publish it only when complete."""
    annotator = _safe_annotator(annotator)
    if provider != "codex":
        raise PriceActionAnnotationError(
            "image-sealed E0 passes currently require the codex provider")
    if not model.strip():
        raise PriceActionAnnotationError("an explicit frozen model is required")
    manifest, cases = _load_bundle(bundle)
    annotations_path = bundle / "annotations.csv"
    existing = pd.read_csv(annotations_path)
    if annotator in set(existing.get("annotator", pd.Series(dtype=str)).astype(str)):
        raise PriceActionAnnotationError(
            f"completed annotator already exists: {annotator}")

    run_dir = bundle / "annotation_runs" / annotator
    checkpoints = run_dir / "checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)
    identity = {
        "annotator": annotator,
        "annotator_kind": "model",
        "provider": provider,
        "model": model,
        "prompt_hash": manifest["annotation_prompt_hash"],
        "case_set_hash": manifest["case_set_hash"],
        "outcome_accessed": False,
    }
    identity_path = run_dir / "run_manifest.json"
    if identity_path.exists():
        if json.loads(identity_path.read_text()) != identity:
            raise PriceActionAnnotationError("annotation run identity changed")
    else:
        _atomic_json(identity_path, identity)

    pending = [case for case in cases
               if not (checkpoints / f"{case['case_id']}.json").exists()]
    if max_cases is not None:
        pending = pending[:max(0, max_cases)]
    for case in pending:
        chart = bundle / "charts" / f"{case['case_id']}.png"
        with tempfile.TemporaryDirectory(prefix="pa_annotate_") as empty:
            result = agent_fn(
                _prompt(case), cwd=Path(empty), timeout_s=timeout_s,
                max_turns=1, allowed_tools=(), provider=provider, model=model,
                sandbox="read-only", image_paths=(chart,))
        checkpoint: dict[str, Any] = {
            "case_id": case["case_id"], "ok": False,
            "error": result.stderr[:500] if result.stderr else "",
            "duration_s": result.duration_s,
        }
        if result.ok:
            try:
                checkpoint.update({"ok": True, "annotation": _parse_reply(result.text)})
            except PriceActionAnnotationError as exc:
                checkpoint["error"] = str(exc)
        _atomic_json(checkpoints / f"{case['case_id']}.json", checkpoint)

    artifacts = {
        path.stem: json.loads(path.read_text())
        for path in checkpoints.glob("*.json")
    }
    missing = [case["case_id"] for case in cases if case["case_id"] not in artifacts]
    if missing:
        return {
            "status": "partial", "annotator": annotator,
            "completed": len(artifacts), "remaining": len(missing),
            "failed_calls": sum(not row.get("ok", False) for row in artifacts.values()),
        }

    rows = []
    for case in cases:
        artifact = artifacts[case["case_id"]]
        annotation = artifact.get("annotation") if artifact.get("ok") else {
            "zone_exists": False, "zone_center_atr_from_close": None,
            "interaction": "none", "stance": "neutral", "confidence": 0.0,
            "notes": f"CALL_FAILED: {artifact.get('error', 'unknown error')}",
        }
        rows.append({
            "case_id": case["case_id"], **identity,
            **annotation,
        })
    added = pd.DataFrame(rows)[list(pa_e0.ANNOTATION_COLUMNS)]
    combined = pd.concat([existing, added], ignore_index=True)
    _atomic_csv(annotations_path, combined)
    completion = {
        **identity, "status": "complete", "cases": len(cases),
        "failed_calls": int(added["notes"].astype(str).str.startswith(
            "CALL_FAILED:").sum()),
    }
    _atomic_json(run_dir / "completion.json", completion)
    return completion


__all__ = ["PriceActionAnnotationError", "run_model_pass"]
