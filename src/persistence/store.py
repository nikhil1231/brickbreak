"""Atomic file-backed persistence store for research objects (PLAN.md §3).

Stores hypotheses, explorations, signals, and evidence as structured JSON
records under `data/metadata/research_store/`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from .. import config
from .models import Evidence, Exploration, Hypothesis, IdeaGraph, Signal


STORE_DIR = config.METADATA_DIR / "research_store"
HYPOTHESES_DIR = STORE_DIR / "hypotheses"
EXPLORATIONS_DIR = STORE_DIR / "explorations"
SIGNALS_DIR = STORE_DIR / "signals"
EVIDENCE_DIR = STORE_DIR / "evidence"


def _ensure_dirs() -> None:
    for d in (HYPOTHESES_DIR, EXPLORATIONS_DIR, SIGNALS_DIR, EVIDENCE_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Hypotheses
# ---------------------------------------------------------------------------

def save_hypothesis(h: Hypothesis) -> Path:
    _ensure_dirs()
    p = HYPOTHESES_DIR / f"{h.id}.json"
    p.write_text(json.dumps(h.to_dict(), indent=2) + "\n")
    return p


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


# ---------------------------------------------------------------------------
# Explorations
# ---------------------------------------------------------------------------

def save_exploration(exp: Exploration) -> Path:
    _ensure_dirs()
    p = EXPLORATIONS_DIR / f"{exp.id}.json"
    p.write_text(json.dumps(exp.to_dict(), indent=2) + "\n")
    return p


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
    p.write_text(json.dumps(sig.to_dict(), indent=2) + "\n")
    return p


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
    p.write_text(json.dumps(ev.to_dict(), indent=2) + "\n")
    return p


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
