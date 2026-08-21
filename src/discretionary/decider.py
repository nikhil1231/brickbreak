"""Provider dispatch — one entry point, two backends, one contract.

The contract is the thing worth stating, because it is what makes a replay
evidence rather than a demonstration:

    a decider receives the rendered case and nothing else, and returns exactly
    one Decision per case, in order, whatever happened.

"Whatever happened" is the load-bearing clause. A call that fails, refuses, or
returns unparseable text still produces a Decision — a SKIP at zero confidence
carrying the error — because the alternative is a case set with holes in it.
Holes are not neutral: baselines see every case, so an AI arm that quietly
dropped its failures would be scored on a different, and easier, population.
`failure_summary` exists so that never passes unnoticed.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from .case import Case
from .decision import Decision
from .providers import api as api_provider
from .providers import cli as cli_provider

logger = logging.getLogger(__name__)

PROVIDERS = ("api", "cli")


class DeciderError(RuntimeError):
    pass


def default_provider() -> str:
    """The API when it can be reached, the subscription otherwise.

    Not a preference so much as arithmetic: the CLI path is serial, and five
    hundred cases at twenty seconds apiece is most of a working day.
    """
    return "api" if api_provider.available() else "cli"


def resolve(provider: str) -> str:
    provider = (provider or "auto").lower()
    if provider == "auto":
        return default_provider()
    if provider not in PROVIDERS:
        raise DeciderError(
            f"unknown decider provider {provider!r}; choose from {PROVIDERS}")
    return provider


def decide(cases: list[Case], provider: str = "auto", model: str = "",
           horizon: int = 10, replay_id: str = "RPL",
           progress: Callable[[int, int], None] | None = None,
           **kwargs: Any) -> list[Decision]:
    """Judge every case with the chosen backend."""
    provider = resolve(provider)
    if provider == "api":
        if not api_provider.available():
            raise DeciderError(api_provider.INSTALL_HINT)
        out = api_provider.decide(
            cases, model=model or api_provider.DEFAULT_MODEL, horizon=horizon,
            replay_id=replay_id, progress=progress, **kwargs)
    else:
        out = cli_provider.decide(
            cases, model=model or None, horizon=horizon, replay_id=replay_id,
            progress=progress, **kwargs)

    if len(out) != len(cases):
        raise DeciderError(
            f"the {provider} decider returned {len(out)} decisions for "
            f"{len(cases)} cases. Every case must get one, including the ones "
            f"that failed — the baselines see all of them, and an arm missing "
            f"its hard cases is scored on an easier population.")
    return out


def failure_summary(decisions: list[Decision]) -> dict[str, Any]:
    """How much of the arm is real, and why the rest is not.

    Read before the report. A replay where a fifth of the calls failed has a
    take rate that means something different from one where none did, and the
    failures are not randomly distributed — a case that breaks a parser is
    likelier to be an unusual case, which is the population under study.
    """
    failed = [d for d in decisions if d.error]
    by_kind: dict[str, int] = {}
    for d in failed:
        kind = d.error.split(":", 1)[0].strip() or "unknown"
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {
        "n": len(decisions),
        "n_failed": len(failed),
        "failed_pct": round(len(failed) / max(len(decisions), 1) * 100, 2),
        "by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
        "cache_read_tokens": sum(d.cache_read_tokens for d in decisions),
        "input_tokens": sum(d.input_tokens for d in decisions),
        "output_tokens": sum(d.output_tokens for d in decisions),
    }
