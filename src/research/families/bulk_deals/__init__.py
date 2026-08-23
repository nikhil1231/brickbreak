"""Bulk deals: NSE's disclosure of trades above 0.5% of a company's equity.

The family exists because the dispersion gate found it: outcomes after a bulk
deal fan out 22-36% more than for size-, volatility- and liquidity-matched
names in the same session, at both a one-day and a ten-day horizon, on 17,000
events across 1,600 sessions. See FINDINGS.md, 2026-08-22.

What the gate could not see, and what `events` exists to handle, is that most
of this flow is not what the disclosure appears to describe.
"""
from __future__ import annotations

__all__ = ["events"]
