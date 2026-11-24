"""Atomic file-backed persistence store for research objects (the refactor plan §3).

Stores hypotheses, explorations, signals, and evidence as structured JSON
records under `data/metadata/research_store/`.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from ..core import config
from .models import (BatchManifest, Evidence, Exploration, Hypothesis, IdeaGraph,
                     PreFlightResult, QueueProposal, Signal, Suggestion)


STORE_DIR = config.METADATA_DIR / "research_store"
HYPOTHESES_DIR = STORE_DIR / "hypotheses"
EXPLORATIONS_DIR = STORE_DIR / "explorations"
SIGNALS_DIR = STORE_DIR / "signals"
EVIDENCE_DIR = STORE_DIR / "evidence"
SUGGESTIONS_DIR = STORE_DIR / "suggestions"
PREFLIGHTS_DIR = STORE_DIR / "preflights"
QUEUE_DIR = STORE_DIR / "queue"
BATCHES_DIR = STORE_DIR / "batches"


def _ensure_dirs() -> None:
    for d in (HYPOTHESES_DIR, EXPLORATIONS_DIR, SIGNALS_DIR, EVIDENCE_DIR,
              SUGGESTIONS_DIR, PREFLIGHTS_DIR, QUEUE_DIR, BATCHES_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _atomic_write_record(path: Path, payload: dict) -> Path:
    """Replace one JSON record without exposing a partial file to readers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return path


# ---------------------------------------------------------------------------
# Hypotheses
# ---------------------------------------------------------------------------

def save_hypothesis(h: Hypothesis) -> Path:
    _ensure_dirs()
    p = HYPOTHESES_DIR / f"{h.id}.json"
    return _atomic_write_record(p, h.to_dict())


def get_hypothesis(id: str) -> Hypothesis | None:
    p = HYPOTHESES_DIR / f"{id}.json"
    if not p.exists():
        return None
    return Hypothesis.from_dict(json.loads(p.read_text()))


def list_hypotheses(
    status: str | None = None,
    family: str | None = None,
    tag: str | None = None,
) -> list[Hypothesis]:
    _ensure_dirs()
    out = []
    for p in sorted(HYPOTHESES_DIR.glob("*.json")):
        h = Hypothesis.from_dict(json.loads(p.read_text()))
        if status and h.status != status:
            continue
        if family and h.family != family:
            continue
        if tag and tag not in h.tags:
            continue
        out.append(h)
    return out


def next_hypothesis_id() -> str:
    """The next free H0xx.

    Taken over the whole ledger rather than over a count, because H0xx ids are
    permanent and a reused one would silently attach new evidence to an old
    hypothesis.
    """
    _ensure_dirs()
    highest = 0
    for p in HYPOTHESES_DIR.glob("*.json"):
        m = re.fullmatch(r"H(\d+)", p.stem)
        if m:
            highest = max(highest, int(m.group(1)))
    return f"H{highest + 1:03d}"


