#!/usr/bin/env python3
"""Create the label-free PA4 bootstrap manifest from the PIT daily panel."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.research_data import frame, splits  # noqa: E402
from src.research_data.pipelines import intraday, renames  # noqa: E402
from src.research_data.sources import security_master  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="pa_bootstrap_v3")
    parser.add_argument("--n-anchors", type=int, default=50)
    parser.add_argument("--warmup-sessions", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20260824)
    return parser.parse_args()


def resolve_codes(symbols: list[str]) -> dict[str, str | None]:
    master = security_master.load()
    canonical = renames.canonical_map(renames.load_map())
    result: dict[str, str | None] = {}
    for symbol in symbols:
        candidate = canonical.get(symbol, symbol)
        resolved = security_master.resolve(master, candidate)
        if resolved is None and candidate != symbol:
            resolved = security_master.resolve(master, symbol)
        result[symbol] = None if resolved is None else resolved.isec_code
    return result


def main() -> int:
    options = parse_args()
    columns = ["symbol", "date", "median_tv_20_cr", "series", "is_etf"]
    panel = frame.load_daily_panel(
        version="v1", columns=columns, drop_purged=False)
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    panel["symbol"] = panel["symbol"].astype(str).str.upper()
    panel = panel.sort_values(["symbol", "date"], kind="stable")
    panel["_history_n"] = panel.groupby("symbol", sort=False).cumcount() + 1
    eligible = panel[
        panel["median_tv_20_cr"].between(3.0, 25.0)
        & panel["series"].eq("EQ")
        & ~panel["is_etf"].fillna(False)
        & panel["date"].ge("2020-01-01")
    ].drop_duplicates(["symbol", "date"]).copy()
    codes = resolve_codes(sorted(eligible["symbol"].unique()))
    eligible["instrument_id"] = eligible["symbol"].map(codes)
    eligible["mapped"] = eligible["instrument_id"].notna()
    eligible["tv_weight"] = eligible["median_tv_20_cr"].clip(lower=0)

    coverage_rows = []
    for year, group in eligible.groupby(eligible["date"].dt.year):
        coverage_rows.append({
            "year": int(year), "symbol_sessions": int(len(group)),
            "symbols": int(group["symbol"].nunique()),
            "mapped_symbol_sessions_pct": round(float(group["mapped"].mean() * 100), 6),
            "mapped_traded_value_pct": round(float(
                group.loc[group["mapped"], "tv_weight"].sum()
                / group["tv_weight"].sum() * 100), 6),
            "unmapped_symbols": sorted(group.loc[~group["mapped"], "symbol"].unique()),
        })
    coverage_passed = all(
        row["mapped_symbol_sessions_pct"] >= 95.0
        and row["mapped_traded_value_pct"] >= 98.0
        for row in coverage_rows)

    train = eligible[
        eligible["mapped"] & eligible["partition"].eq("train")].copy()
    train["era"] = pd.cut(
        train["date"].dt.year,
        bins=[2019, 2021, 2023, 2026],
        labels=["2020-2021", "2022-2023", "2024-2026"])
    train["liquidity_stratum"] = pd.qcut(
        train["median_tv_20_cr"], 3, labels=["low", "mid", "high"])
    candidates = train[
        train["_history_n"].ge(options.warmup_sessions)
    ].dropna(subset=["era", "liquidity_stratum"]).copy()
    # One possible anchor per symbol/group avoids letting long-lived names
    # dominate the bootstrap simply because they have more rows.
    rng = np.random.default_rng(options.seed)
    candidates["_random"] = rng.random(len(candidates))
    candidates = candidates.sort_values("_random").drop_duplicates(
        ["symbol", "era", "liquidity_stratum"])
    groups = list(candidates.groupby(["era", "liquidity_stratum"], observed=True))
    picked = []
    while len(picked) < options.n_anchors:
        progressed = False
        for _, group in groups:
            offset = sum(1 for row in picked if row["era"] == str(group["era"].iloc[0])
                         and row["liquidity_stratum"] == str(group["liquidity_stratum"].iloc[0]))
            if offset < len(group):
                picked.append(group.iloc[offset].to_dict())
                progressed = True
                if len(picked) >= options.n_anchors:
                    break
        if not progressed:
            break
    anchors = pd.DataFrame(picked)
    if len(anchors) < options.n_anchors:
        raise SystemExit(f"only {len(anchors)} distinct bootstrap anchors available")

    calendar = splits.sessions()
    symbol_history = {
        symbol: group["date"].drop_duplicates().sort_values().to_numpy()
        for symbol, group in panel.groupby("symbol", sort=False)
    }
    request_pairs = []
    for row in anchors.itertuples(index=False):
        history_all = pd.DatetimeIndex(symbol_history[str(row.symbol)])
        history = history_all[history_all <= pd.Timestamp(row.date)][
            -options.warmup_sessions:]
        if len(history) < options.warmup_sessions:
            raise SystemExit(
                f"anchor {row.symbol}/{row.date} has only {len(history)} "
                "actual prior trading sessions")
        for session in history:
            request_pairs.append({
                "instrument_id": row.instrument_id,
                "symbol_asof": row.symbol,
                "session": session,
            })
    requests = intraday.build_request_manifest(
        pd.DataFrame(request_pairs), version=options.version,
        interval="5minute", all_sessions=calendar)
    root = intraday.acquisition_root(options.version)
    intraday.write_request_manifest(requests, root)

    report_dir = config.METADATA_DIR / "research_store" / "price_action"
    report_dir.mkdir(parents=True, exist_ok=True)
    anchors_path = report_dir / "pa4_bootstrap_anchors.parquet"
    anchors[["symbol", "date", "instrument_id", "era", "liquidity_stratum",
             "median_tv_20_cr", "partition"]].to_parquet(anchors_path, index=False)
    report = {
        "stage": "PA2_IDENTITY_AND_PA4_REQUESTS",
        "status": "manifest_frozen",
        "supersedes_unfetched_versions": ["pa_bootstrap_v1", "pa_bootstrap_v2"],
        "acquisition_code_hash": intraday.acquisition_code_fingerprint(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "outcome_accessed": False,
        "coverage_thresholds": {
            "symbol_sessions_pct": 95.0, "traded_value_pct": 98.0,
        },
        "coverage_by_year": coverage_rows,
        "identity_coverage_passed": coverage_passed,
        "bootstrap": {
            "seed": options.seed, "anchors": int(len(anchors)),
            "warmup_sessions": options.warmup_sessions,
            "requests": int(len(requests)),
            "expected_max_rows": int(requests["expected_max_rows"].sum()),
            "manifest_hash": intraday.manifest_fingerprint(requests),
            "acquisition_root": str(root),
        },
    }
    report_path = report_dir / "pa2_identity_pa4_request_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "report": str(report_path), "coverage_passed": coverage_passed,
        "anchors": len(anchors), "requests": len(requests),
        "expected_rows": int(requests["expected_max_rows"].sum()),
        "manifest_hash": intraday.manifest_fingerprint(requests),
    }, indent=2))
    return 0 if coverage_passed else 4


if __name__ == "__main__":
    raise SystemExit(main())
