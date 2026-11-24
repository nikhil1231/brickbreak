"""Concrete hypothesis families.

Only the opening-window screener remains. Every other family (opening-window
discovery, resilience, wheel, covered-call, bulk-deals, setup-grind, ...) was
rejected and removed; the code is at git tag `pre-compression`, and the
measurements are in HYPOTHESES.md and FINDINGS.md.
"""
from __future__ import annotations

__all__ = ["opening_window"]
