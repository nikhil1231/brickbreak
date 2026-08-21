"""The subscription decider — the same judgement, through an installed CLI.

Reuses `runner.agent`, which already solves authentication, billing, timeouts
and result normalisation for the signal path. Costs nothing per call under a
subscription, which makes it the right tool while a prompt is being worked on.
It is serial and slow, so it is the wrong tool for five hundred cases.

SEALED, WHICH IS THE ENTIRE DIFFICULTY
`runner.agent.run_agent` exists to give a coding agent a writable worktree with
Read, Write, Edit, Bash, Glob and Grep. That is exactly right for authoring a
signal and exactly wrong here. A judge with Bash is a judge that can open
`daily_bars_adj.parquet` and read the outcome it is about to be scored on — and
it would not have to intend anything for the result to be worthless, because a
model asked to reason about a stock will reasonably reach for the data if the
data is reachable.

So this path passes `allowed_tools=()` and runs in a scratch directory that
contains nothing. The case travels inside the prompt. There is no repository in
front of the judge, and nothing for a tool to read even if one existed.

The seal is asserted by `tests/test_decider.py`, not just intended here.
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Callable

from ...runner import agent
from .. import prompt as prompt_mod
from ..case import Case
from ..decision import AI_DECIDER, Decision, from_payload

logger = logging.getLogger(__name__)

# Empty on purpose, and load-bearing. See the module docstring.
NO_TOOLS: tuple[str, ...] = ()

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def available(provider: str = "claude") -> bool:
    return agent.available(provider=provider)


def _schema_instruction() -> str:
    """The CLI has no `output_config`, so the schema is asked for in words."""
    return (
        "\n\nReturn ONLY a single JSON object, with no prose around it and no "
        "code fence. It must have exactly these keys:\n"
        + json.dumps(
            {k: v.get("description", v.get("type", ""))
             for k, v in prompt_mod.DECISION_SCHEMA["properties"].items()},
            indent=2)
        + f"\n\n`action` must be one of TAKE, SKIP, WATCH. `confidence` is a "
          f"number from 0 to 1. `tags` must be drawn from: "
          f"{', '.join(prompt_mod.REASONING_TAGS)}."
    )


def _parse(text: str) -> dict:
    """Recover the object from whatever the CLI wrapped around it."""
    match = _JSON_BLOCK.search(text or "")
    if not match:
        raise ValueError("no JSON object in the reply")
    return json.loads(match.group(0))


def decide_one(case: Case, model: str | None = None, horizon: int = 10,
               provider: str = "claude", timeout_s: int = 300,
               replay_id: str = "RPL") -> Decision:
    common = dict(
        case_id=case.case_id, replay_id=replay_id, decider=AI_DECIDER,
        model=model or f"{provider}-cli-default",
        prompt_version=prompt_mod.PROMPT_VERSION,
        prompt_hash=prompt_mod.PROMPT_HASH, case_hash=case.case_hash,
        horizon=horizon,
    )
    text = (prompt_mod.SYSTEM_PROMPT + "\n\n---\n\n"
            + prompt_mod.user_prompt(case.render(), horizon)
            + _schema_instruction())

    # An empty directory, discarded afterwards. There is nothing here to read.
    with tempfile.TemporaryDirectory(prefix="decide_") as tmp:
        res = agent.run_agent(
            text, cwd=Path(tmp), timeout_s=timeout_s, max_turns=1,
            allowed_tools=NO_TOOLS, model=model, provider=provider)

    if not res.ok:
        return Decision(action="SKIP", confidence=0.0,
                        error=(res.stderr or "agent reported failure")[:400],
                        **common)
    try:
        payload = _parse(res.text)
        return from_payload(payload, prompt_mod.REASONING_TAGS, **common)
    except Exception as exc:                        # noqa: BLE001 — recorded
        return Decision(action="SKIP", confidence=0.0,
                        error=f"unparseable reply: {exc}", **common)


def decide(cases: list[Case], model: str | None = None, horizon: int = 10,
           provider: str = "claude", timeout_s: int = 300,
           replay_id: str = "RPL",
           progress: Callable[[int, int], None] | None = None,
           **_ignored) -> list[Decision]:
    """Serial by construction — the CLIs hold a session per process."""
    out = []
    for i, c in enumerate(cases, 1):
        out.append(decide_one(c, model=model, horizon=horizon,
                              provider=provider, timeout_s=timeout_s,
                              replay_id=replay_id))
        if progress:
            progress(i, len(cases))
    return out
