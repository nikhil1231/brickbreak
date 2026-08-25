#!/usr/bin/env python3
"""Freeze the H057 development manifest over the point-in-time F&O universe.

This replaces `prepare_h056_nse_development.py`, whose universe was the ₹3-25
crore cash turnover band. That band was inherited from the daily programme and
is not tradable by this account: an NRI cannot square off intraday in the cash
segment and cannot short cash equities, so an intraday or bearish claim is
executable only in F&O — and the F&O eligibility floor sits far above ₹25 crore.
The two universes barely intersect.

Cash intraday bars remain the right thing to *pull*. Levels are drawn on the
cash series, which is continuous and free of roll discontinuities; the futures
series supplies execution prices and costs. What changes is which symbols.

Train and validation are development. Test and forward are refused here so the
final estimate stays untouched.
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
from src.research_data.pipelines import fo_universe, intraday, renames  # noqa: E402
from src.research_data.sources import security_master  # noqa: E402


ALLOWED_DEVELOPMENT_PARTITIONS = ("train", "validation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="h057_fo_development_v1")
    parser.add_argument("--split-version", default="v1")
    parser.add_argument(
        "--partitions", nargs="+", default=list(ALLOWED_DEVELOPMENT_PARTITIONS))
    parser.add_argument("--max-requests", type=int, default=None,
                        help="cap the manifest; omitted means the full universe")
    parser.add_argument("--output", type=Path, default=(
        config.METADATA_DIR / "research_store" / "price_action"
        / "h057_fo_development_contract.json"))
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
            "H057 development refuses test/forward or unknown partitions: "
            + ", ".join(sorted(forbidden)))

    universe = fo_universe.tradable(fo_universe.load())
    universe = universe.loc[universe["tradable"]].copy()
    universe["session"] = pd.to_datetime(universe["session"]).dt.normalize()
    universe["symbol"] = universe["symbol"].astype(str).str.upper()

    # The split is defined on the daily equity panel, so partitions are attached
    # by session through it rather than re-derived here.
    panel = frame.load_daily_panel(
        version=options.split_version, columns=["symbol", "date", "series"],
        drop_purged=False)
    panel["date"] = pd.to_datetime(panel["date"], errors="raise").dt.normalize()
    session_partition = panel[["date", "partition"]].drop_duplicates("date") \
        .rename(columns={"date": "session"})

    eligible = universe.merge(session_partition, on="session", how="inner")
    eligible = eligible.loc[eligible["partition"].isin(partitions)].copy()
    if eligible.empty:
        raise SystemExit("no F&O symbol-sessions fell in the development partitions")

    codes = resolve_codes(sorted(eligible["symbol"].unique()))
    eligible["instrument_id"] = eligible["symbol"].map(codes)
    eligible["mapped"] = eligible["instrument_id"].notna()
    # Traded value here is the futures leg's, which is the right weight: it is
    # the venue the position is actually taken in.
    eligible["tv_weight"] = eligible["traded_value"].clip(lower=0).fillna(0.0)

    coverage = []
    for (partition, year), group in eligible.groupby(
            ["partition", eligible["session"].dt.year], sort=True):
        total_tv = float(group["tv_weight"].sum())
        mapped_tv = float(group.loc[group["mapped"], "tv_weight"].sum())
        coverage.append({
            "partition": str(partition), "year": int(year),
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
        raise SystemExit(
            "point-in-time identity coverage failed; manifest not written\n"
            + json.dumps(coverage, indent=2, default=str))

    pairs = eligible.loc[eligible["mapped"], ["instrument_id", "symbol", "session"]] \
        .rename(columns={"symbol": "symbol_asof"})
    requests = intraday.build_request_manifest(
        pairs, version=options.version, interval="5minute",
        all_sessions=splits.sessions())
    if options.max_requests and len(requests) > options.max_requests:
        # Truncation is by instrument, never by date: dropping late sessions
        # would silently shorten every symbol's history and bias the level book.
        keep = requests["instrument_id"].drop_duplicates()
        chosen: list[str] = []
        running = 0
        counts = requests.groupby("instrument_id").size()
        for instrument in keep:
            if running + int(counts[instrument]) > options.max_requests:
                continue
            chosen.append(instrument)
            running += int(counts[instrument])
        requests = requests.loc[requests["instrument_id"].isin(chosen)].copy()

    root = intraday.acquisition_root(options.version)
    intraday.write_request_manifest(requests, root)
    report = {
        "artifact_version": "h057_fo_development_contract.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "H057",
        "status": "manifest_frozen",
        "outcomes_opened": False,
        "dataset_version": options.version,
        "split_version": options.split_version,
        "partition_semantics": (
            {partition: "development" for partition in partitions}
            | {"test": "untouched_final", "forward": "untouched_final"}),
        "universe": {
            "definition": "point-in-time NSE stock-futures membership",
            "source": "NSE derivatives bhavcopy (legacy + UDiFF eras)",
            "why": (
                "an NRI cannot trade cash intraday or short cash equities, so "
                "the executable universe is F&O membership, not a cash "
                "turnover band"),
            "liquidity_floors": fo_universe.UniverseConfig().__dict__,
            "cash_bars_pulled_for": "level geometry and intra-hour path",
            "futures_prices_used_for": "execution, costs and capacity",
        },
        "coverage_thresholds": {
            "symbol_sessions_pct": 95.0, "traded_value_pct": 98.0},
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
            "Any H057 refinement after outcome access remains development."),
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
