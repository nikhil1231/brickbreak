"""The Anthropic API decider — concurrent, cached, and schema-constrained.

WHY THIS IS THE WORKHOUSE
One model call per case, five hundred cases per replay. Serially at ~20s each
that is nearly three hours; at sixteen in flight it is minutes, and a research
loop nobody waits for is a research loop that gets used.

THREE THINGS THIS GETS RIGHT THAT THE OBVIOUS IMPLEMENTATION DOES NOT

**The schema is enforced, not requested.** `output_config.format` constrains
the response rather than asking politely for JSON, so a decision cannot arrive
as prose that needs regex. That matters more here than in most places: a
parse failure is a *missing decision*, and a case set with holes in it is not
the case set that was committed.

**The frozen prompt is cached.** Render order is tools -> system -> messages,
so the system block is the prefix every case shares. It carries a cache
breakpoint and the case goes in the user turn, after it. The prefix is close to
the ~1024-token minimum, so `cache_read_tokens` is reported back and worth
watching: if it stays at zero the caching is not engaging and the prefix needs
to be longer, not the code changed.

**A failure is a recorded outcome, not a silence.** A case whose call fails
comes back as a SKIP at zero confidence carrying the error text, and
`decide()` reports the failure count. Dropping failures instead would silently
change the case set between the AI arm and the baselines, which all see every
case — and a selector that quietly declines to answer on its hard cases would
score better for it.
"""
from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .. import prompt as prompt_mod
from ..case import Case
from ..decision import AI_DECIDER, Decision, from_payload

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_CONCURRENCY = 8
DEFAULT_MAX_TOKENS = 4000

INSTALL_HINT = (
    "the anthropic SDK is not installed. Run:\n"
    "    .venv/bin/python -m pip install anthropic\n"
    "and set ANTHROPIC_API_KEY, or use --provider cli to decide through the "
    "Claude Code subscription instead.")


class ApiDeciderError(RuntimeError):
    pass


def available() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY")
                or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _client():
    try:
        import anthropic
    except ImportError as exc:
        raise ApiDeciderError(INSTALL_HINT) from exc
    return anthropic.Anthropic()


def _decide_one(client, case: Case, model: str, horizon: int, effort: str,
                max_tokens: int, replay_id: str) -> Decision:
    common = dict(
        case_id=case.case_id, replay_id=replay_id, decider=AI_DECIDER,
        model=model, prompt_version=prompt_mod.PROMPT_VERSION,
        prompt_hash=prompt_mod.PROMPT_HASH, case_hash=case.case_hash,
        horizon=horizon,
    )
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={
                "effort": effort,
                "format": {"type": "json_schema",
                           "schema": prompt_mod.DECISION_SCHEMA},
            },
            system=[{"type": "text", "text": prompt_mod.SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user",
                       "content": prompt_mod.user_prompt(case.render(), horizon)}],
        )
    except Exception as exc:                       # noqa: BLE001 — recorded
        logger.warning("case %s failed: %s", case.case_id, exc)
        return Decision(action="SKIP", confidence=0.0,
                        error=f"{type(exc).__name__}: {exc}"[:400], **common)

    usage = getattr(resp, "usage", None)
    counts = {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "cache_read_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
    }

    # A refusal is a real outcome and must not be mistaken for a SKIP the judge
    # reasoned its way to. Recorded with the reason so it can be excluded.
    if getattr(resp, "stop_reason", None) == "refusal":
        detail = getattr(resp, "stop_details", None)
        return Decision(action="SKIP", confidence=0.0,
                        error=f"refusal: {getattr(detail, 'category', 'unknown')}",
                        **common, **counts)

    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return Decision(action="SKIP", confidence=0.0,
                        error=f"unparseable response: {exc}", **common, **counts)

    try:
        return from_payload(payload, prompt_mod.REASONING_TAGS,
                            **common, **counts)
    except Exception as exc:                        # noqa: BLE001 — recorded
        return Decision(action="SKIP", confidence=0.0,
                        error=f"invalid decision payload: {exc}",
                        **common, **counts)


def decide(cases: list[Case], model: str = DEFAULT_MODEL, horizon: int = 10,
           effort: str = "medium", max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
           max_tokens: int = DEFAULT_MAX_TOKENS, replay_id: str = "RPL",
           progress: Callable[[int, int], None] | None = None
           ) -> list[Decision]:
    """Judge every case. Order of the returned list matches `cases`."""
    if not cases:
        return []
    client = _client()
    out: list[Decision | None] = [None] * len(cases)

    def _run(i: int) -> None:
        out[i] = _decide_one(client, cases[i], model, horizon, effort,
                             max_tokens, replay_id)
        if progress:
            progress(sum(x is not None for x in out), len(cases))

    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        list(pool.map(_run, range(len(cases))))

    done = [d for d in out if d is not None]
    failed = sum(1 for d in done if d.error)
    cached = sum(d.cache_read_tokens for d in done)
    logger.info(
        "api decider: %d decisions, %d failed, %d cache-read tokens "
        "(zero means the frozen prompt is not caching)",
        len(done), failed, cached)
    return done
