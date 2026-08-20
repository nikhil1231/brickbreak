"""Isolated git worktrees for research jobs (PLAN.md §5.7).

One exploration must not be able to trash another, or mutate the canonical
data pipeline. Each job gets its own worktree from the current commit, its own
writable output directory, and a read-only view of the data store.

Data is *linked*, not copied: the store is ~1.5GB and every job would
otherwise pay for a duplicate. The links go *inside* `data/`, one per entry,
rather than replacing the directory — replacing it makes git report every
tracked file under `data/metadata` (the frozen splits, the holdout results) as
deleted, and a job branch that looks like it deleted the evidence is worse than
no isolation at all. Everything linked is already gitignored, so a job's
`git status` stays clean apart from its own output.

Isolation is structural, not permission-based: a worker reaches data through
`research_data` and the tests enforce that. The links are a convenience, not
the lock.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import config


class WorktreeError(RuntimeError):
    pass


WORKTREE_ROOT = config.PROJECT_ROOT.parent / ".brickbreak_worktrees"


def _git(*args: str, cwd: Path | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd or config.PROJECT_ROOT),
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise WorktreeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


@dataclass
class Worktree:
    """A checkout a job may write to, and the commit it came from."""
    path: Path
    branch: str
    commit: str

    @property
    def job_dir(self) -> Path:
        """Where the job writes. The only directory a worker should create in."""
        return self.path / "job"

    @property
    def result_path(self) -> Path:
        return self.job_dir / "experiment_result.json"

    @property
    def signal_path(self) -> Path:
        return self.job_dir / "signal.py"


def create(job_id: str, link_data: bool = True) -> Worktree:
    """Create an isolated worktree for `job_id` at the current HEAD."""
    WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    path = WORKTREE_ROOT / job_id
    if path.exists():
        raise WorktreeError(f"worktree {path} already exists")

    commit = _git("rev-parse", "HEAD")
    branch = f"job/{job_id}"
    _git("worktree", "add", "--detach", str(path), commit)
    _git("checkout", "-B", branch, cwd=path)

    (path / "job").mkdir(exist_ok=True)

    if link_data:
        _link_data(path)

    return Worktree(path=path, branch=branch, commit=commit)


def _link_data(path: Path) -> None:
    """Symlink each store entry that the checkout does not already carry."""
    for sub in ("normalized", "raw", "metadata"):
        real = config.DATA_DIR / sub
        if not real.exists():
            continue
        mirror = path / "data" / sub
        mirror.mkdir(parents=True, exist_ok=True)
        for entry in real.iterdir():
            target = mirror / entry.name
            if target.exists() or target.is_symlink():
                continue          # tracked file checked out from git — leave it
            target.symlink_to(entry)


def remove(wt: Worktree, keep_if_changed: bool = True) -> bool:
    """Tear down a worktree. Returns True if it was removed.

    A worktree whose job left uncommitted changes is kept by default: the
    output of a failed job is usually the only record of why it failed.
    """
    if keep_if_changed and _is_dirty(wt):
        return False

    _unlink_data(wt.path)
    _git("worktree", "remove", "--force", str(wt.path))
    try:
        _git("branch", "-D", wt.branch)
    except WorktreeError:
        pass
    return True


def _unlink_data(path: Path) -> None:
    for sub in ("normalized", "raw", "metadata"):
        mirror = path / "data" / sub
        if not mirror.exists():
            continue
        for entry in mirror.iterdir():
            if entry.is_symlink():
                entry.unlink()


def _is_dirty(wt: Worktree) -> bool:
    """Changes other than the job's own output directory."""
    try:
        lines = _git("status", "--porcelain", cwd=wt.path).splitlines()
    except WorktreeError:
        return False
    return any(l.strip() and "job/" not in l for l in lines)


def prune() -> None:
    """Drop worktree records whose directories are gone."""
    _git("worktree", "prune")
