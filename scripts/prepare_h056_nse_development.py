#!/usr/bin/env python3
"""Freeze the label-free old-NSE development manifest for H056.

Train and validation are deliberately renamed development here. Test and
forward are refused so the final NSE estimate remains untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.research_data import frame, splits  # noqa: E402
from src.research_data.pipelines import intraday, renames  # noqa: E402
from src.research_data.sources import security_master  # noqa: E402


ALLOWED_DEVELOPMENT_PARTITIONS = ("train", "validation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="h056_nse_development_v1")
    parser.add_argument("--split-version", default="v1")
    parser.add_argument(
        "--partitions", nargs="+", default=list(ALLOWED_DEVELOPMENT_PARTITIONS))
    parser.add_argument("--output", type=Path, default=(
        config.METADATA_DIR / "research_store" / "price_action"
        / "h056_nse_development_contract.json"))
    return parser.parse_args()


def resolve_codes(symbols: list[str]) -> dict[str, str | None]:
    master = security_master.load()
    canonical = renames.canonical_map(renames.load_map())
    resolved: dict[str, str | None] = {}
    for symbol in symbols:
        candidate = canonical.get(symbol, symbol)
        security = security_master.resolve(master, candidate)
        if security is None and candidate != symbol:
            security = security_master.resolve(master, symbol)
        resolved[symbol] = None if security is None else security.isec_code
    return resolved


def main() -> int:
    options = parse_args()
    partitions = tuple(dict.fromkeys(options.partitions))
    forbidden = set(partitions) - set(ALLOWED_DEVELOPMENT_PARTITIONS)
    if forbidden:
        raise SystemExit(
            "H056 NSE development refuses test/forward or unknown partitions: "
            + ", ".join(sorted(forbidden)))

    panel = frame.load_daily_panel(
        version=options.split_version,
        columns=["symbol", "date", "median_tv_20_cr", "series", "is_etf"],
        drop_purged=False,
    )
    panel["date"] = pd.to_datetime(panel["date"], errors="raise").dt.normalize()
    panel["symbol"] = panel["symbol"].astype(str).str.upper()
    eligible = panel.loc[
        panel["partition"].isin(partitions)
        & panel["median_tv_20_cr"].between(3.0, 25.0)
        & panel["series"].eq("EQ")
        & ~panel["is_etf"].fillna(False)
    ].drop_duplicates(["symbol", "date"]).copy()
    codes = resolve_codes(sorted(eligible["symbol"].unique()))
    eligible["instrument_id"] = eligible["symbol"].map(codes)
    eligible["mapped"] = eligible["instrument_id"].notna()
    eligible["tv_weight"] = eligible["median_tv_20_cr"].clip(lower=0)

    coverage = []
    for (partition, year), group in eligible.groupby(
            ["partition", eligible["date"].dt.year], sort=True):
        total_tv = float(group["tv_weight"].sum())
        mapped_tv = float(group.loc[group["mapped"], "tv_weight"].sum())
        coverage.append({
            "partition": str(partition),
            "year": int(year),
            "symbol_sessions": int(len(group)),
            "symbols": int(group["symbol"].nunique()),
            "mapped_symbol_sessions_pct": round(float(group["mapped"].mean() * 100), 6),
            "mapped_traded_value_pct": round(
                mapped_tv / total_tv * 100.0 if total_tv else 0.0, 6),
            "unmapped_symbols": sorted(group.loc[~group["mapped"], "symbol"].unique()),
        })
    coverage_passed = bool(coverage) and all(
        row["mapped_symbol_sessions_pct"] >= 95.0
        and row["mapped_traded_value_pct"] >= 98.0
        for row in coverage)
    if not coverage_passed:
        raise SystemExit("point-in-time identity coverage failed; manifest not written")

    pairs = eligible.loc[eligible["mapped"], [
        "instrument_id", "symbol", "date"]].rename(columns={
            "symbol": "symbol_asof", "date": "session"})
    requests = intraday.build_request_manifest(
        pairs,
        version=options.version,
        interval="5minute",
        all_sessions=splits.sessions(),
    )
    root = intraday.acquisition_root(options.version)
    intraday.write_request_manifest(requests, root)
    report = {
        "artifact_version": "h056_nse_development_contract.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "H056",
        "status": "manifest_frozen",
        "outcomes_opened": False,
        "dataset_version": options.version,
        "split_version": options.split_version,
        "partition_semantics": {
            partition: "development" for partition in partitions
        } | {"test": "untouched_final", "forward": "untouched_final"},
        "universe": {
            "series": "EQ", "etfs_excluded": True,
            "lagged_median_tv_20_cr": [3.0, 25.0],
        },
        "coverage_thresholds": {
            "symbol_sessions_pct": 95.0, "traded_value_pct": 98.0,
        },
        "coverage_by_partition_year": coverage,
        "identity_coverage_passed": coverage_passed,
        "manifest": {
            "root": str(root),
            "hash": intraday.manifest_fingerprint(requests),
            "acquisition_code_hash": intraday.acquisition_code_fingerprint(),
            "requests": int(len(requests)),
            "instrument_ids": int(requests["instrument_id"].nunique()),
            "symbol_asof": int(requests["symbol_asof"].nunique()),
            "requested_symbol_sessions": int(len(pairs)),
            "expected_max_rows": int(requests["expected_max_rows"].sum()),
        },
        "remote_only": True,
        "final_test_guard": (
            "No test or forward session appears in this request manifest. "
            "Any H056 refinement after outcome access remains development."
        ),
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
