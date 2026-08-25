#!/usr/bin/env python3
"""Run the H057 level-reaction study on the F&O development panel.

Registered in HYPOTHESES.md before this was first executed. The frozen bar is:
primary cell (barrier 0.50 ATR, horizon 24 five-minute bars, control
`permuted_geometry`) must show a mean paired contrast of at least +0.02 in
rejection rate with session-clustered t >= 3.0, and the grid maximum must clear
a permutation p <= 0.05.

This reads the future five-minute path and is logged exposure. It reads no sign,
no directional hit rate and no payoff. Test and forward are absent from the
dataset by construction, so the final estimate stays untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.research.families import level_reaction  # noqa: E402
from src.research_data import frame  # noqa: E402
from src.research_data.pipelines import levels  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="h057_fo_development_v1")
    parser.add_argument("--split-version", default="v1")
    parser.add_argument("--symbols", type=int, default=None,
                        help="profile on the first N symbols by name")
    parser.add_argument("--detectors", nargs="+",
                        default=sorted(levels.DETECTORS))
    # Monte-Carlo precision of the control only. It changes neither the
    # estimand, the primary cell, nor the frozen bar: with five fake levels per
    # real one the control's sampling noise is already a small fraction of the
    # real book's, and the panel is otherwise too large to hold in memory.
    parser.add_argument("--pseudo-per-real", type=int, default=5)
    parser.add_argument("--symbol-batch", type=int, default=8)
    parser.add_argument("--output", type=Path, default=(
        config.METADATA_DIR / "research_store" / "price_action"
        / "h057_reaction_study.json"))
    return parser.parse_args()


def main() -> int:
    options = parse_args()
    started = time.time()
    bars = frame.load_intraday_panel(
        version=options.version, split_version=options.split_version,
        base_interval="5minute")

    # The manifest contained only development sessions, but that is a property
    # of how it was built, not a guarantee about what is on disk. Assert it.
    partitions = set(bars["partition"].dropna().unique())
    leaked = partitions - {"train", "validation"}
    if leaked:
        raise SystemExit(
            f"refusing to run: dataset contains non-development partitions {sorted(leaked)}")

    if options.symbols:
        keep = sorted(bars["symbol_asof"].unique())[:options.symbols]
        bars = bars.loc[bars["symbol_asof"].isin(keep)].copy()

    panel = bars.rename(columns={
        "symbol_asof": "symbol", "open_raw": "open", "high_raw": "high",
        "low_raw": "low", "close_raw": "close", "volume_raw": "volume"})
    panel = panel[["symbol", "session", "bar_end", "open", "high", "low",
                   "close", "volume"]].copy()
    # Parquet can hand back pyarrow-backed columns. Any later element access on
    # one re-materialises a ChunkedArray slice, which is invisible until it
    # turns an inner loop into hours of thrashing. Force numpy dtypes once here.
    for column in ("open", "high", "low", "close", "volume"):
        panel[column] = np.asarray(panel[column], dtype=float)
    panel["symbol"] = np.asarray(panel["symbol"], dtype=object)
    panel["session"] = pd.to_datetime(np.asarray(panel["session"]))
    panel["bar_end"] = pd.to_datetime(np.asarray(panel["bar_end"]))

    def progress(number: int, total: int, batch: list[str]) -> None:
        print(f"batch {number}/{total} ({len(batch)} symbols, "
              f"{time.time() - started:.0f}s elapsed)", flush=True)

    report = level_reaction.run_reaction_study(
        panel, detectors=tuple(options.detectors),
        config=level_reaction.ReactionConfig(
            pseudo_per_real=options.pseudo_per_real),
        symbol_batch=options.symbol_batch, progress=progress)
    report["hypothesis"] = "H057"
    report["dataset_version"] = options.version
    report["created_at"] = datetime.now(timezone.utc).isoformat()
    report["runtime_seconds"] = round(time.time() - started, 1)
    report["panel"] = {
        "bars": int(len(panel)),
        "symbols": int(panel["symbol"].nunique()),
        "sessions": int(panel["session"].nunique()),
        "first_session": str(pd.Timestamp(panel["session"].min()).date()),
        "last_session": str(pd.Timestamp(panel["session"].max()).date()),
        "partitions": sorted(partitions),
    }
    if options.symbols:
        report["status"] = f"{report.get('status')}_subsample"

    grid = pd.DataFrame(report.get("grid", []))
    if not grid.empty:
        primary = grid.loc[grid["primary"]
                           & grid["control"].eq("permuted_geometry")]
        report["frozen_bar"] = {
            "min_contrast": 0.02, "min_t": 3.0, "max_permutation_p": 0.05,
            "primary_cell": "barrier 0.50 ATR / horizon 24 bars / permuted_geometry",
        }
        verdicts = {}
        for row in primary.to_dict("records"):
            passes = (
                row["mean_contrast"] is not None
                and row["mean_contrast"] >= 0.02
                and row["t_stat"] is not None and row["t_stat"] >= 3.0
                and (report["multiplicity"].get("null_p") is not None
                     and report["multiplicity"]["null_p"] <= 0.05))
            verdicts[row["detector"]] = "PASS" if passes else "FAIL"
        report["frozen_bar"]["verdict_by_detector"] = verdicts
        report["frozen_bar"]["overall"] = (
            "PASS" if any(v == "PASS" for v in verdicts.values()) else "FAIL")

    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")

    print(json.dumps(report.get("panel", {}), indent=1))
    print("book sizes:", report.get("book_sizes"))
    print("events:", report.get("events"))
    if not grid.empty:
        view = grid.loc[grid["primary"]].copy()
        for column in ("mean_contrast", "real_rejection_rate",
                       "pseudo_rejection_rate", "t_stat"):
            view[column] = pd.to_numeric(view[column], errors="coerce").round(4)
        print("\nPRIMARY CELL (barrier 0.50 ATR, horizon 24 bars):")
        print(view[["detector", "control", "real_rejection_rate",
                    "pseudo_rejection_rate", "mean_contrast", "t_stat",
                    "n_sessions", "n_symbol_sessions"]].to_string(index=False))
        print("\nmultiplicity:", report.get("multiplicity"))
        print("verdict:", report.get("frozen_bar", {}).get("overall"),
              report.get("frozen_bar", {}).get("verdict_by_detector"))
    print(f"\nwrote {options.output}  ({report['runtime_seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
