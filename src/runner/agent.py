"""CLI-backed LLM providers for the research worker (the refactor plan §5.7).

The dashboard never executes generated shell text. It creates a job; this
module runs the selected coding agent headless inside that job's worktree,
bounded by a wall-clock timeout, and hands back a common structured result.

WHAT THE WORKER IS ALLOWED TO DO
Write one file: `job/signal.py`, exposing `compute(df) -> pd.Series`. That is
the part of an experiment that genuinely needs intelligence. Everything
downstream — partitions, forward labels, the standard report, the canonical
backtest, the leakage gate — is the harness, and the harness is not
negotiable. An agent that could rewrite the evaluation could talk itself into
any answer.

AUTH AND BILLING
Both providers reuse the authentication already held by their CLI. This keeps
credentials out of the lab and lets a local ChatGPT or Claude subscription be
the billing path.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PROVIDER = "claude"
PROVIDERS = ("claude", "codex", "antigravity")

CLAUDE_INSTALL_HINT = (
    "Claude Code CLI not found. Install it with:\n"
    "    npm install -g @anthropic-ai/claude-code\n"
    "then run `claude` once to log in. Set CLAUDE_CLI to an explicit path if "
    "it lives somewhere unusual."
)
CODEX_INSTALL_HINT = (
    "Codex CLI not found. Install it with:\n"
    "    npm install -g @openai/codex\n"
    "then run `codex login`. Set CODEX_CLI to an explicit path if it lives "
    "somewhere unusual."
)
ANTIGRAVITY_INSTALL_HINT = (
    "Antigravity CLI not found. Install it and ensure `agy` is on your PATH. "
    "Set ANTIGRAVITY_CLI to an explicit path if it lives somewhere unusual."
)

# Backward-compatible name used by the existing CLI and tests.
INSTALL_HINT = CLAUDE_INSTALL_HINT

# Places the CLI turns up when it is not on PATH.
_CLAUDE_CANDIDATES = (
    "~/.claude/local/claude",
    "~/.local/bin/claude",
    "/usr/local/bin/claude",
    "/opt/homebrew/bin/claude",
)
_CODEX_CANDIDATES = (
    "/Applications/ChatGPT.app/Contents/Resources/codex",
    "~/.local/bin/codex",
    "/usr/local/bin/codex",
    "/opt/homebrew/bin/codex",
)
_ANTIGRAVITY_CANDIDATES = (
    "~/.local/bin/agy",
    "/usr/local/bin/agy",
    "/opt/homebrew/bin/agy",
)

# Backward-compatible alias for callers that patch the old constant.
_CANDIDATES = _CLAUDE_CANDIDATES

_CLAUDE_MODELS = (
    ("", "CLI default"),
    ("sonnet", "Sonnet"),
    ("opus", "Opus"),
    ("fable", "Fable"),
)
_CODEX_FALLBACK_MODELS = (
    ("", "CLI default"),
    ("gpt-5.6-sol", "GPT-5.6-Sol"),
    ("gpt-5.6-terra", "GPT-5.6-Terra"),
    ("gpt-5.6-luna", "GPT-5.6-Luna"),
    ("gpt-5.5", "GPT-5.5"),
)
_ANTIGRAVITY_MODELS = (
    ("", "CLI default"),
    ("gemini-3.7-flash-high", "Gemini 3.7 Flash (High)"),
    ("gemini-3.7-flash-medium", "Gemini 3.7 Flash (Medium)"),
    ("gemini-3.7-flash-low", "Gemini 3.7 Flash (Low)"),
    ("gemini-3.1-pro-high", "Gemini 3.1 Pro (High)"),
    ("gemini-3.1-pro-low", "Gemini 3.1 Pro (Low)"),
)


class AgentError(RuntimeError):
    pass


class AgentNotInstalled(AgentError):
    pass


def _error_detail(value: object) -> str:
    """Flatten a provider's structured error without losing its explanation.

    Codex emits JSONL events whose ``error`` value is sometimes a nested
    object (rather than a string).  ``str(event["error"])`` hid the useful
    message behind a Python dictionary representation and, for aborted turns,
    often left the UI with only the generic abort text.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("message", "detail", "reason", "error", "code"):
            if key not in value:
                continue
            detail = _error_detail(value[key])
            if detail and detail not in parts:
                parts.append(detail)
        if parts:
            return "; ".join(parts)
        return json.dumps(value, default=str, sort_keys=True)
    if isinstance(value, (list, tuple)):
        parts = [_error_detail(item) for item in value]
        return "; ".join(part for part in parts if part)
    return str(value).strip() if value is not None else ""


