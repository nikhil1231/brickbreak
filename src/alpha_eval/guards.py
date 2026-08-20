"""Guards that run where a signal is actually scored.

The catalogue already knows which features may be ranked on and which may only
stratify — `size_tier_rank` is present-day index membership applied to 2021
rows (H030), and index membership is assigned on market cap, i.e. on the
returns being scored. That guard was built, tested and displayed in the UI, and
then never called from `evaluate_signal`, so passing `signal_col="size_tier_rank"`
returned a complete fingerprint with no complaint.

A guard that is not on the path it guards is documentation. This module is the
call site.
"""
from __future__ import annotations

import logging

from ..research_data.catalogue import DEFAULT as CATALOGUE

logger = logging.getLogger(__name__)


class ScoringGuardError(RuntimeError):
    pass


def assert_scorable(signal_col: str, allow_unscorable: bool = False) -> None:
    """Refuse to score a feature the catalogue marks stratification-only.

    Columns the catalogue does not know — a residual, a composite, anything an
    experiment just built — pass through. The catalogue is a register of known
    hazards, not a whitelist, and requiring registration before a signal could
    be tested would make the lab useless.

    `allow_unscorable=True` is the deliberate escape hatch, and it logs. Use it
    to *measure* a blocked feature's exposure (that is a legitimate diagnostic),
    never to promote one.
    """
    if signal_col not in CATALOGUE:
        return

    spec = CATALOGUE[signal_col]
    if CATALOGUE.scorable(signal_col):
        return

    reason = (spec.known_caveats or "").strip() or "not point-in-time"
    msg = (f"{signal_col!r} may not be scored: {reason}. "
           f"Non-PIT features may stratify a result, never rank one "
           f"(AGENTS.md). Pass allow_unscorable=True to measure its exposure "
           f"deliberately.")
    if allow_unscorable:
        logger.warning("SCORING GUARD OVERRIDDEN — %s", msg)
        return
    raise ScoringGuardError(msg)
