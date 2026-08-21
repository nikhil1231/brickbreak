"""Configured dispatch rate limiter and partition gate (PLAN.md §5, §5.1).

Enforces strict dispatch rate limiting per partition per period:
- Five explorations per week against `train`
- Zero against `validation` until a signal clears `train`
- Zero against `test` until a signal clears `validation`
- Unlimited against `forward`

Attempting to dispatch beyond the rate limit is REFUSED with an explicit error,
not warned about.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..persistence import store
from .spec import ExperimentSpec

logger = logging.getLogger(__name__)


class DispatchGateRefusalError(RuntimeError):
    """Raised when dispatching exceeds the configured rate limit or policy."""
    pass


class DispatchRateLimitExceededError(DispatchGateRefusalError):
    """Raised when dispatch rate limit for a partition period is exceeded."""
    pass


@dataclass(frozen=True)
class RateLimitPolicy:
    max_dispatches: int | None    # None means unlimited
    period_days: int = 7


DEFAULT_POLICIES: dict[str, RateLimitPolicy] = {
    "train": RateLimitPolicy(max_dispatches=5, period_days=7),
    "validation": RateLimitPolicy(max_dispatches=0, period_days=7),
    "test": RateLimitPolicy(max_dispatches=0, period_days=7),
    "forward": RateLimitPolicy(max_dispatches=None, period_days=7),
}


def _parse_exploration_time(exp) -> datetime | None:
    """Extract timestamp from exploration record or ID."""
    # Try parsing from ID: EXP_YYYYMMDD_HHMMSS
    if exp.id.startswith("EXP_") and len(exp.id) >= 19:
        try:
            return datetime.strptime(exp.id[4:19], "%Y%m%d_%H%M%S")
        except ValueError:
            pass
    # Fallback to created_date YYYY-MM-DD
    if getattr(exp, "created_date", None):
        try:
            return datetime.strptime(exp.created_date, "%Y-%m-%d")
        except ValueError:
            pass
    return None


def count_recent_dispatches(
    partition: str,
    period_days: int = 7,
    as_of: datetime | None = None,
) -> int:
    """Count non-void explorations dispatched against partition in the last `period_days`."""
    now = as_of or datetime.now()
    cutoff = now - timedelta(days=period_days)

    count = 0
    for exp in store.list_explorations(include_voided=False):
        spec = exp.spec or {}
        if spec.get("partition") != partition:
            continue
        exp_time = _parse_exploration_time(exp)
        if exp_time and exp_time >= cutoff:
            count += 1
    return count


def check_dispatch_allowance(
    partition: str,
    custom_policy: RateLimitPolicy | None = None,
    as_of: datetime | None = None,
) -> tuple[bool, int, int | None, str]:
    """Check whether a new exploration is allowed on `partition`.

    Returns (is_allowed, recent_count, max_allowed, reason).
    """
    policy = custom_policy or DEFAULT_POLICIES.get(partition, RateLimitPolicy(max_dispatches=5, period_days=7))

    if policy.max_dispatches is None:
        # Unlimited (e.g. forward lane)
        return True, 0, None, f"Partition '{partition}' has unlimited dispatch allowance."

    recent = count_recent_dispatches(partition, period_days=policy.period_days, as_of=as_of)

    if policy.max_dispatches == 0:
        return (
            False,
            recent,
            0,
            f"Partition '{partition}' is locked for new dispatches (max=0 per {policy.period_days}d). "
            f"Only signals that cleared prior tiers may be promoted."
        )

    if recent >= policy.max_dispatches:
        return (
            False,
            recent,
            policy.max_dispatches,
            f"Dispatch rate limit reached for partition '{partition}': {recent} dispatches "
            f"in the last {policy.period_days} days (limit is {policy.max_dispatches} per {policy.period_days}d). "
            f"Refusing dispatch to preserve sample budget (PLAN.md §5.1)."
        )

    remaining = policy.max_dispatches - recent
    return (
        True,
        recent,
        policy.max_dispatches,
        f"Allowed: {recent}/{policy.max_dispatches} dispatches used in last {policy.period_days}d ({remaining} remaining)."
    )


def enforce_dispatch_gate(
    spec: ExperimentSpec,
    custom_policy: RateLimitPolicy | None = None,
    as_of: datetime | None = None,
) -> None:
    """Enforces the dispatch gate. Raises DispatchRateLimitExceededError if rate limit is reached."""
    allowed, recent, max_allowed, reason = check_dispatch_allowance(
        spec.partition, custom_policy=custom_policy, as_of=as_of
    )
    if not allowed:
        raise DispatchRateLimitExceededError(reason)


def gate_status(period_days: int = 7) -> dict[str, Any]:
    """Summary of dispatch rate utilization across all partitions."""
    out = {}
    for part, policy in DEFAULT_POLICIES.items():
        allowed, recent, max_limit, reason = check_dispatch_allowance(part)
        out[part] = {
            "dispatches_in_period": recent,
            "max_dispatches": max_limit,
            "period_days": policy.period_days,
            "allowed": allowed,
            "status_text": reason,
        }
    return out
