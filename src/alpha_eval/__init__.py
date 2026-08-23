"""`alpha_eval` — Standard alpha evaluation suite and canonical backtest (the refactor plan §5.8–§5.10).

The battery applied identically to every candidate signal:
- `diagnostics`: Rank IC, quantile profiles, monotonicity, turnover, persistence, session-clustered inference.
- `neutralisation`: Factor projection against market beta, sector, size, volatility, momentum (and H038 check).
- `backtest`: Canonical top-K equal-weighted backtest charging cash for uninvested days.
- `report`: Unified `evaluate_signal()` emitting standard alpha fingerprints.
- `spread`: The pre-flight dispersion gate — does an event family fan
  outcomes out at all? A second moment, so it names no direction and
  cannot produce a claim; run it before spending cases on a family.
"""
from __future__ import annotations

from . import backtest, diagnostics, neutralisation, report, spread
from .report import evaluate_signal

__all__ = [
    "ScoringGuardError",
    "assert_scorable",
    "backtest",
    "diagnostics",
    "evaluate_signal",
    "neutralisation",
    "report",
]
