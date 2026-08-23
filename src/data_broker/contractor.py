"""Contract synthesis and catalogue integration (PLAN.md §5 and Stage Y).

Turns an observation probe and approval into a formal DataContract and
registers the new point-in-time features into the research_data catalogue.
"""
from __future__ import annotations

import logging
from typing import Any, Sequence

from ..contracts.data_contract import DataContract, SourceFieldDef
from .approval import ApprovalCard, ApprovalStatus
from .probe import ProbeResult

logger = logging.getLogger(__name__)


def synthesize_data_contract(probe: ProbeResult,
                             approval: ApprovalCard,
                             fields: Sequence[SourceFieldDef],
                             source_owner: str,
                             storage_path: str,
                             available_at_rule: str,
                             first_tradable_session_rule: str,
                             rate_limits: str = "5 req/s",
                             timestamp_tz: str = "Asia/Kolkata",
                             universe_depth: str = "NSE listed",
                             survivorship_policy: str = "Point-in-time daily captures",
                             entity_resolution_policy: str = "symbolchange.csv mapping",
                             maintenance_owner: str = "Data Broker"
                             ) -> DataContract:
    """Create a verified DataContract from an approved probe."""
    if approval.status not in (ApprovalStatus.AUTO_APPROVED, ApprovalStatus.APPROVED):
        raise ValueError(f"Cannot synthesize contract for unapproved source (status={approval.status.value})")

    return DataContract(
        contract_id=f"DC_{probe.source_name.upper().replace(' ', '_')[:12]}_{approval.card_id[-6:]}",
        source_name=probe.source_name,
        source_owner=source_owner,
        licence_type=approval.licence_type,
        cash_cost_usd=approval.cash_cost_usd,
        rate_limits=rate_limits,
        raw_fields=tuple(fields),
        timestamp_tz=timestamp_tz,
        publication_latency_hours=4.0 if probe.timestamp_fidelity == "exact_intraday" else 18.0,
        available_at_rule=available_at_rule,
        first_tradable_session_rule=first_tradable_session_rule,
        coverage_start=probe.usable_start_date or "2020-01-01",
        coverage_end=probe.usable_end_date or "present",
        universe_depth=universe_depth,
        survivorship_policy=survivorship_policy,
        expected_join_rate_pct=probe.join_rate_pct,
        pagination_and_caps_notes="Silent caps checked by micro-probe",
        entity_resolution_policy=entity_resolution_policy,
        unlocked_families=approval.mechanisms_unlocked,
        storage_path=storage_path,
        maintenance_owner=maintenance_owner,
    )
