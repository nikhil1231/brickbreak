#!/usr/bin/env python
"""Score a frozen H058 Stage 0 pass against its registered bar.

Reads no outcome and cannot: the bundle contains no forward bar. It answers two
questions and one decision -- is the reviewer's take/skip judgement
reproducible, what does a data point cost, and does Stage 2 open.

    python scripts/h058_stage0_report.py --annotator owner

The verdict comes from the acceptance bar frozen inside the manifest, not from
the module constant, so editing the bar afterwards cannot change how a pass
already frozen is judged.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from src.core import config  # noqa: E402
from src.research.families import setup_grind  # noqa: E402

VERDICT_TEXT = {
    "proceed_full": "PROCEED — Stage 2 opens at the full 0.20R size",
    "proceed_reduced": "PROCEED, REDUCED — Stage 2 opens only at the 0.30R size",
    "stop": "STOP — the programme ends here",
    "redraw_deck": "REDRAW — the deck, not the reviewer, is the problem",
    "inconclusive": "INCONCLUSIVE — the pass cannot be scored",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotator", default="owner")
    parser.add_argument("--bundle", type=Path, default=None)
    args = parser.parse_args()

    bundle = args.bundle or (config.METADATA_DIR / "research_store"
                             / "price_action" / "h058_stage0")
    manifest = json.loads((bundle / "manifest.json").read_text())
    private = [json.loads(line) for line
               in (bundle / "cases_private.jsonl").read_text().splitlines() if line]
    with (bundle / "annotations.csv").open() as handle:
        annotations = pd.DataFrame(list(csv.DictReader(handle)))
    if annotations.empty:
        print("No frozen pass yet. Finalize the pass in the app first —\n"
              "a draft is not data, and only a complete pass is scored.")
        return 1

    for column in ("entry_atr", "stop_atr", "target_atr", "conviction",
                   "seconds_elapsed"):
        if column in annotations:
            annotations[column] = pd.to_numeric(annotations[column],
                                                errors="coerce")

    report = setup_grind.stage0_report(
        annotations, manifest, private, annotator=args.annotator)

    take = report["take_rate"]
    consistency = report["consistency"]
    pace = report["pace"]
    print(f"\n=== H058 STAGE 0 — {args.annotator} ===")
    print(f"cases reviewed        {report['cases_reviewed']}")
    print(f"take rate             {take['rate']:.1%} "
          f"({take['takes']}/{take['first_showings']} first showings, "
          f"95% {take['wilson_95'][0]:.1%}-{take['wilson_95'][1]:.1%})")
    kappa = consistency["take_skip_kappa"]
    print(f"test-retest kappa     "
          f"{'undefined' if kappa is None else f'{kappa:+.3f}'} "
          f"over {consistency['pairs']} repeated charts "
          f"(raw agreement {consistency['raw_agreement']})")
    if consistency["direction_agreement"] is not None:
        print(f"direction agreement   {consistency['direction_agreement']:.1%} "
              f"on {consistency['both_taken_pairs']} pairs taken twice")
    print(f"pace                  {pace['median_seconds_per_skip']}s per skip, "
          f"{pace['median_seconds_per_take']}s per take, "
          f"{pace['total_minutes']} minutes total")
    if report["geometry_violations"]:
        print(f"geometry violations   {len(report['geometry_violations'])} "
              "(a stop on the wrong side of an entry is a pairing bug)")

    print(f"\nVERDICT: {VERDICT_TEXT.get(report['verdict'], report['verdict'])}")
    print(f"  {report['verdict_reason']}")
    print(f"  {consistency['recall_caveat']}")

    if report["stage_2_sizing"]:
        print("\nWhat Stage 2 costs at YOUR measured rate and pace:")
        print(f"  {'edge (R)':>9} {'takes':>7} {'charts':>8} {'hours':>7}")
        for row in report["stage_2_sizing"]:
            print(f"  {row['detectable_edge_r']:>9.2f} {row['takes_needed']:>7} "
                  f"{row['charts_needed']:>8} {row['hours']:>7.1f}")
        print(f"  (assumes per-trade dispersion of "
              f"{report['sizing_assumption']['sigma_r']}R; every hour above "
              "moves with its square)")

    destination = (config.METADATA_DIR / "research_store" / "price_action"
                   / "h058_stage0_report.json")
    destination.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"\nwritten to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
