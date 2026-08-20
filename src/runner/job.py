"""Research jobs: dashboard -> spec -> worktree -> Claude Code -> result (PLAN.md §5.7).

    job spec -> isolated worktree -> Claude Code CLI -> job/signal.py
             -> trusted harness -> experiment_result.json -> store

THE CONTRACT
The worker writes exactly one file, `job/signal.py`, exposing

    def compute(df: pandas.DataFrame) -> pandas.Series

and nothing else it produces is read. The signal function is the part of an
experiment that needs intelligence; partitions, forward labels, the standard
report, the canonical backtest and the leakage gate are the harness. The
harness runs **in this process, from the canonical checkout** — never from the
worktree — so an agent cannot loosen the evaluation it is being judged by,
even though it has a writable copy of the repo in front of it.

`signal.py` is imported, which means running agent-authored Python. That is
inherent to the design; the isolation is the worktree and the fact that data
is reachable only through `research_data`.
"""
from __future__ import annotations

import importlib.util
import json
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .. import config
from . import agent, worktree
from .spec import ExperimentSpec, SpecValidationError, validate_spec

JOBS_DIR = config.METADATA_DIR / "research_store" / "jobs"

STATES = ("queued", "running", "succeeded", "failed", "blocked", "timeout")

# Fields a job result must carry before the store will accept it.
REQUIRED_RESULT_FIELDS = (
    "job_id", "hypothesis_id", "signal_name", "partition", "role",
    "failure_class", "interpretation", "evaluation", "manifest",
)


class JobError(RuntimeError):
    pass


class ResultSchemaError(JobError):
    pass


@dataclass
class Job:
    id: str
    spec: dict[str, Any]
    state: str = "queued"
    created_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    finished_at: str = ""
    worktree_path: str = ""
    commit: str = ""
    agent_turns: int = 0
    agent_cost_usd: float | None = None
    agent_session: str = ""
    runtime_s: float = 0.0
    error: str = ""
    result_path: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        return cls(**d)

    def save(self) -> Path:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        p = JOBS_DIR / f"{self.id}.json"
        p.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        return p


def list_jobs() -> list[Job]:
    if not JOBS_DIR.exists():
        return []
    return [Job.from_dict(json.loads(p.read_text()))
            for p in sorted(JOBS_DIR.glob("*.json"), reverse=True)]


def get_job(job_id: str) -> Job | None:
    p = JOBS_DIR / f"{job_id}.json"
    return Job.from_dict(json.loads(p.read_text())) if p.exists() else None


# ---------------------------------------------------------------------------
# the prompt
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """You are a quantitative researcher working inside an alpha
research lab. Write ONE file and stop.

# The question
{question}

Hypothesis: {hypothesis_id}
Signal to construct: `{signal_name}`
Partition: {partition} (role: {role}) — already selected for you.
Primary horizon: {primary_horizon} sessions.

# Your deliverable
Create `job/signal.py` containing exactly:

    import pandas as pd

    def compute(df: pd.DataFrame) -> pd.Series:
        \"\"\"Return the cross-sectional score, aligned to df.index.\"\"\"
        ...

Rules that are not negotiable:
- Return a Series aligned to `df.index`. Higher score = more attractive.
- Use ONLY columns already present in `df`. Do not read files, do not import
  anything from `src`, do not call the network. The frame you are given is
  already point-in-time and already restricted to the right partition.
- Never use a column starting with `fwd_ret_` or `excess_ret_`. Those are
  forward labels — the outcome being predicted. Using one is the single
  worst error available to you here.
- Do not use `sector`, `size_tier`, `size_tier_rank` or `is_etf` as scores.
  They are present-day snapshots and may stratify a result, never rank one.
- Handle missing data. NaN scores are dropped, so prefer NaN over a guess.

# Columns available
{columns}

# How to check your work
Run this, and fix anything it reports:

    python job/check_signal.py

Write the file, run the check, and then reply with two sentences describing
what the signal measures and why it might carry information. Do not evaluate
its performance — that is the harness's job, not yours."""


def build_prompt(spec: ExperimentSpec, columns: list[str],
                 question: str | None = None) -> str:
    show = [c for c in columns
            if not c.startswith(("fwd_ret_", "excess_ret_"))]
    return PROMPT_TEMPLATE.format(
        question=question or spec.question,
        hypothesis_id=spec.hypothesis_id,
        signal_name=spec.signal_name,
        partition=spec.partition,
        role=spec.role,
        primary_horizon=spec.primary_horizon,
        columns=", ".join(sorted(show)),
    )


