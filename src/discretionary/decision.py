"""A committed decision — immutable, and written before any outcome exists.

The record the whole replay turns on. Two properties make it evidence rather
than an anecdote:

**It is committed.** A decision is written to disk in the `decide` phase, and
`reveal` refuses to run unless what it finds on disk hashes to what was
committed. Nothing can revise a decision after seeing what happened next,
because the code will not let it.

**It carries its own identity.** `model`, `prompt_hash` and `case_hash` say
exactly what was asked, of what, by whom. A replay is reproducible only if all
three are pinned, and a *distinct test of the sample* is exactly a distinct
triple.

The reasoning fields are not decoration. MISSION §8 asks which kinds of
discretionary reasoning genuinely add alpha — a question that can only be
answered if the reasoning was recorded in a form that can be grouped, which is
what `tags` is for, and if inference was kept separate from fact, which is what
the three buckets are for.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

ACTIONS = ("TAKE", "SKIP", "WATCH")

# Every decision carries the name of what produced it. The AI arm and the
# baseline arms are the same object so that `evaluate` compares like with like
# and cannot accidentally compare a rich record against a thin one.
AI_DECIDER = "ai"


class DecisionError(RuntimeError):
    pass


@dataclass
class Decision:
    """One committed verdict on one case."""
    case_id: str
    replay_id: str
    decider: str                  # "ai", or the baseline's registered name
    action: str
    confidence: float

    # --- the reasoning, for MISSION §8 ---
    facts: list[str] = field(default_factory=list)
    unusual: str = ""
    inference: str = ""
    speculation: str = ""
    market_and_sector: str = ""
    thesis: str = ""
    competing_explanation: str = ""
    invalidation: str = ""
    asymmetry: str = ""
    analogue_read: str = ""
    rationale: str = ""
    tags: list[str] = field(default_factory=list)

    # --- identity, for reproducibility and for the burden count ---
    model: str = ""
    prompt_version: str = ""
    prompt_hash: str = ""
    case_hash: str = ""
    decided_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # --- optional, when the experiment asks for a tradeable decision ---
    entry: float | None = None
    stop: float | None = None
    horizon: int | None = None

    # --- provenance of the call itself ---
    error: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise DecisionError(
                f"invalid action {self.action!r}; must be one of {ACTIONS}")
        try:
            self.confidence = float(self.confidence)
        except (TypeError, ValueError):
            raise DecisionError(f"confidence must be a number, got {self.confidence!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise DecisionError(
                f"confidence {self.confidence} is outside [0, 1]. It is a "
                f"probability that this decision beats the market, and it is "
                f"scored for calibration — a number outside the interval "
                f"cannot be.")

    @property
    def took(self) -> bool:
        """TAKE is a position. WATCH is not — it is an explicit non-position.

        Folding WATCH into TAKE would inflate the take rate with decisions that
        said, in words, that they were not actionable yet.
        """
        return self.action == "TAKE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Decision":
        return cls(**d)


def _as_list(value: Any) -> list[str]:
    """Coerce a field the schema declares as an array.

    A string is wrapped, not iterated. `[str(x) for x in "Over..."]` yields
    `['O', 'v', 'e', ...]` — a silent corruption that looks like a populated
    list, survives every well-formed fixture, and only shows up when a real
    model returns a single fact as a bare string, which one did on the first
    live call.
    """
    if value is None:
        return []
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [str(value)]


def from_payload(payload: dict[str, Any], allowed_tags: tuple[str, ...],
                 **identity: Any) -> Decision:
    """Build a Decision from a model's JSON reply.

    Shared by both providers on purpose: the coercion rules are where the
    silent corruptions live, and two copies of them drift.
    """
    def _text(key: str) -> str:
        v = payload.get(key, "")
        return "" if v is None else str(v).strip()

    return Decision(
        action=str(payload.get("action", "SKIP")).strip().upper(),
        confidence=float(payload.get("confidence", 0.0) or 0.0),
        facts=_as_list(payload.get("facts")),
        unusual=_text("unusual"),
        inference=_text("inference"),
        speculation=_text("speculation"),
        market_and_sector=_text("market_and_sector"),
        thesis=_text("thesis"),
        competing_explanation=_text("competing_explanation"),
        invalidation=_text("invalidation"),
        asymmetry=_text("asymmetry"),
        analogue_read=_text("analogue_read"),
        rationale=_text("rationale"),
        # A tag outside the vocabulary would silently create a new group in the
        # MISSION section 8 analysis, so it is dropped rather than kept.
        tags=[t for t in _as_list(payload.get("tags")) if t in allowed_tags],
        **identity)


def to_jsonl(decisions: list[Decision]) -> str:
    return "".join(json.dumps(d.to_dict(), sort_keys=True, default=str) + "\n"
                   for d in decisions)


def from_jsonl(text: str) -> list[Decision]:
    return [Decision.from_dict(json.loads(line))
            for line in text.splitlines() if line.strip()]


def commit_hash(decisions: list[Decision]) -> str:
    """The seal `reveal` checks before it will look at an outcome.

    Over the fields that constitute the verdict, not over the record: the
    timestamp and the token counts are provenance and may legitimately differ
    between a run and its reload, while the action, the confidence and the case
    it was made against may not.
    """
    h = hashlib.sha256()
    for d in sorted(decisions, key=lambda x: (x.decider, x.case_id)):
        h.update(f"{d.decider}|{d.case_id}|{d.action}|{d.confidence:.6f}|"
                 f"{d.case_hash}|{d.model}|{d.prompt_hash}".encode())
    return h.hexdigest()[:16]
