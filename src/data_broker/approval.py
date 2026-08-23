"""Source acquisition approval cards (PLAN.md §5 and Stage Y).

Free and reversible probes may run automatically. Anything paid, licence-sensitive
or operationally material stops at a priced approval card.
Default proprietary-data cash budget is $0.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ..core import config


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    AUTO_APPROVED = "auto_approved"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ApprovalCard:
    card_id: str
    source_name: str
    licence_type: str
    cash_cost_usd: float
    engineering_hours_estimate: float
    mechanisms_unlocked: tuple[str, ...]
    independent_blocks_added: int
    roi_priority_score: float
    status: ApprovalStatus
    review_notes: str
    created_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "source_name": self.source_name,
            "licence_type": self.licence_type,
            "cash_cost_usd": self.cash_cost_usd,
            "engineering_hours_estimate": self.engineering_hours_estimate,
            "mechanisms_unlocked": list(self.mechanisms_unlocked),
            "independent_blocks_added": self.independent_blocks_added,
            "roi_priority_score": self.roi_priority_score,
            "status": self.status.value,
            "review_notes": self.review_notes,
            "created_at": self.created_at,
        }


def compute_data_roi_score(independent_blocks: int,
                           mechanisms_count: int,
                           reuse_value: float = 1.0,
                           orthogonality: float = 1.0,
                           cash_cost_usd: float = 0.0,
                           eng_hours: float = 2.0,
                           pit_risk_penalty: float = 1.0
                           ) -> float:
    """Calculate the data acquisition score defined in PLAN.md §5."""
    numerator = max(1, independent_blocks) * max(1, mechanisms_count) * reuse_value * orthogonality
    denominator = (cash_cost_usd * 0.1) + eng_hours + pit_risk_penalty
    return round(float(numerator / max(denominator, 0.1)), 2)


def create_approval_card(source_name: str,
                         licence_type: str,
                         cash_cost_usd: float,
                         engineering_hours: float,
                         mechanisms_unlocked: tuple[str, ...],
                         independent_blocks_added: int,
                         max_auto_cash_usd: float = 0.0
                         ) -> ApprovalCard:
    """Generate an approval card for a proposed data source."""
    roi = compute_data_roi_score(
        independent_blocks=independent_blocks_added,
        mechanisms_count=len(mechanisms_unlocked),
        cash_cost_usd=cash_cost_usd,
        eng_hours=engineering_hours,
    )

    if cash_cost_usd <= max_auto_cash_usd and licence_type in ("public", "exchange_terms"):
        status = ApprovalStatus.AUTO_APPROVED
        notes = "Free/public source eligible for automatic acquisition."
    else:
        status = ApprovalStatus.PENDING
        notes = f"Requires human approval: cash cost ${cash_cost_usd:.2f}, licence {licence_type}."

    return ApprovalCard(
        card_id=f"APP_{datetime.now():%Y%m%d_%H%M%S}",
        source_name=source_name,
        licence_type=licence_type,
        cash_cost_usd=cash_cost_usd,
        engineering_hours_estimate=engineering_hours,
        mechanisms_unlocked=mechanisms_unlocked,
        independent_blocks_added=independent_blocks_added,
        roi_priority_score=roi,
        status=status,
        review_notes=notes,
    )