def _event_error_detail(event: dict) -> str:
    """Extract a human-readable diagnostic from one Codex JSONL event."""
    details = []
    for key in ("message", "error", "detail", "reason"):
        detail = _error_detail(event.get(key))
        if detail and detail not in details:
            details.append(detail)
    item = event.get("item")
    if isinstance(item, dict):
        for key in ("message", "error", "detail", "reason"):
            detail = _error_detail(item.get(key))
            if detail and detail not in details:
                details.append(detail)
    return "; ".join(details)


def validate_provider(provider: str) -> str:
    provider = (provider or DEFAULT_PROVIDER).lower()
    if provider not in PROVIDERS:
        raise AgentError(
            f"unknown LLM provider {provider!r}; choose one of {', '.join(PROVIDERS)}")
    return provider


def install_hint(provider: str = DEFAULT_PROVIDER) -> str:
    provider = validate_provider(provider)
    if provider == "codex":
        return CODEX_INSTALL_HINT
    elif provider == "antigravity":
        return ANTIGRAVITY_INSTALL_HINT
    return CLAUDE_INSTALL_HINT


def find_cli(explicit: str | None = None,
             provider: str = DEFAULT_PROVIDER) -> str:
    """Locate one provider's CLI, or say how to install it."""
    provider = validate_provider(provider)

    if provider == "codex":
        env_name = "CODEX_CLI"
        command = "codex"
        candidates = _CODEX_CANDIDATES
    elif provider == "antigravity":
        env_name = "ANTIGRAVITY_CLI"
        command = "agy"
        candidates = _ANTIGRAVITY_CANDIDATES
    else:
        env_name = "CLAUDE_CLI"
        command = "claude"
        candidates = _CANDIDATES

    hint = install_hint(provider)

    for cand in (explicit, os.environ.get(env_name)):
        if cand:
            p = Path(cand).expanduser()
            if p.exists():
                return str(p)
            raise AgentNotInstalled(f"{cand} does not exist.\n{hint}")

    found = shutil.which(command)
    if found:
        return found
    for cand in candidates:
        p = Path(cand).expanduser()
        if p.exists():
            return str(p)
    raise AgentNotInstalled(hint)


def available(explicit: str | None = None,
              provider: str = DEFAULT_PROVIDER) -> bool:
    try:
        find_cli(explicit, provider=provider)
        return True
    except AgentNotInstalled:
        return False


def _codex_models(exe: str) -> tuple[tuple[str, str], ...]:
    """Read the bundled catalog shipped by the installed CLI, without network."""
    try:
        proc = subprocess.run(
            [exe, "debug", "models", "--bundled"], capture_output=True,
            text=True, timeout=5)
        payload = json.loads(proc.stdout)
        visible = [
            (str(m["slug"]), str(m.get("display_name") or m["slug"]))
            for m in payload.get("models", []) if m.get("visibility") == "list"
        ]
        if visible:
            return (("", "CLI default"), *visible)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, KeyError,
            TypeError):
        pass
    return _CODEX_FALLBACK_MODELS


def provider_catalog() -> dict:
    """Provider/model choices for CLI and UI surfaces."""
    out = []
    for provider, label in (("claude", "Claude Code"),
                            ("codex", "OpenAI Codex"),
                            ("antigravity", "Google Antigravity")):
        is_available = available(provider=provider)
        exe = find_cli(provider=provider) if is_available else None
        models = (_codex_models(exe) if provider == "codex" and exe
                  else _CLAUDE_MODELS if provider == "claude"
                  else _ANTIGRAVITY_MODELS if provider == "antigravity"
                  else _CODEX_FALLBACK_MODELS)
        out.append({
            "id": provider,
            "label": label,
            "available": is_available,
            "default_model": "",
            "models": [{"id": model, "label": model_label}
                       for model, model_label in models],
            "install_hint": install_hint(provider),
        })
    return {"default_provider": DEFAULT_PROVIDER, "providers": out}


@dataclass
class AgentResult:
    ok: bool
    text: str
    returncode: int
    duration_s: float
    num_turns: int = 0
    cost_usd: float | None = None
    session_id: str = ""
    raw: dict = field(default_factory=dict)
    stderr: str = ""


