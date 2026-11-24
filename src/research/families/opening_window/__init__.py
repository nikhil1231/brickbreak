"""The volatility-contraction screener, the one surviving piece of the opening-window family.

The rest of the family (H001-H033: discovery, behaviour, shotgun, holdout) was
removed after it failed out of sample; it lives at git tag `pre-compression`.
"""
from __future__ import annotations

from . import screener

__all__ = ["screener"]