CHECKER = '''"""Self-check for job/signal.py. Run: python job/check_signal.py"""
import sys, pathlib, json
import numpy as np, pandas as pd

here = pathlib.Path(__file__).parent
sys.path.insert(0, str(here))
sample = here / "sample_frame.parquet"

problems = []
try:
    import signal as _clash  # noqa
except Exception:
    pass
spec_path = here / "signal.py"
if not spec_path.exists():
    print("FAIL: job/signal.py does not exist"); sys.exit(1)

import importlib.util
s = importlib.util.spec_from_file_location("job_signal", spec_path)
m = importlib.util.module_from_spec(s)
try:
    s.loader.exec_module(m)
except Exception as e:
    print(f"FAIL: signal.py did not import: {e}"); sys.exit(1)

if not hasattr(m, "compute"):
    print("FAIL: signal.py has no compute() function"); sys.exit(1)

df = pd.read_parquet(sample)
try:
    out = m.compute(df)
except Exception as e:
    print(f"FAIL: compute() raised: {e}"); sys.exit(1)

if not isinstance(out, pd.Series):
    problems.append(f"compute() returned {type(out).__name__}, expected Series")
else:
    if not out.index.equals(df.index):
        problems.append("returned Series is not aligned to df.index")
    if out.notna().sum() == 0:
        problems.append("every score is NaN")
    elif float(out.std(skipna=True) or 0) == 0:
        problems.append("the score is constant — it cannot rank anything")

src = spec_path.read_text()
for bad in ("fwd_ret_", "excess_ret_"):
    if bad in src:
        problems.append(f"signal.py references {bad!r} — that is a forward label")
for bad in ("size_tier_rank", "size_tier", "is_etf"):
    if bad in src:
        problems.append(f"signal.py uses {bad!r}, a present-day snapshot; it may not score")
if "open(" in src or "read_parquet" in src or "read_csv" in src:
    problems.append("signal.py reads files; use only the frame you are given")

if problems:
    print("PROBLEMS:")
    for p in problems:
        print(" -", p)
    sys.exit(1)
print(f"OK: {out.notna().sum():,} of {len(df):,} rows scored")
'''


# ---------------------------------------------------------------------------
# loading what the worker produced
# ---------------------------------------------------------------------------

FORBIDDEN_PREFIXES = ("fwd_ret_", "excess_ret_")
FORBIDDEN_SCORES = ("sector", "size_tier", "size_tier_rank", "is_etf")


def load_signal_fn(path: Path) -> Callable[[pd.DataFrame], pd.Series]:
    """Import `compute` from an agent-written signal file, with a source audit.

    The source check is a cheap first pass, not the guarantee — the guarantee
    is that the harness never hands the frame's forward-label columns to the
    scoring path and that `assert_scorable` runs downstream.
    """
    if not path.exists():
        raise JobError(f"the worker produced no {path.name}")
    src = path.read_text()
    for bad in FORBIDDEN_PREFIXES:
        if bad in src:
            raise JobError(
                f"signal.py references {bad!r}, a forward label. Refusing to "
                f"score a signal built from the outcome.")

    spec = importlib.util.spec_from_file_location("job_signal", path)
    if spec is None or spec.loader is None:
        raise JobError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, "compute", None)
    if fn is None:
        raise JobError("signal.py defines no compute() function")
    return fn


def validate_result(result: dict) -> None:
    """The dashboard ingests a schema, not a transcript."""
    missing = [f for f in REQUIRED_RESULT_FIELDS if f not in result]
    if missing:
        raise ResultSchemaError(
            f"experiment_result.json is missing {missing}. A job that cannot "
            f"produce a conforming result is a failed job, not a partial one.")
    if not isinstance(result.get("evaluation"), dict):
        raise ResultSchemaError("'evaluation' must be an object")
    if not isinstance(result.get("manifest"), dict):
        raise ResultSchemaError("'manifest' must be an object")


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def _seed_worktree(wt: worktree.Worktree, spec: ExperimentSpec,
                   sample: pd.DataFrame, prompt: str) -> None:
    """Everything the worker needs, and nothing it does not."""
    wt.job_dir.mkdir(parents=True, exist_ok=True)
    (wt.job_dir / "PROMPT.md").write_text(prompt)
    (wt.job_dir / "spec.json").write_text(
        json.dumps(spec.to_dict(), indent=2) + "\n")
    (wt.job_dir / "check_signal.py").write_text(CHECKER)
    sample.to_parquet(wt.job_dir / "sample_frame.parquet")


