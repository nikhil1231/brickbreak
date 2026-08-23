"""Research lifecycle state machine (PLAN.md §2 and Stage W).

Durable states:
IDEA -> DOSSIER -> DATA_GAP | DATA_READY -> SOURCE_PROBED -> DATA_CONTRACTED
     -> PREFLIGHTED -> EXPERIMENT_CONTRACTED -> BATCH_FROZEN
     -> OUTCOME_BLIND_EXECUTED -> RULE_FROZEN -> REVEALED -> EVIDENCE -> FORWARD

No state may be skipped. Every transition records its inputs, actor/provider,
hashes, token and cash cost, outcome-exposure level and reason.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Sequence


class LifecycleState(str, Enum):
    IDEA = "IDEA"
    DOSSIER = "DOSSIER"
    DATA_GAP = "DATA_GAP"
    DATA_READY = "DATA_READY"
    SOURCE_PROBED = "SOURCE_PROBED"
    DATA_CONTRACTED = "DATA_CONTRACTED"
    PREFLIGHTED = "PREFLIGHTED"
    EXPERIMENT_CONTRACTED = "EXPERIMENT_CONTRACTED"
    BATCH_FROZEN = "BATCH_FROZEN"
    OUTCOME_BLIND_EXECUTED = "OUTCOME_BLIND_EXECUTED"
    RULE_FROZEN = "RULE_FROZEN"
    REVEALED = "REVEALED"
    EVIDENCE = "EVIDENCE"
    FORWARD = "FORWARD"


class IllegalLifecycleTransitionError(ValueError):
    pass


# Permitted directed transitions in the lifecycle graph
PERMITTED_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.IDEA: frozenset({LifecycleState.DOSSIER}),
    LifecycleState.DOSSIER: frozenset({LifecycleState.DATA_GAP, LifecycleState.DATA_READY}),
    LifecycleState.DATA_GAP: frozenset({LifecycleState.SOURCE_PROBED}),
    LifecycleState.SOURCE_PROBED: frozenset({LifecycleState.DATA_CONTRACTED, LifecycleState.DATA_GAP}),
    LifecycleState.DATA_CONTRACTED: frozenset({LifecycleState.DATA_READY}),
    LifecycleState.DATA_READY: frozenset({LifecycleState.PREFLIGHTED}),
    LifecycleState.PREFLIGHTED: frozenset({LifecycleState.EXPERIMENT_CONTRACTED}),
    LifecycleState.EXPERIMENT_CONTRACTED: frozenset({LifecycleState.BATCH_FROZEN}),
    LifecycleState.BATCH_FROZEN: frozenset({LifecycleState.OUTCOME_BLIND_EXECUTED}),
    LifecycleState.OUTCOME_BLIND_EXECUTED: frozenset({LifecycleState.RULE_FROZEN, LifecycleState.REVEALED}),
    LifecycleState.RULE_FROZEN: frozenset({LifecycleState.REVEALED}),
    LifecycleState.REVEALED: frozenset({LifecycleState.EVIDENCE}),
    LifecycleState.EVIDENCE: frozenset({LifecycleState.FORWARD}),
    LifecycleState.FORWARD: frozenset(),
}


@dataclass(frozen=True)
class StateTransitionRecord:
    from_state: LifecycleState
    to_state: LifecycleState
    entity_id: str
    actor: str
    input_hashes: tuple[str, ...]
    exposure_level: str  # "E0", "E1", "E2", "E3", "E4"
    reason: str
    tokens_spent: int = 0
    cash_cost_usd: float = 0.0
    timestamp: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "entity_id": self.entity_id,
            "actor": self.actor,
            "input_hashes": list(self.input_hashes),
            "exposure_level": self.exposure_level,
            "reason": self.reason,
            "tokens_spent": self.tokens_spent,
            "cash_cost_usd": self.cash_cost_usd,
            "timestamp": self.timestamp,
        }


def validate_transition(from_state: LifecycleState,
                        to_state: LifecycleState) -> None:
    """Verify that a transition is permitted in the research lifecycle."""
    allowed = PERMITTED_TRANSITIONS.get(from_state, frozenset())
    if to_state not in allowed:
        raise IllegalLifecycleTransitionError(
            f"Cannot transition from {from_state.value} to {to_state.value}. "
            f"Allowed next states from {from_state.value}: {[s.value for s in allowed]} "
            f"(PLAN §2). Direct execution without required lifecycle contracts is prohibited."
        )


@dataclass
class LifecycleTracker:
    """Tracks state history for one hypothesis or entity."""
    entity_id: str
    current_state: LifecycleState = LifecycleState.IDEA
    history: list[StateTransitionRecord] = field(default_factory=list)

    def transition(self,
                   to_state: LifecycleState,
                   actor: str,
                   input_hashes: Sequence[str] = (),
                   exposure_level: str = "E0",
                   reason: str = "",
                   tokens_spent: int = 0,
                   cash_cost_usd: float = 0.0) -> StateTransitionRecord:
        """Advance to next state with audit record."""
        validate_transition(self.current_state, to_state)
        if not actor.strip():
            raise ValueError("lifecycle transition actor cannot be empty")
        if not reason.strip():
            raise ValueError("lifecycle transition reason cannot be empty")
        if exposure_level not in ("E0", "E1", "E2", "E3", "E4"):
            raise ValueError("invalid lifecycle exposure_level")
        if tokens_spent < 0:
            raise ValueError("tokens_spent cannot be negative")
        if cash_cost_usd < 0:
            raise ValueError("cash_cost_usd cannot be negative")
        rec = StateTransitionRecord(
            from_state=self.current_state,
            to_state=to_state,
            entity_id=self.entity_id,
            actor=actor,
            input_hashes=tuple(input_hashes),
            exposure_level=exposure_level,
            reason=reason,
            tokens_spent=tokens_spent,
            cash_cost_usd=cash_cost_usd,
        )
        self.history.append(rec)
        self.current_state = to_state
        return rec

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "current_state": self.current_state.value,
            "history": [r.to_dict() for r in self.history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LifecycleTracker:
        """Restore a tracker while re-validating every recorded transition."""
        tracker = cls(entity_id=str(data["entity_id"]))
        for raw in data.get("history", []):
            expected_from = LifecycleState(raw["from_state"])
            if tracker.current_state != expected_from:
                raise IllegalLifecycleTransitionError(
                    f"Lifecycle history for {tracker.entity_id!r} is discontinuous: "
                    f"expected {tracker.current_state.value}, found {expected_from.value}"
                )
            tracker.transition(
                LifecycleState(raw["to_state"]),
                actor=str(raw["actor"]),
                input_hashes=tuple(raw.get("input_hashes", ())),
                exposure_level=str(raw.get("exposure_level", "E0")),
                reason=str(raw["reason"]),
                tokens_spent=int(raw.get("tokens_spent", 0)),
                cash_cost_usd=float(raw.get("cash_cost_usd", 0.0)),
            )
            # Preserve the original audit time rather than the restoration time.
            tracker.history[-1] = StateTransitionRecord(
                **{
                    **tracker.history[-1].__dict__,
                    "timestamp": str(raw.get("timestamp", tracker.history[-1].timestamp)),
                }
            )
        declared = LifecycleState(data.get("current_state", tracker.current_state.value))
        if declared != tracker.current_state:
            raise IllegalLifecycleTransitionError(
                f"Lifecycle current_state {declared.value} does not match history "
                f"ending at {tracker.current_state.value}"
            )
        return tracker
