#!/usr/bin/env python
"""Freeze the H058 Stage 2 deck — the one scored read of `test`.

Registered before it exists: the statistic, its control, the bar, the seven
splits and the multiplicity rule all live in `setup_grind.ANALYSIS_PLAN` and are
copied into this bundle's manifest. Building the deck reads no outcome; only the
resolver does, once, later.

    python scripts/build_h058_stage2.py [--cases 1650] [--repeats 40]

Refuses to overwrite an existing bundle.
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
    parser.add_argument("--cases", type=int, default=1650,
                        help="distinct decisions; 1650 sizes the median splits")
    parser.add_argument("--repeats", type=int, default=40,
                        help="drift check across a multi-evening grind")
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument("--partition", default="test")
    args = parser.parse_args()

    output = (config.METADATA_DIR / "research_store" / "price_action"
              / "h058_stage2")
    if output.exists():
        print(f"refusing to overwrite a frozen bundle at {output}")
        return 1

    print("loading session-aligned adjusted bars ...")
    bars = corporate_actions.load_adjusted()
    partitions = splits.assign(bars[["symbol", "date"]].copy())
    universe = fo_universe.load()

    decisions = setup_grind.eligible_decisions(
        bars, universe, partitions, partition=args.partition)
    print(f"{len(decisions):,} eligible decisions in `{args.partition}` over "
          f"{decisions['symbol'].nunique()} symbols and "
          f"{decisions['date'].nunique()} sessions")

    deck = setup_grind.build_deck(
        decisions, n_unique=args.cases, n_repeats=args.repeats,
        max_per_symbol=12, max_per_session=8, seed=args.seed)
    per_session = deck.groupby("date").size()
    print(f"deck: {len(deck)} charts over {deck['date'].nunique()} sessions "
          f"and {deck['symbol'].nunique()} symbols "
          f"({per_session.median():.0f} per session, max {per_session.max()})")

    manifest = setup_grind.freeze_stage0_bundle(
        deck, bars, output, stage="stage_2", partition=args.partition)
    print(json.dumps({k: v for k, v in manifest.items()
                      if k not in ("review_schema", "acceptance_bar",
                                   "execution_rules_registered_for_stage_2")},
                     indent=2))
    print(f"\nfrozen at {output}")
    print("open the app, pick 'Mark your own setups — the real run', and grind.")
    print("NOTHING here has read an outcome. The resolver is a separate, "
          "one-shot step.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
