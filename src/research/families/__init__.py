"""Concrete hypothesis families.

| family | what it believes | ledger |
| --- | --- | --- |
| `opening_window` | a volatility-contraction breakout, entered in the first minutes of the session | H001-H033 |
| `resilience` | names that hold up in a market decline rebound harder | H034-H038 |

Both are **historical research lines, not the architecture**. `resilience` is
recorded as SUPERSEDED (H038: the adjusted score is algebraically beta), and the
opening-window family's 2020-2023 window is spent. They are kept because a
negative result is a result and because their measurements must stay
reproducible — not because anything new should be built in their shape.

Imported lazily: loading a family pulls in several hundred milliseconds of
pandas machinery that the lab does not need to start.
"""
from __future__ import annotations

__all__ = ["opening_window", "resilience"]
