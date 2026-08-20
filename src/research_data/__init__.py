"""`research_data` — the only door to market data.

Every failure this project has had was a data-layer failure: selecting on the
entry day's own close (H015), a lookahead hiding in a denominator, a
present-day index-membership snapshot applied to 2021 rows (H030), and a
feature that read the interval to the *next* tick. None of them were caught by
being careful. They were caught, eventually, by tests — and three of them
entered through ad-hoc parquet reads scattered across a dozen modules.

So this package owns access. Point-in-time features, universes, adjusted and
raw prices, benchmarks, forward labels, the feature catalogue and the dataset
splits all live behind it, and nothing outside it opens a data file. If
something is missing, it is added here rather than worked around.

See `PLAN.md` §5.1-5.4 for the architecture this implements and `AGENTS.md`
for the rules that survive from the single-strategy era.

Built so far:
- `splits` — versioned, purged, quarter-level dataset partitions.
"""
from __future__ import annotations

from . import splits

__all__ = ["splits"]
