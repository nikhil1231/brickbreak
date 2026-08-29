"""Sync NSE's daily all-index close archive (the buy-and-hold hurdle)."""
from __future__ import annotations

import sys
from datetime import date

from src.research_data.sources import nse_index_close as ic


def main() -> int:
    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2020, 1, 1)
    end = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date(2026, 8, 28)
    print(ic.sync(start, end, throttle=0.25, workers=2), flush=True)
    print("consolidated ->", ic.consolidate(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
