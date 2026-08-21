"""Atomic file-backed persistence store for research objects (the refactor plan §3).

Stores hypotheses, explorations, signals, and evidence as structured JSON
records under `data/metadata/research_store/`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

from ..core import config
from .models import (Evidence, Exploration, Hypothesis, IdeaGraph,
                     PreFlightResult, Signal, Suggestion)


STORE_DIR = config.METADATA_DIR / "research_store"
HYPOTHESES_DIR = STORE_DIR / "hypotheses"
EXPLORATIONS_DIR = STORE_DIR / "explorations"
SIGNALS_DIR = STORE_DIR / "signals"
EVIDENCE_DIR = STORE_DIR / "evidence"
SUGGESTIONS_DIR = STORE_DIR / "suggestions"
PREFLIGHTS_DIR = STORE_DIR / "preflights"


def _ensure_dirs() -> None:
    for d in (HYPOTHESES_DIR, EXPLORATIONS_DIR, SIGNALS_DIR, EVIDENCE_DIR,
              SUGGESTIONS_DIR, PREFLIGHTS_DIR):
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


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

def save_suggestion(sug: Suggestion) -> Path:
    _ensure_dirs()
    p = SUGGESTIONS_DIR / f"{sug.id}.json"
    p.write_text(json.dumps(sug.to_dict(), indent=2) + "\n")
    return p


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
    p.write_text(json.dumps(res.to_dict(), indent=2) + "\n")
    return p


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
