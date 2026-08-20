"""Claude Code CLI adapter — the research worker (PLAN.md §5.7).

The dashboard never executes generated shell text. It creates a job; this
module runs Claude Code headless inside that job's worktree, bounded by a
wall-clock timeout and a turn limit, and hands back a structured result.

WHAT THE WORKER IS ALLOWED TO DO
Write one file: `job/signal.py`, exposing `compute(df) -> pd.Series`. That is
the part of an experiment that genuinely needs intelligence. Everything
downstream — partitions, forward labels, the standard report, the canonical
backtest, the leakage gate — is the harness, and the harness is not
negotiable. An agent that could rewrite the evaluation could talk itself into
any answer.

BILLING
Headless `claude` uses whatever subscription the CLI is logged into, which is
the point: no API key, no separate metering.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

INSTALL_HINT = (
    "Claude Code CLI not found. Install it with:\n"
    "    npm install -g @anthropic-ai/claude-code\n"
    "then run `claude` once to log in. Set CLAUDE_CLI to an explicit path if "
    "it lives somewhere unusual."
)

# Places the CLI turns up when it is not on PATH.
_CANDIDATES = (
    "~/.claude/local/claude",
    "~/.local/bin/claude",
    "/usr/local/bin/claude",
    "/opt/homebrew/bin/claude",
)


class AgentError(RuntimeError):
    pass


class AgentNotInstalled(AgentError):
    pass


def find_cli(explicit: str | None = None) -> str:
    """Locate the Claude Code executable, or say how to get one."""
    for cand in (explicit, os.environ.get("CLAUDE_CLI")):
        if cand:
            p = Path(cand).expanduser()
            if p.exists():
                return str(p)
            raise AgentNotInstalled(f"{cand} does not exist.\n{INSTALL_HINT}")

    found = shutil.which("claude")
    if found:
        return found
    for cand in _CANDIDATES:
        p = Path(cand).expanduser()
        if p.exists():
            return str(p)
    raise AgentNotInstalled(INSTALL_HINT)


def available(explicit: str | None = None) -> bool:
    try:
        find_cli(explicit)
        return True
    except AgentNotInstalled:
        return False


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
) -> AgentResult:
    """Run Claude Code headless in `cwd` and return what it reported.

    Bounded on purpose: a job that hangs is a job that never releases its
    worktree, and a killed job is a recorded outcome rather than a silence.
    """
    exe = find_cli(cli)
    cmd = [
        exe, "-p", prompt,
        "--output-format", "json",
        "--max-turns", str(max_turns),
        "--permission-mode", "acceptEdits",
        "--allowedTools", ",".join(allowed_tools),
    ]
    if model:
        cmd += ["--model", model]

    import time
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True,
                              text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return AgentResult(ok=False, text="", returncode=-1,
                           duration_s=time.time() - t0,
                           stderr=f"timed out after {timeout_s}s")
    dur = time.time() - t0

    payload: dict = {}
    text = proc.stdout.strip()
    if text:
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                text = str(payload.get("result", text))
        except json.JSONDecodeError:
            pass          # older CLIs, or a plain-text fallback

    return AgentResult(
        ok=proc.returncode == 0 and not payload.get("is_error", False),
        text=text,
        returncode=proc.returncode,
        duration_s=dur,
        num_turns=int(payload.get("num_turns", 0) or 0),
        cost_usd=payload.get("total_cost_usd"),
        session_id=str(payload.get("session_id", "")),
        raw=payload if isinstance(payload, dict) else {},
        stderr=proc.stderr.strip(),
    )