@contextmanager
def _hypothesis_id_lock():
    """Serialize durable H-ID allocation across CLI/UI worker processes."""
    import fcntl

    director_dir = STORE_DIR / "director"
    director_dir.mkdir(parents=True, exist_ok=True)
    lock_path = director_dir / ".hypothesis_id.lock"
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield director_dir
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def reserve_hypothesis_id(source_key: str, statement: str,
                          family: str) -> str:
    """Bind one provisional dossier identity to one permanent H-ID.

    Qualification is intentionally retryable while it remains outcome-free.
    Without this mapping, every failed authoring attempt called
    ``next_hypothesis_id`` again and registered the same dossier as H049 and
    H050.  The mapping and allocation happen under one process lock, and an
    exact pre-existing ledger statement is adopted to repair older retries.
    """
    if not source_key.strip() or not statement.strip() or not family.strip():
        raise ValueError("source_key, statement and family are required")
    _ensure_dirs()
    with _hypothesis_id_lock() as director_dir:
        mapping_path = director_dir / "hypothesis_promotions.json"
        if mapping_path.exists():
            try:
                raw = json.loads(mapping_path.read_text())
                if not isinstance(raw, dict):
                    raise ValueError("promotion map must be an object")
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                raise RuntimeError(
                    f"hypothesis promotion map is unreadable; refusing ID allocation: {exc}") from exc
        else:
            raw = {}

        existing_id = raw.get(source_key)
        if existing_id:
            return str(existing_id)

        # Adopt the earliest exact ledger match. This makes the mapping repair
        # H049/H050-style duplicates instead of allocating H052 on the retry.
        exact = sorted(
            (h for h in list_hypotheses()
             if h.statement == statement and h.family == family),
            key=lambda h: int(h.id[1:]) if h.id[1:].isdigit() else 10**9,
        )
        if exact:
            assigned = exact[0].id
        else:
            highest = 0
            for p in HYPOTHESES_DIR.glob("H*.json"):
                match = re.fullmatch(r"H(\d+)", p.stem)
                if match:
                    highest = max(highest, int(match.group(1)))
            for value in raw.values():
                match = re.fullmatch(r"H(\d+)", str(value))
                if match:
                    highest = max(highest, int(match.group(1)))
            assigned = f"H{highest + 1:03d}"

        raw[source_key] = assigned
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{mapping_path.name}.", suffix=".tmp",
            dir=str(mapping_path.parent))
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(raw, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, mapping_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return assigned


# ---------------------------------------------------------------------------
# Explorations
# ---------------------------------------------------------------------------

def save_exploration(exp: Exploration) -> Path:
    _ensure_dirs()
    p = EXPLORATIONS_DIR / f"{exp.id}.json"
    return _atomic_write_record(p, exp.to_dict())


def get_exploration(id: str) -> Exploration | None:
    p = EXPLORATIONS_DIR / f"{id}.json"
    if not p.exists():
        return None
    return Exploration.from_dict(json.loads(p.read_text()))


def void_exploration(id: str, reason: str) -> Exploration:
    """Mark an exploration — and every piece of evidence from it — as void.

    Used when the pipeline that produced a result is later found to be wrong.
    Nothing is deleted: a wrong result that is quietly removed is a result the
    next person will produce again.
    """
    from datetime import datetime as _dt
    exp = get_exploration(id)
    if exp is None:
        raise KeyError(f"no exploration {id!r}")
    exp.voided_reason = reason
    exp.voided_date = _dt.now().strftime("%Y-%m-%d")
    save_exploration(exp)
    for ev in list_evidence(include_voided=True):
        if ev.exploration_id == id and not ev.is_void:
            ev.voided_reason = reason
            ev.voided_date = exp.voided_date
            add_evidence(ev)
    return exp


def list_explorations(hypothesis_id: str | None = None,
                      include_voided: bool = False) -> list[Exploration]:
    _ensure_dirs()
    out = []
    for p in sorted(EXPLORATIONS_DIR.glob("*.json")):
        exp = Exploration.from_dict(json.loads(p.read_text()))
        if exp.is_void and not include_voided:
            continue
        if hypothesis_id and exp.hypothesis_id != hypothesis_id:
            continue
        out.append(exp)
    return out


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def save_signal(sig: Signal) -> Path:
    _ensure_dirs()
    p = SIGNALS_DIR / f"{sig.name}.json"
    return _atomic_write_record(p, sig.to_dict())


def get_signal(name: str) -> Signal | None:
    p = SIGNALS_DIR / f"{name}.json"
    if not p.exists():
        return None
    return Signal.from_dict(json.loads(p.read_text()))


def list_signals(hypothesis_id: str | None = None) -> list[Signal]:
    _ensure_dirs()
    out = []
    for p in sorted(SIGNALS_DIR.glob("*.json")):
        sig = Signal.from_dict(json.loads(p.read_text()))
        if hypothesis_id and sig.owner_hypothesis_id != hypothesis_id:
            continue
        out.append(sig)
    return out


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

def add_evidence(ev: Evidence) -> Path:
    _ensure_dirs()
    p = EVIDENCE_DIR / f"{ev.id}.json"
    return _atomic_write_record(p, ev.to_dict())


def get_evidence(id: str) -> Evidence | None:
    p = EVIDENCE_DIR / f"{id}.json"
    if not p.exists():
        return None
    return Evidence.from_dict(json.loads(p.read_text()))


def list_evidence(
    hypothesis_id: str | None = None,
    signal_id: str | None = None,
    role: str | None = None,
    include_voided: bool = False,
) -> list[Evidence]:
    _ensure_dirs()
    out = []
    for p in sorted(EVIDENCE_DIR.glob("*.json")):
        ev = Evidence.from_dict(json.loads(p.read_text()))
        if ev.is_void and not include_voided:
            continue
        if hypothesis_id and ev.hypothesis_id != hypothesis_id:
            continue
        if signal_id and ev.signal_id != signal_id:
            continue
        if role and ev.role != role:
            continue
        out.append(ev)
    return out


# ---------------------------------------------------------------------------
# Graph Loader
# ---------------------------------------------------------------------------

def get_idea_graph() -> IdeaGraph:
    """Builds and returns the IdeaGraph across all stored hypotheses."""
    hyps = list_hypotheses()
    return IdeaGraph(hyps)


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

def save_suggestion(sug: Suggestion) -> Path:
    _ensure_dirs()
    p = SUGGESTIONS_DIR / f"{sug.id}.json"
    return _atomic_write_record(p, sug.to_dict())


def get_suggestion(id: str) -> Suggestion | None:
    p = SUGGESTIONS_DIR / f"{id}.json"
    if not p.exists():
        return None
    return Suggestion.from_dict(json.loads(p.read_text()))


def list_suggestions(status: str | None = None) -> list[Suggestion]:
    """Every suggestion ever made, newest id last.

    The default is deliberately unfiltered: the generator needs the dead ones
    too, since a proposal already refreshed away is exactly the proposal it
    must not make again.
    """
    _ensure_dirs()
    out = []
    for p in sorted(SUGGESTIONS_DIR.glob("*.json")):
        sug = Suggestion.from_dict(json.loads(p.read_text()))
        if status and sug.status != status:
            continue
        out.append(sug)
    return out


def next_suggestion_id() -> str:
    _ensure_dirs()
    highest = 0
    for p in SUGGESTIONS_DIR.glob("*.json"):
        m = re.fullmatch(r"S(\d+)", p.stem)
        if m:
            highest = max(highest, int(m.group(1)))
    return f"S{highest + 1:03d}"


# ---------------------------------------------------------------------------
# Pre-flight Results (PLAN.md §6)
# ---------------------------------------------------------------------------

def save_preflight(res: PreFlightResult) -> Path:
    _ensure_dirs()
    p = PREFLIGHTS_DIR / f"{res.id}.json"
    return _atomic_write_record(p, res.to_dict())


def get_preflight(id: str) -> PreFlightResult | None:
    p = PREFLIGHTS_DIR / f"{id}.json"
    if not p.exists():
        return None
    return PreFlightResult.from_dict(json.loads(p.read_text()))


def list_preflights(
    hypothesis_id: str | None = None,
    signal_name: str | None = None,
    passed: bool | None = None,
) -> list[PreFlightResult]:
    _ensure_dirs()
    out = []
    for p in sorted(PREFLIGHTS_DIR.glob("*.json")):
        res = PreFlightResult.from_dict(json.loads(p.read_text()))
        if hypothesis_id and res.hypothesis_id != hypothesis_id:
            continue
        if signal_name and res.signal_name != signal_name:
            continue
        if passed is not None and res.passed != passed:
            continue
        out.append(res)
    return out


# ---------------------------------------------------------------------------
# Deep Queue Proposals (PLAN.md §5)
# ---------------------------------------------------------------------------

def save_proposal(prop: QueueProposal) -> Path:
    _ensure_dirs()
    p = QUEUE_DIR / f"{prop.id}.json"
    return _atomic_write_record(p, prop.to_dict())


def get_proposal(id: str) -> QueueProposal | None:
    p = QUEUE_DIR / f"{id}.json"
    if not p.exists():
        return None
    return QueueProposal.from_dict(json.loads(p.read_text()))


def list_proposals(status: str | None = None) -> list[QueueProposal]:
    _ensure_dirs()
    out = []
    for p in sorted(QUEUE_DIR.glob("*.json")):
        prop = QueueProposal.from_dict(json.loads(p.read_text()))
        if status and prop.status != status:
            continue
        out.append(prop)
    return out


def next_proposal_id() -> str:
    _ensure_dirs()
    highest = 0
    for p in QUEUE_DIR.glob("*.json"):
        m = re.fullmatch(r"P(\d+)", p.stem)
        if m:
            highest = max(highest, int(m.group(1)))
    return f"P{highest + 1:03d}"


# ---------------------------------------------------------------------------
# Batch Pre-registration (PLAN.md §5, Stage 3)
# ---------------------------------------------------------------------------

def save_batch(batch: BatchManifest) -> Path:
    _ensure_dirs()
    p = BATCHES_DIR / f"{batch.batch_id}.json"
    return _atomic_write_record(p, batch.to_dict())


def get_batch(id: str) -> BatchManifest | None:
    p = BATCHES_DIR / f"{id}.json"
    if not p.exists():
        return None
    return BatchManifest.from_dict(json.loads(p.read_text()))


def list_batches(partition: str | None = None) -> list[BatchManifest]:
    _ensure_dirs()
    out = []
    for p in sorted(BATCHES_DIR.glob("*.json")):
        batch = BatchManifest.from_dict(json.loads(p.read_text()))
        if partition and batch.partition != partition:
            continue
        out.append(batch)
    return out
