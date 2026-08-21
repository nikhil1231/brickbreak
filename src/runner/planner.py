"""Idea -> experiment spec (PLAN.md §5.5, v1 item 1).

You type a vague sentence:

    "Do stocks that hold up unusually well during Nifty drawdowns rebound
     harder?"

and get back a plan that says what it intends to measure, which hypothesis it
belongs to, and what would falsify it — amendable before anything runs.

TWO THINGS THE PLANNER MUST GET RIGHT, NOT ONE
1. **Lineage.** An idea that is a descendant of a spent hypothesis family must
   say so, because the ledger blocks on lineage and an unlinked hypothesis is
   how a spent quarter gets read again. The planner is shown the existing
   hypotheses and is required to link or explicitly declare novelty.
2. **The bar, in units of the effect.** H037 passed a bar satisfied by
   -0.037%, a number indistinguishable from zero, because the bar was written
   as a sign test. `spec.validate_pass_criterion` enforces the shape; the
   planner has to propose something that survives it.

Without the selected CLI installed the planner still works: `offline_plan`
builds the same object from the graveyard and the defaults, and says it did.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..persistence import store
from . import agent
from .spec import ExperimentSpec

PLANNER_PROMPT = """You are planning ONE experiment in an alpha research lab.

# The idea, as typed
{idea}

# Existing hypotheses (link to these where the idea is related)
{hypotheses}

# Ideas already dead — do not propose a rerun of one of these
{graveyard}

# Columns available
{columns}

# What to return
Return ONLY a JSON object, no prose around it:

{{
  "question": "one sentence, precise, testable",
  "rationale": "the economic or behavioural reason this might work",
  "what_it_measures": "what the number will actually be, in plain words",
  "hypothesis_id": "an existing H0xx if this is a descendant, else \\"NEW\\"",
  "lineage": [{{"target_id": "H0xx", "relation": "specialises|generalises|conditions-on|contradicts|subsumed-by|adjacent-to|retest-of"}}],
  "family": "which family this belongs to",
  "signal_name": "snake_case name for the score",
  "signal_sketch": "how the score would be computed, in one or two sentences",
  "horizons": [5, 10, 20],
  "primary_horizon": 10,
  "pass_criterion": {{"min_mean_ic": 0.0, "min_spread_bps": 0.0, "min_monotonicity": 0.0}},
  "falsification_condition": "what result would kill this",
  "novelty_note": "why this is not just a restatement of something already tested"
}}

Rules:
- `pass_criterion` must be in units of the effect. Never a sign test: a bar of
  "spread > 0" is satisfied by 0.4 bps, which is nothing. Set numbers you would
  actually act on.
- If the idea is a variant of a dead hypothesis, say so in `lineage` rather
  than presenting it as new. Being a descendant is not disqualifying; hiding it
  is.
- Prefer a signal that is *not* a restatement of generic momentum. Say in
  `novelty_note` what makes it different."""


@dataclass
class Plan:
    """A proposed experiment, before a human has agreed to it."""
    idea: str
    question: str
    rationale: str = ""
    what_it_measures: str = ""
    hypothesis_id: str = "NEW"
    lineage: list[dict] = field(default_factory=list)
    family: str = "general"
    signal_name: str = "candidate_signal"
    signal_sketch: str = ""
    horizons: tuple[int, ...] = (5, 10, 20)
    primary_horizon: int = 10
    pass_criterion: dict[str, float] = field(default_factory=dict)
    falsification_condition: str = ""
    novelty_note: str = ""
    source: str = "agent"
    warnings: list[str] = field(default_factory=list)

    def to_spec(self, partition: str = "train",
                role: str = "exploratory") -> ExperimentSpec:
        return ExperimentSpec(
            hypothesis_id=self.hypothesis_id,
            question=self.question,
            signal_name=self.signal_name,
            partition=partition,
            role=role,
            horizons=tuple(self.horizons),
            primary_horizon=self.primary_horizon,
            pass_criterion=dict(self.pass_criterion),
            falsification_condition=self.falsification_condition,
        )

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["horizons"] = list(self.horizons)
        return d


def _context() -> tuple[str, str]:
    """Existing hypotheses and the graveyard, as the planner sees them."""
    hyps, dead = [], []
    for h in store.list_hypotheses():
        line = f"{h.id} [{h.family}/{h.status}] {h.title}"
        hyps.append(line)
        if h.status in ("rejected", "decayed", "superseded"):
            why = (getattr(h, "rejection_reason", "") or
                   getattr(h, "summary", "") or "")[:160]
            dead.append(f"{h.id}: {h.title} — {why}" if why
                        else f"{h.id}: {h.title}")
    return "\n".join(hyps) or "(none)", "\n".join(dead) or "(none)"


def _extract_json(text: str) -> dict:
    """Pull the JSON object out of a reply that may be wrapped in prose."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("the planner returned no JSON object")
    return json.loads(m.group(0))


