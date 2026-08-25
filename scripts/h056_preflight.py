#!/usr/bin/env python3
"""Run H056's outcome-free structural preflight on an intraday data product."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.research.families.machine_geometry import (  # noqa: E402
    RetestPrior,
    exit_policy_grid,
    generate_retest_population,
)
from src.research_data import frame  # noqa: E402
from src.research_data.pipelines import causal_zones  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="pa_bootstrap_v4")
    parser.add_argument("--split-version", default="v1")
    parser.add_argument("--partition", default="train")
    parser.add_argument("--output", type=Path, default=(
        config.METADATA_DIR / "research_store" / "price_action"
        / "h056_structural_preflight.json"))
    return parser.parse_args()


def rejection_counts(population: pd.DataFrame) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for value in population.get("rejection_reasons", pd.Series(dtype=str)).fillna(""):
        counts.update(item for item in str(value).split("|") if item)
    return dict(sorted(counts.items()))


def main() -> int:
    options = parse_args()
    bars = frame.load_intraday_panel(
        version=options.version,
        partition=options.partition,
        split_version=options.split_version,
        base_interval="5minute",
    )
    features = causal_zones.build_zone_state_machine(bars)
    prior = RetestPrior()
    population = generate_retest_population(features, prior)
    eligible = (
        population.loc[population["eligible"].fillna(False)].copy()
        if "eligible" in population else population.iloc[0:0].copy())
    report = {
        "artifact_version": "h056_structural_preflight.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "H056",
        "outcomes_opened": False,
        "dataset_version": options.version,
        "split_version": options.split_version,
        "partition": options.partition,
        "manual_prior": prior.to_dict(),
        "exit_policy_grid": exit_policy_grid(prior),
        "input": {
            "bars": int(len(bars)),
            "sessions": int(bars["session"].nunique()),
            "symbols": int(bars["symbol_asof"].nunique()),
        },
        "population": {
            "role_reversal_retests": int(len(population)),
            "eligible": int(len(eligible)),
            "eligible_sessions": int(eligible["session"].nunique()) if len(eligible) else 0,
            "eligible_symbols": int(eligible["symbol"].nunique()) if len(eligible) else 0,
            "direction": {
                str(key): int(value)
                for key, value in population.get(
                    "direction", pd.Series(dtype=str)).value_counts().items()
            },
            "eligible_direction": {
                str(key): int(value)
                for key, value in eligible.get(
                    "direction", pd.Series(dtype=str)).value_counts().items()
            },
            "rejection_counts_nonexclusive": rejection_counts(population),
        },
        "status": (
            "bootstrap_has_eligible_retests" if len(eligible)
            else "bootstrap_too_sparse_under_initial_prior"),
        "interpretation": (
            "Outcome-free density only. Thresholds may be changed only as a "
            "recorded H056 development revision; this report contains no alpha evidence."
        ),
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
