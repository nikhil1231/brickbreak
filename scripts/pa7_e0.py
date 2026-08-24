#!/usr/bin/env python3
"""Prepare or evaluate the real, outcome-free H055 E0 bundle."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.discretionary import pa_e0  # noqa: E402
from src.research_data import frame, splits  # noqa: E402
from src.research_data.pipelines import causal_zones, intraday  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "report"))
    parser.add_argument("--version", default="pa_bootstrap_v4")
    parser.add_argument("--split-version", default="v1")
    parser.add_argument("--bundle", type=Path, default=(
        config.METADATA_DIR / "research_store" / "price_action" / "pa7_e0_bundle"))
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--n-cases", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20260824)
    return parser.parse_args()


def feature_frame(version: str, split_version: str) -> pd.DataFrame:
    manifest_path = intraday.dataset_manifest_path(version, "5minute")
    if not manifest_path.exists():
        split_manifest = splits.load(split_version)
        intraday.build_dataset(
            intraday.acquisition_root(version), split_version=split_version,
            split_hash=split_manifest["hash"])
    bars = frame.load_intraday_panel(
        version=version, partition=None, split_version=split_version,
        base_interval="5minute")
    daily = frame.bars(
        version=split_version, columns=["adj_factor"], drop_purged=False)
    bars = causal_zones.annotate_corporate_actions(bars, daily)
    return causal_zones.build_zone_state_machine(bars)


def reports(options: argparse.Namespace, features: pd.DataFrame,
            candidates: pd.DataFrame) -> dict:
    acquisition = intraday.verify_acquisition(
        intraday.acquisition_root(options.version), require_complete=True)
    identity_path = (config.METADATA_DIR / "research_store" / "price_action"
                     / "pa2_identity_pa4_request_report.json")
    identity = json.loads(identity_path.read_text())
    annotation_path = options.annotations or options.bundle / "annotations.csv"
    annotations = pd.read_csv(annotation_path) if annotation_path.exists() else None
    cases_path = options.bundle / "cases.jsonl"
    ready_case_ids = None
    prompt_hash = None
    if cases_path.exists():
        records = [json.loads(line) for line in cases_path.read_text().splitlines()
                   if line.strip()]
        ready_case_ids = {
            str(record["case_id"]) for record in records
            if record.get("case_status") == "ready"}
        prompt_hash = json.loads(
            (options.bundle / "manifest.json").read_text()
        )["annotation_prompt_hash"]
    return pa_e0.structural_report(
        features, candidates, acquisition_report=acquisition,
        identity_report=identity, annotations=annotations,
        annotation_case_ids=ready_case_ids,
        annotation_prompt_hash=prompt_hash)


def main() -> int:
    options = parse_args()
    features = feature_frame(options.version, options.split_version)
    candidates = pa_e0.generate_candidates(features)
    if "partition" in candidates.columns:
        candidates = candidates[candidates["partition"].eq("train")].copy()

    if options.mode == "prepare":
        manifest = pa_e0.freeze_annotation_bundle(
            candidates, features, options.bundle, n_cases=options.n_cases,
            seed=options.seed)
        candidates.to_parquet(options.bundle / "candidates_private.parquet", index=False)
        report = reports(options, features, candidates)
        (options.bundle / "e0_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
        print(json.dumps({"bundle": str(options.bundle), "manifest": manifest,
                          "e0_status": report["status"]}, indent=2))
        return 0

    candidate_path = options.bundle / "candidates_private.parquet"
    if not candidate_path.exists():
        raise SystemExit(f"missing frozen candidates: {candidate_path}; run prepare first")
    frozen_candidates = pd.read_parquet(candidate_path)
    report = reports(options, features, frozen_candidates)
    (options.bundle / "e0_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({"bundle": str(options.bundle), "e0_status": report["status"],
                      "gates": report["gates"]}, indent=2))
    return 0 if report["status"] == "passed" else 4


if __name__ == "__main__":
    raise SystemExit(main())
