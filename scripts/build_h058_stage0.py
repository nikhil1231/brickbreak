#!/usr/bin/env python
"""Freeze the H058 Stage 0 deck.

Stage 0 measures two things and spends nothing: whether the reviewer's own
take/skip judgement survives seeing the same chart twice, and what a data point
costs in minutes. It reads no outcome, and it draws from `validation` so that
the 306 sessions of `test` stay whole for the single Stage 2 read.

    python scripts/build_h058_stage0.py [--cases 120] [--repeats 30]

Refuses to overwrite an existing bundle. A frozen deck that can be rebuilt in
place is not frozen.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core import config  # noqa: E402
from src.research_data import splits  # noqa: E402
from src.research_data.pipelines import corporate_actions, fo_universe  # noqa: E402
from src.research.families import setup_grind  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=120,
                        help="distinct decisions in the deck")
    parser.add_argument("--repeats", type=int, default=30,
                        help="how many of them are shown a second time")
    parser.add_argument("--seed", type=int, default=20260827)
    parser.add_argument("--partition", default="validation")
    args = parser.parse_args()

    output = (config.METADATA_DIR / "research_store" / "price_action"
              / "h058_stage0")
    if output.exists():
        print(f"refusing to overwrite a frozen bundle at {output}")
        return 1

    # Charts are drawn from session-aligned adjusted bars, never from the
    # as-of-open screening panel: that panel carries date D's opening print
    # beside date D-1's high/low/close, so its four price columns are not one
    # candle and its `open` is the future at this decision point.
    print("loading session-aligned adjusted bars ...")
    bars = corporate_actions.load_adjusted()
    partitions = splits.assign(bars[["symbol", "date"]].copy())
    universe = fo_universe.load()

    decisions = setup_grind.eligible_decisions(
        bars, universe, partitions, partition=args.partition)
    print(f"{len(decisions):,} eligible decisions in `{args.partition}` "
          f"over {decisions['symbol'].nunique()} symbols and "
          f"{decisions['date'].nunique()} sessions")

    deck = setup_grind.build_deck(
        decisions, n_unique=args.cases, n_repeats=args.repeats, seed=args.seed)
    manifest = setup_grind.freeze_stage0_bundle(deck, bars, output)

    print(json.dumps({key: value for key, value in manifest.items()
                      if key not in ("review_schema",
                                     "execution_rules_registered_for_stage_2")},
                     indent=2))
    print(f"\nfrozen at {output}")
    print("open the app, pick the 'Mark your own setups' queue, and grind.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