def offline_plan(idea: str, columns: list[str] | None = None,
                 provider: str = agent.DEFAULT_PROVIDER) -> Plan:
    """A usable plan without the CLI, honest about being a stub.

    It cannot invent a rationale or a signal, so it says so and leaves the
    fields for a human. Everything structural — a bar with real numbers in it,
    a default partition, the horizons — is filled in.
    """
    return Plan(
        idea=idea,
        question=idea.strip().rstrip("?") + "?",
        rationale=f"(not generated — {provider} CLI unavailable)",
        what_it_measures="(fill in before running)",
        signal_name="candidate_signal",
        pass_criterion={"min_mean_ic": 0.015, "min_spread_bps": 30.0,
                        "min_monotonicity": 0.6},
        falsification_condition="mean IC indistinguishable from zero after "
                                "the overlap correction, or a non-monotonic "
                                "quantile profile",
        source="offline",
        warnings=[f"{provider} CLI not installed; lineage was not checked "
                  "against existing hypotheses, so this plan may restate "
                  "something already tested. Link it by hand."],
    )


def propose(idea: str, columns: list[str] | None = None,
            cli: str | None = None, timeout_s: int = 300,
            agent_fn=None, provider: str = agent.DEFAULT_PROVIDER,
            model: str | None = None) -> Plan:
    """Turn a typed idea into a plan. Falls back to `offline_plan`."""
    provider = agent.validate_provider(provider)
    if agent_fn is None and not agent.available(cli, provider=provider):
        return offline_plan(idea, columns, provider=provider)

    hyps, dead = _context()
    prompt = PLANNER_PROMPT.format(
        idea=idea, hypotheses=hyps, graveyard=dead,
        columns=", ".join(sorted(columns or [])) or "(not supplied)")

    import pathlib
    res = (agent_fn(prompt) if agent_fn else
           agent.run_agent(prompt, cwd=pathlib.Path.cwd(), timeout_s=timeout_s,
                           max_turns=3, allowed_tools=(), cli=cli,
                           provider=provider, model=model, sandbox="read-only"))
    if not res.ok:
        p = offline_plan(idea, columns, provider=provider)
        p.warnings.append(f"planner failed ({res.stderr or 'no output'}); "
                          f"fell back to the offline plan")
        return p

    try:
        data = _extract_json(res.text)
    except (ValueError, json.JSONDecodeError) as exc:
        p = offline_plan(idea, columns, provider=provider)
        p.warnings.append(f"planner returned unparseable output ({exc})")
        return p

    plan = Plan(
        idea=idea,
        question=data.get("question", idea),
        rationale=data.get("rationale", ""),
        what_it_measures=data.get("what_it_measures", ""),
        hypothesis_id=data.get("hypothesis_id", "NEW"),
        lineage=data.get("lineage", []) or [],
        family=data.get("family", "general"),
        signal_name=data.get("signal_name", "candidate_signal"),
        signal_sketch=data.get("signal_sketch", ""),
        horizons=tuple(data.get("horizons", (5, 10, 20))),
        primary_horizon=int(data.get("primary_horizon", 10)),
        pass_criterion=data.get("pass_criterion", {}) or {},
        falsification_condition=data.get("falsification_condition", ""),
        novelty_note=data.get("novelty_note", ""),
        source=provider,
    )
    plan.warnings.extend(review(plan))
    return plan


def review(plan: Plan) -> list[str]:
    """Checks a human would otherwise have to remember to make."""
    out = []
    if plan.hypothesis_id == "NEW" and not plan.lineage:
        out.append("Declared new with no lineage. If this is a variant of an "
                   "existing hypothesis, link it — the ledger blocks on "
                   "lineage, and an unlinked descendant is how a spent "
                   "quarter gets read twice.")
    for hid in [e.get("target_id") for e in plan.lineage]:
        h = store.get_hypothesis(hid) if hid else None
        if h and h.status in ("rejected", "decayed"):
            out.append(f"Linked to {hid}, which is {h.status}. Check the "
                       f"graveyard entry before spending anything on this.")
    if not plan.pass_criterion:
        out.append("No pass criterion proposed. Freeze one before dispatch.")
    return out
