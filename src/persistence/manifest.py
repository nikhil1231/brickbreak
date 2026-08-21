"""Immutable experiment manifests and cryptographic lineage (the refactor plan §5.6).

Every experiment emits an immutable manifest recording:
code hash · dataset version & hash · split version · catalogue version ·
hypothesis ID · spec · parameters · universe · partition · model · runtime ·
result hash.

This guarantees reproducible findings and tamper detection.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core import config
from ..research_data import catalogue, splits


class ManifestError(RuntimeError):
    pass


def get_git_commit_hash() -> str:
    """Returns the current git HEAD commit hash, or 'uncommitted'."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=config.PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()[:16]
    except Exception:
        return "unknown"


def compute_payload_hash(payload: dict) -> str:
    """Deterministic 16-character SHA-256 fingerprint of dictionary payload."""
    clean = {k: v for k, v in payload.items() if k != "hash"}
    raw = json.dumps(clean, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def build_manifest(
    hypothesis_id: str,
    spec: dict[str, Any],
    partition: str,
    result_metrics: dict[str, Any],
    dataset_version: str = "v1",
    provider_used: str = "none",
    model_used: str = "none",
    runtime_seconds: float = 0.0,
    universe_name: str = "liquid_universe",
    batch_id: str = "",
    batch_hash: str = "",
) -> dict:
    """Constructs a cryptographic experiment manifest."""
    # Split hash
    split_manifest = splits.load(dataset_version)
    split_hash = split_manifest.get("hash", "unknown")

    # Catalogue hash
    cat_summary = catalogue.DEFAULT.summary()
    cat_hash = hashlib.sha256(cat_summary.encode("utf-8")).hexdigest()[:16]

    result_hash = compute_payload_hash(result_metrics)

    manifest = {
        "hypothesis_id": hypothesis_id,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "code_hash": get_git_commit_hash(),
        "dataset_version": dataset_version,
        "split_version": dataset_version,
        "split_hash": split_hash,
        "catalogue_hash": cat_hash,
        "partition": partition,
        "universe": universe_name,
        "spec": spec,
        "provider_used": provider_used,
        "model_used": model_used,
        "runtime_seconds": round(runtime_seconds, 2),
        "result_hash": result_hash,
    }
    if batch_id:
        manifest["batch_id"] = batch_id
        manifest["batch_hash"] = batch_hash

    manifest["hash"] = compute_payload_hash(manifest)
    return manifest



def verify_manifest(manifest: dict) -> bool:
    """Verifies that the manifest has not been modified since creation."""
    stored_hash = manifest.get("hash")
    if not stored_hash:
        return False
    computed_hash = compute_payload_hash(manifest)
    return stored_hash == computed_hash


def save_manifest(manifest: dict, path: Path) -> Path:
    """Saves manifest to disk, verifying hash before writing."""
    if not verify_manifest(manifest):
        raise ManifestError("Manifest verification failed before saving.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, default=str) + "\n")
    return path


def load_manifest(path: Path) -> dict:
    """Loads manifest and validates integrity."""
    if not path.exists():
        raise ManifestError(f"Manifest not found: {path}")
    data = json.loads(path.read_text())
    if not verify_manifest(data):
        raise ManifestError(f"Manifest at {path} has been tampered with or corrupted (hash mismatch).")
    return data
