"""Ways of getting a judgement out of a model.

Two, deliberately. `api` is the workhorse — concurrent, batched, and the only
one that makes a 500-case replay a matter of minutes. `cli` reuses the
subscription already installed for the signal path, which costs nothing per
call and is the right choice for a handful of cases while a prompt is being
worked on.

Both must satisfy the same contract, and the contract is severe: **the decider
gets the case and nothing else.** No tools, no filesystem, no network, no
repository. A judge that could open a parquet file could read the outcome it is
being scored against, and would not have to do so deliberately for the result
to be worthless.
"""
from __future__ import annotations

__all__ = ["api", "cli"]
