"""`alpha_eval` — Standard alpha evaluation suite and canonical backtest (PLAN.md §5.8–§5.10).

The battery applied identically to every candidate signal:
- `diagnostics`: Rank IC, quantile profiles, monotonicity, turnover, persistence, session-clustered inference.
- `neutralisation`: Factor projection against market beta, sector, size, volatility, momentum (and H038 check).
- `backtest`: Canonical top-K equal-weighted backtest charging cash for uninvested days.
- `report`: Unified `evaluate_signal()` emitting standard alpha fingerprints.
"""
from __future__ import annotations

from . import backtest, diagnostics, neutralisation, report
from .report import evaluate_signal

__all__ = [
    "backtest",
    "diagnostics",
    "evaluate_signal",
    "neutralisation",
    "report",
]
