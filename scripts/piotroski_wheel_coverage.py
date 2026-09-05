"""H068 pre-outcome gate: can local PIT XBRL cover the H063 wheel universe?"""
from __future__ import annotations

import json

from src.core import config
from src.research.families.wheel.engine import prepare
from src.research_data.pipelines import option_chain as oc
from src.research_data.pipelines import piotroski

OUT = config.PROJECT_ROOT / "logs" / "wheel"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    chain = oc.load()
    tape = prepare(chain)
    cycles, stats = piotroski.archive_coverage(tape)
    cycles.to_csv(OUT / "piotroski_coverage_cycles.csv", index=False)
    (OUT / "piotroski_coverage.json").write_text(
        json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))
    if not stats["passes"]:
        print("H068 NOT TESTED: the point-in-time XBRL coverage gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
