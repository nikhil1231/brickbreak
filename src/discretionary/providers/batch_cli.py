"""Batch subscription judge for compact event cases.

The ordinary CLI backend deliberately sends one case per process. That is a
good default for large chart cases and an unnecessarily slow one for H064's
compact disclosure cases. This backend freezes groups of twenty consecutive
cases into one prompt, keeps the same empty-directory/no-tools seal, and
requires one keyed JSON decision for every case. The batch composition is
deterministic, so it is part of the case-set/prompt identity rather than a
runtime convenience that can drift.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from ...runner import agent
from .. import prompt as prompt_mod
from ..case import Case
from ..decision import AI_DECIDER, Decision, from_payload

BATCH_SIZE = 20
MAX_WORKERS = 4
PROMPT_VERSION = "announcement_batch_v1"
NO_TOOLS: tuple[str, ...] = ()

EVENT_INSTRUCTION = """
The cases below are corporate disclosures in relatively low-capacity NSE cash
equities. Judge the economic substance, not whether the wording sounds upbeat.
Distinguish a binding and material event from a memorandum, routine update,
promotional repetition or adverse balance-sheet/governance information. You do
not know market capitalisation, revenue or valuation unless the case states it;
do not invent them. The event was public before the shown session's open, so
assume any obvious headline reaction may already be in that opening print.

Compare the cases in this batch. TAKE only cases you believe can beat the
equal-weighted NSE market over about 20 sessions after costs. There is no quota:
zero or several TAKES are valid. WATCH is not a position.
""".strip()

OUTPUT_INSTRUCTION = """
Return ONLY one JSON array, with exactly one object per supplied case and no
markdown. Each object must contain: case_id, facts (at most 3 short strings),
unusual, thesis, competing_explanation, action (TAKE/SKIP/WATCH), confidence
(0 to 1), tags (from the allowed list), and rationale (at most 2 sentences).
Do not omit hard cases. Preserve every case_id exactly.
""".strip()

PROMPT_HASH = hashlib.sha256(
    (prompt_mod.SYSTEM_PROMPT + EVENT_INSTRUCTION + OUTPUT_INSTRUCTION
     + str(BATCH_SIZE)).encode("utf-8")
).hexdigest()[:16]


def _provider_model(value: str | None) -> tuple[str, str | None]:
    raw = (value or "codex:").strip()
    if ":" in raw:
        provider, model = raw.split(":", 1)
        provider = provider.strip().lower()
        if provider in ("codex", "claude", "antigravity"):
            return provider, model.strip() or None
    # A bare model retains the historical CLI default (Claude).
    return "claude", raw or None


def _extract_array(text: str) -> list[dict]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text or "", re.DOTALL)
        if not match:
            raise ValueError("no JSON array in reply")
        value = json.loads(match.group(0))
    if not isinstance(value, list):
        raise ValueError("reply is not a JSON array")
    return [item for item in value if isinstance(item, dict)]


def _failure(case: Case, replay_id: str, model: str, message: str,
             horizon: int) -> Decision:
    return Decision(
        case_id=case.case_id, replay_id=replay_id, decider=AI_DECIDER,
        action="SKIP", confidence=0.0, error=message[:400], model=model,
        prompt_version=PROMPT_VERSION, prompt_hash=PROMPT_HASH,
        case_hash=case.case_hash, horizon=horizon)


def _judge_batch(cases: list[Case], model: str | None, horizon: int,
                 replay_id: str, timeout_s: int) -> list[Decision]:
    provider, provider_model = _provider_model(model)
    model_id = f"{provider}:{provider_model or '<default>'}"
    rendered = "\n\n".join(
        f"===== CASE {case.case_id} =====\n{case.render()}" for case in cases)
    prompt = (
        prompt_mod.SYSTEM_PROMPT + "\n\n" + EVENT_INSTRUCTION + "\n\n"
        + f"Decision horizon: about {horizon} trading sessions.\n\n"
        + rendered + "\n\n" + OUTPUT_INSTRUCTION + "\nAllowed tags: "
        + ", ".join(prompt_mod.REASONING_TAGS))
    with tempfile.TemporaryDirectory(prefix="batch_decide_") as tmp:
        result = agent.run_agent(
            prompt, cwd=Path(tmp), timeout_s=timeout_s, max_turns=1,
            allowed_tools=NO_TOOLS, model=provider_model, provider=provider)
    if not result.ok:
        message = result.stderr or "batch agent reported failure"
        return [_failure(c, replay_id, model_id, message, horizon) for c in cases]
    try:
        payloads = _extract_array(result.text)
    except Exception as exc:  # noqa: BLE001 - failure is recorded per case
        return [_failure(c, replay_id, model_id,
                         f"unparseable batch reply: {exc}", horizon) for c in cases]

    by_id = {str(item.get("case_id", "")): item for item in payloads}
    out = []
    for case in cases:
        payload = by_id.get(case.case_id)
        if payload is None:
            out.append(_failure(case, replay_id, model_id,
                                "case missing from batch reply", horizon))
            continue
        try:
            out.append(from_payload(
                payload, prompt_mod.REASONING_TAGS,
                case_id=case.case_id, replay_id=replay_id, decider=AI_DECIDER,
                model=model_id, prompt_version=PROMPT_VERSION,
                prompt_hash=PROMPT_HASH, case_hash=case.case_hash,
                horizon=horizon))
        except Exception as exc:  # noqa: BLE001 - preserve the population
            out.append(_failure(case, replay_id, model_id,
                                f"invalid decision payload: {exc}", horizon))
    return out


def decide(cases: list[Case], model: str | None = None, horizon: int = 20,
           replay_id: str = "RPL", timeout_s: int = 600,
           progress: Callable[[int, int], None] | None = None,
           **_ignored) -> list[Decision]:
    """Judge deterministic consecutive batches, up to four concurrently."""
    batches = [cases[i:i + BATCH_SIZE] for i in range(0, len(cases), BATCH_SIZE)]
    completed: dict[int, list[Decision]] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, max(len(batches), 1))) as ex:
        futures = {
            ex.submit(_judge_batch, batch, model, horizon, replay_id, timeout_s): i
            for i, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            i = futures[future]
            try:
                completed[i] = future.result()
            except Exception as exc:  # noqa: BLE001 - every case still counts
                completed[i] = [
                    _failure(c, replay_id, model or "", f"batch crashed: {exc}",
                             horizon)
                    for c in batches[i]]
            done += len(completed[i])
            if progress:
                progress(done, len(cases))
    return [decision for i in range(len(batches)) for decision in completed[i]]