def run_job(
    spec: ExperimentSpec,
    question: str | None = None,
    timeout_s: int = 1800,
    max_turns: int = 40,
    model: str | None = None,
    cli: str | None = None,
    agent_fn: Callable[[str, Path], agent.AgentResult] | None = None,
    keep_worktree: bool = False,
    sample_rows: int = 5000,
) -> Job:
    """Run one research job end to end.

    `agent_fn` exists so the pipeline can be tested without a live CLI, and so
    a different worker could be swapped in later. Everything else about the
    job is identical either way.
    """
    from .runner import run_exploration          # local: avoids a cycle

    import time
    t0 = time.time()
    job_id = f"JOB_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    jb = Job(id=job_id, spec=spec.to_dict())

    # Budget and lineage are checked *before* a worktree is created: a blocked
    # job should cost nothing.
    try:
        validate_spec(spec)
    except Exception as exc:
        jb.state = "blocked"
        jb.error = f"{type(exc).__name__}: {exc}"
        jb.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        jb.save()
        return jb

    jb.state = "running"
    jb.save()

    wt = None
    try:
        from ..research_data import frame

        df = frame.load_daily_panel(version=spec.dataset_version,
                                    partition=spec.partition,
                                    asof_open=True, include_context=True)
        sample = df.head(sample_rows).copy()

        wt = worktree.create(job_id)
        jb.worktree_path = str(wt.path)
        jb.commit = wt.commit
        prompt = build_prompt(spec, list(df.columns), question=question)
        _seed_worktree(wt, spec, sample, prompt)
        jb.save()

        res = (agent_fn(prompt, wt.path) if agent_fn else
               agent.run_agent(prompt, cwd=wt.path, timeout_s=timeout_s,
                               max_turns=max_turns, model=model, cli=cli))
        jb.agent_turns = res.num_turns
        jb.agent_cost_usd = res.cost_usd
        jb.agent_session = res.session_id
        if not res.ok:
            jb.state = "timeout" if "timed out" in res.stderr else "failed"
            jb.error = res.stderr or res.text[:500] or "agent reported failure"
            return jb

        compute = load_signal_fn(wt.signal_path)

        # The harness runs from the canonical checkout, in this process. The
        # worker's copy of it is irrelevant by construction.
        summary = run_exploration(spec, compute, save_results=True)

        result = {
            "job_id": job_id,
            "hypothesis_id": spec.hypothesis_id,
            "signal_name": spec.signal_name,
            "partition": spec.partition,
            "role": spec.role,
            "failure_class": summary["failure_class"],
            "interpretation": summary["interpretation"],
            "evaluation": summary["evaluation"],
            "manifest": summary["manifest"],
            "exploration_id": summary["exploration_id"],
            "suggested_next_moves": summary.get("suggested_next_moves", []),
            "agent": {
                "turns": res.num_turns,
                "cost_usd": res.cost_usd,
                "session_id": res.session_id,
                "summary": res.text[:2000],
                "signal_source": wt.signal_path.read_text(),
            },
            "commit": wt.commit,
        }
        validate_result(result)
        wt.result_path.write_text(json.dumps(result, indent=2, default=str) + "\n")

        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        stored = JOBS_DIR / f"{job_id}_result.json"
        stored.write_text(json.dumps(result, indent=2, default=str) + "\n")
        jb.result_path = str(stored)
        jb.state = "succeeded"

    except Exception as exc:                       # noqa: BLE001 — recorded, not raised
        jb.state = "failed"
        jb.error = f"{type(exc).__name__}: {exc}"
        jb.error += "\n" + "".join(traceback.format_exc().splitlines(True)[-4:])
    finally:
        jb.runtime_s = round(time.time() - t0, 1)
        jb.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if wt is not None and not keep_worktree:
            # A job that left changes keeps its worktree: for a failure it is
            # usually the only record of what the worker actually did.
            worktree.remove(wt, keep_if_changed=(jb.state != "succeeded"))
        jb.save()

    return jb
