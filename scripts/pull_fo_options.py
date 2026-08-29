"""Re-fetch the NSE F&O archive keeping only option legs, with strike + type.

`data/raw/fo_bhavcopy` was written by a parser that dropped STRIKE_PR and
OPTION_TYP, so its option rows cannot be told apart. The futures rows there are
still good and still back `fo_universe.parquet`; only the option chain is
re-pulled, into its own tree.
"""
from __future__ import annotations

import sys
from datetime import date

from src.research_data.sources import nse_derivatives as nd


def main() -> int:
    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2020, 1, 1)
    end = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date(2026, 8, 28)
    stats = nd.sync(start, end, root=nd.FO_OPTIONS_DIR,
                    keep=nd.OPTION_INSTRUMENTS, throttle=0.20, workers=4)
    print("done", stats, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
