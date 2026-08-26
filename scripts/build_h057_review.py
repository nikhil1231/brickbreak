#!/usr/bin/env python3
"""Freeze the H057 blind level-audit deck, or score a finalised pass.

Build:  python scripts/build_h057_review.py --symbols 40 --cases 60
Score:  python scripts/build_h057_review.py --score <annotator>

The deck is balanced real-versus-control, so chance is exactly 50%. It spends no
new sample: H057's path exposure is already logged and its result published, and
this re-renders cases from that same read.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.research.families import level_audit as h057_review  # noqa: E402
from src.research_data import frame  # noqa: E402
from src.research_data.pipelines import levels  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="h057_fo_development_v1")
    parser.add_argument("--symbols", type=int, default=40)
    parser.add_argument("--cases", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20260826)
    parser.add_argument("--score", metavar="ANNOTATOR")
    parser.add_argument("--output", type=Path, default=(
        config.METADATA_DIR / "research_store" / "price_action"
        / "h057_level_audit"))
    return parser.parse_args()


def main() -> int:
    options = parse_args()
    if options.score:
        print(json.dumps(
            h057_review.score_pass(options.output, options.score), indent=2))
        return 0

    bars = frame.load_intraday_panel(
        version=options.version, base_interval="5minute")
    rng = np.random.default_rng(options.seed)
    symbols = sorted(bars["symbol_asof"].unique())
    chosen = rng.choice(symbols, size=min(options.symbols, len(symbols)),
                        replace=False)
    bars = bars.loc[bars["symbol_asof"].isin(chosen)]

    panel = bars.rename(columns={
        "symbol_asof": "symbol", "open_raw": "open", "high_raw": "high",
        "low_raw": "low", "close_raw": "close", "volume_raw": "volume"})
    panel = panel[["symbol", "session", "bar_end", "open", "high", "low",
                   "close", "volume"]].copy()
    # Parquet hands back pyarrow-backed columns; forcing numpy dtypes once here
    # is what keeps every later element access from re-materialising a slice.
    for column in ("open", "high", "low", "close", "volume"):
        panel[column] = np.asarray(panel[column], dtype=float)
    panel["symbol"] = np.asarray(panel["symbol"], dtype=object)
    panel["session"] = pd.to_datetime(np.asarray(panel["session"]))
    panel["bar_end"] = pd.to_datetime(np.asarray(panel["bar_end"]))

    print(f"panel: {len(panel):,} bars, {panel['symbol'].nunique()} symbols")
    cases = h057_review.collect_cases(panel, seed=options.seed)
    print(f"approach events: {len(cases):,} "
          f"({int((cases['book'] == 'real').sum()):,} real)")

    hourly = levels.resample_hourly(panel)
    manifest = h057_review.freeze_review_bundle(
        cases, hourly.loc[hourly["complete"]], panel, options.output,
        n_cases=options.cases, seed=options.seed)
    print(json.dumps(manifest, indent=2, sort_keys=True)[:1200])
    print(f"\nfrozen at {options.output}")
    print(f"real={manifest['real_cases']} control={manifest['control_cases']} "
          f"failures={manifest['source_failures']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
