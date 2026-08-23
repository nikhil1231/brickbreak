"""Capability-separated firewall zones (PLAN.md §6 and Stage X).

Zones:
- RESEARCH: may see dossiers, source documents, raw PIT facts, predictor distributions.
  May NOT see forward labels and target-case outcomes.
- EVALUATION_VAULT: may see frozen contracts, signals/decisions, outcome labels, scoring code.
  May NOT see generative research tools and mutable prompts.
- EVIDENCE_SINK: may see preregistered reports, failure classes, permitted aggregates.
  May NOT see arbitrary slices or follow-up queries into the same result.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

import pandas as pd

from ..alpha_eval.guards import LeakageGuardError, assert_no_forward_labels

logger = logging.getLogger(__name__)


class FirewallZone(str, Enum):
    RESEARCH = "research"
    EVALUATION_VAULT = "evaluation_vault"
    EVIDENCE_SINK = "evidence_sink"


class FirewallAccessError(PermissionError):
    pass


# Prohibited column patterns per zone
FORBIDDEN_ZONE_COLUMNS: dict[FirewallZone, tuple[str, ...]] = {
    FirewallZone.RESEARCH: (
        "fwd_ret_", "excess_ret_", "future_", "target_outcome", "forward_label",
    ),
    FirewallZone.EVALUATION_VAULT: (),
    FirewallZone.EVIDENCE_SINK: (
        "raw_individual_trade", "unmasked_target_label",
    ),
}


def assert_zone_frame_access(df: pd.DataFrame, zone: FirewallZone, context: str = "") -> None:
    """Ensure a dataframe respects the capability boundary of the caller's zone."""
    if not isinstance(df, pd.DataFrame):
        return

    forbidden_prefixes = FORBIDDEN_ZONE_COLUMNS.get(zone, ())
    if not forbidden_prefixes:
        return

    found = []
    for col in df.columns:
        col_str = str(col)
        if any(col_str.startswith(p) for p in forbidden_prefixes):
            found.append(col_str)

    if found:
        raise FirewallAccessError(
            f"Zone {zone.value!r} attempted to access forbidden outcome columns {found!r} "
            f"in context {context!r} (PLAN.md §6). Research zone cannot view forward outcomes."
        )


def enforce_research_guard(df: pd.DataFrame, context: str = "") -> None:
    """Helper for research zone boundary."""
    assert_zone_frame_access(df, FirewallZone.RESEARCH, context=context)
    assert_no_forward_labels(df, context=context)
