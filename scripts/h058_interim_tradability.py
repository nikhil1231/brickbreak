#!/usr/bin/env python
"""Apply the second registered futility criterion. Prints one word.

Reads the sealed interim file rather than the market: the outcome read was paid
for by the first criterion, and this re-examines it. The estimate stays sealed
for the same reason as before -- a number printed here has reached both the
reviewer and the assistant.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core import config  # noqa: E402

FUTILITY_THRESHOLD = 0.00


def main() -> int:
    sealed = (config.METADATA_DIR / "research_store" / "price_action"
              / "h058_stage2_interim_SEALED.json")
    if not sealed.exists():
        print("no sealed interim: run scripts/h058_interim.py first")
        return 1
    report = json.loads(sealed.read_text())
    verdict = ("STOP" if report["take_mean_r"] <= FUTILITY_THRESHOLD
               else "CONTINUE")
    report["tradability_criterion"] = {
        "registered_rule": f"stop if mean R on takes <= {FUTILITY_THRESHOLD}",
        "verdict": verdict,
    }
    sealed.write_text(json.dumps(report, indent=2) + "\n")
    print(verdict)
    print(f"\n({report['pairs_resolved']} takes, net of costs. The estimate "
          "stays sealed and is deliberately not printed.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