def run_agent(
    prompt: str,
    cwd: Path,
    timeout_s: int = 1800,
    max_turns: int = 40,
    allowed_tools: tuple[str, ...] = ("Read", "Write", "Edit", "Bash", "Glob", "Grep"),
    model: str | None = None,
    cli: str | None = None,
    provider: str = DEFAULT_PROVIDER,
    sandbox: str = "workspace-write",
) -> AgentResult:
    """Run the selected coding agent headless and normalize its result.

    Bounded on purpose: a job that hangs is a job that never releases its
    worktree, and a killed job is a recorded outcome rather than a silence.
    """
    provider = validate_provider(provider)
    exe = find_cli(cli, provider=provider)
    if provider == "claude":
        cmd = [
            exe, "-p", prompt,
            "--output-format", "json",
            "--max-turns", str(max_turns),
            "--permission-mode", "acceptEdits",
            "--allowedTools", ",".join(allowed_tools),
        ]
        if model:
            cmd += ["--model", model]
    elif provider == "antigravity":
        cmd = [
            exe, "-p", prompt,
            "--output-format", "json",
            "--sandbox",
            "--disable-slash-commands",
        ]
        if model:
            cmd += ["--model", model]
    else:
        cmd = [
            exe, "exec", "--json", "--ephemeral",
            "--ignore-user-config",
            "--skip-git-repo-check",
            "--sandbox", sandbox,
            "-c", 'approval_policy="never"',
        ]
        if model:
            cmd += ["--model", model]
        cmd.append(prompt)

    import time
    t0 = time.time()
    try:
        # Both CLIs read stdin when it is a terminal or an inherited pipe:
        # they stall three seconds waiting for input that is never coming and
        # then warn about it on stderr, which buries the message that matters
        # ("Not logged in") under one that does not.
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True,
                              text=True, timeout=timeout_s,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return AgentResult(ok=False, text="", returncode=-1,
                           duration_s=time.time() - t0,
                           stderr=f"timed out after {timeout_s}s")
    dur = time.time() - t0

    if provider in ("claude", "antigravity"):
        payload: dict = {}
        output_text = proc.stdout.strip()
        if output_text:
            try:
                parsed = json.loads(output_text)
                if isinstance(parsed, dict):
                    payload = parsed
            except json.JSONDecodeError:
                for line in output_text.splitlines():
                    line_s = line.strip()
                    if line_s.startswith("{") and line_s.endswith("}"):
                        try:
                            parsed = json.loads(line_s)
                            if isinstance(parsed, dict):
                                payload = parsed
                                break
                        except json.JSONDecodeError:
                            continue
            if payload and isinstance(payload, dict):
                response_key = "response" if provider == "antigravity" else "result"
                output_text = str(payload.get(response_key, output_text))

        status_failed = (
            provider == "antigravity"
            and bool(payload.get("status"))
            and str(payload["status"]).upper() != "SUCCESS"
        )
        is_error = (bool(payload.get("is_error", False))
                    or status_failed or proc.returncode != 0)
        err_msg = proc.stderr.strip()
        if not err_msg and is_error:
            if payload.get("error"):
                err_msg = _error_detail(payload.get("error"))
            elif payload.get("result") and payload.get("is_error"):
                err_msg = str(payload.get("result"))
            elif output_text:
                err_msg = output_text

        return AgentResult(
            ok=not is_error,
            text=output_text,
            returncode=proc.returncode,
            duration_s=dur,
            num_turns=int(payload.get("num_turns", 0) or 0),
            cost_usd=payload.get("total_cost_usd"),
            session_id=str(payload.get(
                "conversation_id" if provider == "antigravity" else "session_id", "")),
            raw=payload if isinstance(payload, dict) else {},
            stderr=err_msg,
        )

    events, parse_errors = [], []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                events.append(event)
        except json.JSONDecodeError:
            parse_errors.append(line)

    messages = [
        str(e.get("item", {}).get("text", ""))
        for e in events
        if e.get("type") == "item.completed"
        and e.get("item", {}).get("type") == "agent_message"
    ]
    session_id = next((str(e.get("thread_id", "")) for e in events
                       if e.get("type") == "thread.started"), "")
    turns = sum(e.get("type") == "turn.completed" for e in events)
    failures = [
        event for event in events
        if str(event.get("type", "")).endswith((".failed", ".error", ".aborted"))
        or event.get("type") == "error"
        or (
            isinstance(event.get("item"), dict)
            and str(event["item"].get("type", "")).endswith((".failed", ".error"))
        )
    ]
    fallback_text = "\n".join(parse_errors).strip() or proc.stdout.strip()
    output_text = messages[-1] if messages else fallback_text
    error_text = proc.stderr.strip()
    if failures and not error_text:
        error_text = "; ".join(
            detail for detail in (_event_error_detail(event) for event in failures)
            if detail)
    if not error_text and proc.returncode != 0:
        error_text = f"Codex exited with status {proc.returncode}"
    return AgentResult(
        ok=proc.returncode == 0 and not failures,
        text=output_text,
        returncode=proc.returncode,
        duration_s=dur,
        num_turns=turns,
        session_id=session_id,
        raw={"events": events},
        stderr=error_text,
    )
