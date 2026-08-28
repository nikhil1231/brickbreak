#!/usr/bin/env python
"""Run the registered H058 futility interim. Prints one word.

The full interim statistics are written to the research store so the read is
auditable, and they are NOT printed. The registration promised the reviewer a
verdict with no estimate, no direction and no magnitude, and a number that
reaches the terminal has reached both the reviewer and the assistant.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from src.core import config  # noqa: E402
from src.research_data.pipelines import corporate_actions  # noqa: E402
from src.research.families import setup_grind_outcome as resolve  # noqa: E402

FUTILITY_THRESHOLD = 0.00
SEED = 20260828


def main() -> int:
    bundle = (config.METADATA_DIR / "research_store" / "price_action"
              / "h058_stage2")
    manifest = json.loads((bundle / "manifest.json").read_text())
    private = {r["case_id"]: r for r in
               (json.loads(l) for l in
                (bundle / "cases_private.jsonl").read_text().splitlines() if l.strip())
               if r.get("case_status") == "ready"}
    draft = json.loads((bundle / "human_drafts" / "owner.json").read_text())
    marks = pd.DataFrame([{"case_id": k, **v["values"]}
                          for k, v in draft["annotations"].items()])
    for column in ("entry_atr", "stop_atr", "target_atr", "conviction"):
        marks[column] = pd.to_numeric(marks[column], errors="coerce")

    pairs = resolve.build_pairs(marks, private, seed=SEED)
    bars = corporate_actions.load_adjusted()
    scored = resolve.resolve_pairs(pairs, private, bars)
    if scored.empty:
        print("INCONCLUSIVE — no pair could be resolved")
        return 1

    difference = scored["difference_r"]
    verdict = "STOP" if difference.mean() <= FUTILITY_THRESHOLD else "CONTINUE"

    report = {
        "stage": "H058_STAGE2_FUTILITY_INTERIM",
        "outcome_accessed": True,
        "partition": manifest["partition"],
        "registered_rule": f"stop if mean paired difference <= {FUTILITY_THRESHOLD}",
        "charts_marked": int(len(marks)),
        "pairs_resolved": int(len(scored)),
        "verdict": verdict,
        "mean_difference_r": float(difference.mean()),
        "sd_difference_r": float(difference.std()),
        "take_mean_r": float(scored["take_r"].mean()),
        "control_mean_r": float(scored["control_r"].mean()),
        "take_outcomes": scored["take_outcome"].value_counts().to_dict(),
        "control_outcomes": scored["control_outcome"].value_counts().to_dict(),
    }
    destination = (config.METADATA_DIR / "research_store" / "price_action"
                   / "h058_stage2_interim_SEALED.json")
    destination.write_text(json.dumps(report, indent=2) + "\n")

    print(verdict)
    print(f"\n({len(scored)} pairs resolved. The estimate is sealed at "
          f"{destination.name} and is deliberately not printed.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
