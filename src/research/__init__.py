"""Hypothesis-family research implementations.

This package holds *families* — concrete, strategy-specific research lines. It
is deliberately a leaf of the architecture rather than a part of it. Nothing in
`src/discretionary`, `src/alpha_eval`, `src/research_data` or `src/persistence`
may import from here; the dependency runs one way, and
`tests/test_architecture.py` enforces it.

A family is where a particular belief about the market lives. The lab is what
tests beliefs, and it must not be shaped by any one of them.

See `src/research/families/` for the families themselves.
"""
from __future__ import annotations

__all__ = ["families"]
