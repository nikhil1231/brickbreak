"""The research inbox: what to test next, given everything already tested.

The Explore console answers "run this idea". This module answers the harder
question that comes before it — *which* idea — and it is the one place in the
lab where a model is asked to be original rather than obedient.

THREE THINGS THIS MUST NOT BECOME
1. **A random idea generator.** "Try momentum with different lookbacks" is
   not a proposal; it is a sentence. Every suggestion here has to name the
   population, the conditioning variable, the mechanism, and the columns it
   would be computed from, or the reviewer cannot tell a real idea from a
   plausible-sounding one.
2. **A machine for re-running the graveyard.** This project has 38 recorded
   hypotheses and four of them are dead for reasons that are not obvious from
   their titles. The generator is shown all of them — statuses, rejection
   reasons, and every measured result — and is required to say, per
   suggestion, why it is not a restatement of one.
3. **A momentum factory.** The objective is several weakly-correlated alphas,
   not the strongest single one (the refactor plan §5.12), so a proposal states which
   existing signal it expects to correlate with. An idea that would land on
   top of `rs_60d_vs_mkt` is worth less than a weaker independent one, and the
   generator is told so.

WHY SUGGESTIONS ARE STORED
Generating on page load would spend a model call every time a tab is opened,
and — worse — would silently change the list under someone deciding between
its entries. Suggestions are written to the store, read back cheaply, and
regenerate only when asked. Refreshing one replaces that slot alone; the
displaced suggestion is kept as `replaced`, because the list of everything
ever proposed is what stops the next generation proposing it again.

Without a CLI installed the module still returns something, mechanically
derived from the store's own failure classes, and says that is what it is.
"""
from __future__ import annotations

import json
import re
from ..persistence import store
from ..persistence.models import (RELATION_TYPES, Edge, Hypothesis,
                                  Suggestion)
from ..research_data import catalogue
from . import agent
from .spec import SpecValidationError, validate_pass_criterion

DEFAULT_COUNT = 3

# The bar a suggestion falls back to when the one it proposed cannot fail.
# These are the spec defaults, and they are above transaction costs on purpose.
DEFAULT_BAR = {
    "min_mean_ic": 0.015,
    "min_spread_bps": 30.0,
    "min_monotonicity": 0.60,
}

# A proposal whose wording overlaps an existing hypothesis this much is
# flagged, not dropped. Restating H021 is sometimes the right move — doing it
# without noticing is not.
DUPLICATE_JACCARD = 0.6


# Ordered static-first on purpose. Everything above the "ledger" heading is
# byte-identical between calls, so it forms a cacheable prefix; everything the
# store can change sits below it. Putting the 3k-token column catalogue after
# the ledger — where it used to live — invalidated the whole prefix on every
# run for no benefit.
#
# The inbox is deliberately absent. Its only job was to stop the generator
# restating something already proposed, and `_restates_existing` does that job
# after generation, against the same corpus, for none of the tokens.
SUGGEST_PROMPT = """You are the research director of an alpha lab trading NSE
(Indian) equities on daily data. Your job is to propose the experiments most
likely to produce a *real, tradeable* edge on this specific data — not the
most interesting-sounding ones.

Use what you know about cross-sectional equity anomalies, market
microstructure, and the specific institutional features of the Indian market
(promoter holding dynamics, delivery-based settlement, circuit limits, retail
flow concentration, index-inclusion effects, the F&O ban list, monthly expiry).
But every proposal must be computable from the columns listed below, on daily
bars, for a ~1,500-2,000 name liquid universe from 2020 onward.

# What can be computed
Format: name | first knowable | PIT | scorable | description
{columns}

# Rules this lab enforces, which constrain what is worth proposing
- Only point-in-time features may be *scored*. `sector`, `size_tier`,
  `size_tier_rank` and `is_etf` are present-day snapshots: they may stratify a
  result, never rank one. Anything with `fwd_ret_`/`excess_ret_` is the
  outcome.
- Costs are 0.40% round trip, measured and conservative. A Q5-Q1 spread under
  ~25 bps is not tradeable no matter how significant it is.
- Long horizons are punished twice: overlapping forward windows inflate every
  t-statistic (corrected by Hansen-Hodrick), and the correction cannot invent
  independent observations. A 20-session idea needs a *large* effect to survive;
  5-15 sessions is where this data has room.
- 2020-2023 has been read twice and is spent for the opening-window and
  resilience families. A descendant of those families can only be confirmed on
  the forward lane, so an idea in a *different* family is worth more.
- The objective is several weakly-correlated alphas, not one strong one. A
  score that would correlate above ~0.7 with an existing signal is worth less
  than a weaker independent one.
- A score built by subtracting a factor is usually a sort on that factor. This
  lab already shipped that mistake once (H038): within one session the market
  return is a constant, so `r - beta*r_mkt` is algebraically just `beta`.

# What a good proposal looks like here
Names a specific population, a specific conditioning variable, and a reason a
mispricing would exist and persist — who is on the other side of the trade and
why they keep taking it. Bad: "test relative strength over other lookbacks".
Good: "names whose delivery percentage rises while price consolidates are being
accumulated by holders who do not intend to sell into the next print; rank by
20-day delivery trend within contraction states".

You may read HYPOTHESES.md, FINDINGS.md and AGENTS.md in this repository for
detail before answering. Do not write or edit any file.

# The ledger — every hypothesis this lab has already recorded
{ledger}

# Dead, and why. Do not propose these again in new words.
{graveyard}

# What has actually been measured
{evidence}

# Signals already scored on this data
{signals}

# What to return
Return ONLY a JSON array of exactly {n} object(s), ordered most promising
first, with no prose around it:

[
  {{
    "title": "six to ten words, the claim itself, not a topic",
    "question": "one precise, testable sentence",
    "rationale": "the economic or behavioural mechanism, and who is on the other side",
    "what_it_measures": "what the number will actually be, in plain words",
    "signal_name": "snake_case name for the score",
    "signal_sketch": "how the score is computed, naming the columns used",
    "family": "which family this belongs to (an existing one, or a new name)",
    "lineage": [{{"target_id": "H0xx", "relation": "{relations}"}}],
    "evidence_basis": "which recorded result or measurement motivates this",
    "novelty_note": "why this is not a restatement of anything above",
    "expected_correlation": "which existing signal this would resemble, and roughly how much",
    "horizons": [5, 10, 20],
    "primary_horizon": 10,
    "pass_criterion": {{"min_mean_ic": 0.015, "min_spread_bps": 30.0, "min_monotonicity": 0.6}},
    "falsification_condition": "what result would kill this"
  }}
]

`pass_criterion` must be in units of the effect and must be able to fail. A bar
of "spread > 0" is satisfied by 0.4 bps, which is nothing; set numbers you
would act on. If a proposal is a descendant of something in the ledger, say so
in `lineage` — being a descendant is not disqualifying, hiding it is."""


# ---------------------------------------------------------------------------
# what the generator is shown
# ---------------------------------------------------------------------------

def _ledger_context() -> tuple[str, str]:
    """The ledger and the graveyard, as the generator sees them."""
    live, dead = [], []
    for h in store.list_hypotheses():
        live.append(f"{h.id} [{h.family}/{h.status}] {h.title}")
        if h.status in ("rejected", "decayed", "superseded"):
            why = (h.rationale or h.statement or "")[:200]
            dead.append(f"{h.id}: {h.title}" + (f" — {why}" if why else ""))
    return "\n".join(live) or "(none)", "\n".join(dead) or "(none)"


def _evidence_context(limit: int = 40) -> str:
    """Measured results, most recent last. Voided results are excluded."""
    lines = []
    for ev in store.list_evidence()[-limit:]:
        metrics = ev.metrics or {}
        keys = ("mean_ic", "t_stat", "q5_spread_bps", "ic_retention_pct")
        nums = ", ".join(f"{k}={metrics[k]}" for k in keys if k in metrics)
        lines.append(f"{ev.hypothesis_id} [{ev.role}/{ev.partition}] "
                     f"{ev.signal_id}: {ev.verdict_statement}"
                     + (f" ({nums})" if nums else ""))
    for exp in store.list_explorations()[-limit:]:
        lines.append(f"{exp.hypothesis_id} {exp.failure_class}: {exp.verdict}")
    return "\n".join(lines) or "(nothing measured yet)"


def _signal_context() -> str:
    lines = [f"{s.name} (owner {s.owner_hypothesis_id}): {s.definition}"
             for s in store.list_signals()]
    return "\n".join(lines) or "(none)"


def _column_context() -> str:
    cat = catalogue.DEFAULT
    return "\n".join(
        f"{s.name} | {s.available_as_of} | "
        f"{'PIT' if s.point_in_time else 'NOT-PIT'} | "
        f"{'scorable' if cat.scorable(s.name) else 'stratify-only'} | "
        f"{s.description}"
        for s in cat.all_features())


def build_prompt(n: int) -> str:
    ledger, graveyard = _ledger_context()
    return SUGGEST_PROMPT.format(
        n=n,
        ledger=ledger,
        graveyard=graveyard,
        evidence=_evidence_context(),
        signals=_signal_context(),
        columns=_column_context(),
        relations="|".join(RELATION_TYPES),
    )


# ---------------------------------------------------------------------------
# reading what came back
# ---------------------------------------------------------------------------

def _extract_json_array(text: str) -> list[dict]:
    """Pull the JSON array out of a reply that may be wrapped in prose."""
    for candidate in (text, *(m.group(0) for m in
                              re.finditer(r"\[.*\]", text, re.S))):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            data = data.get("suggestions", [])
        if isinstance(data, list) and data:
            return [d for d in data if isinstance(d, dict)]
    raise ValueError("the generator returned no JSON array of suggestions")


def _tokens(*parts: str) -> set[str]:
    words = re.findall(r"[a-z]{4,}", " ".join(parts).lower())
    return set(words)


def _restates_existing(title: str, question: str) -> str:
    """The id of a recorded hypothesis or prior proposal this all but repeats.

    This is the whole of the lab's duplicate defence, and it is deliberately
    on this side of the call. The generator used to be *shown* every
    suggestion ever made so it would not repeat one; that block grew without
    bound — every proposal ever, forever, at ~220 characters each — and it
    bought nothing this comparison does not, because a restatement is just as
    catchable on the way out as it is preventable on the way in.

    Hypotheses are checked first: repeating one of those is the more expensive
    mistake, since something in the ledger may already have been scored.
    """
    proposed = _tokens(title, question)
    if not proposed:
        return ""

    def matches(other: set[str]) -> bool:
        if not other:
            return False
        return len(proposed & other) / len(proposed | other) >= DUPLICATE_JACCARD

    for h in store.list_hypotheses():
        if matches(_tokens(h.title, h.statement)):
            return h.id
    for sug in store.list_suggestions():
        if matches(_tokens(sug.title, sug.question)):
            return sug.id
    return ""


def _snake(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_]+", "_", str(name or "").lower()).strip("_")
    return cleaned or fallback


def coerce(data: dict, slot: int, source: str, model: str = "",
           sug_id: str | None = None) -> Suggestion:
    """Turn one returned object into a Suggestion, with its own review attached.

    Nothing here is silently repaired except a bar that cannot fail, and that
    substitution is recorded as a warning. A suggestion that quietly had its
    lineage or its threshold rewritten would be a worse input to a decision
    than one that says what is wrong with it.
    """
    warnings: list[str] = []
    title = str(data.get("title") or data.get("question") or "").strip()
    question = str(data.get("question") or title).strip()
    if not title or not question:
        raise ValueError("suggestion has neither a title nor a question")

    lineage = []
    for edge in data.get("lineage") or []:
        if not isinstance(edge, dict):
            continue
        target, relation = edge.get("target_id"), edge.get("relation")
        if relation not in RELATION_TYPES:
            warnings.append(f"dropped a lineage edge with unknown relation "
                            f"{relation!r}")
            continue
        if not target or store.get_hypothesis(str(target)) is None:
            warnings.append(f"dropped a lineage edge to {target!r}, which is "
                            f"not in the ledger")
            continue
        lineage.append({"target_id": str(target), "relation": relation})

    criterion = data.get("pass_criterion") or {}
    if isinstance(criterion, dict):
        criterion = {k: v for k, v in criterion.items()
                     if isinstance(v, (int, float))}
    else:
        criterion = {}
    try:
        validate_pass_criterion(criterion)
    except SpecValidationError as exc:
        warnings.append(f"proposed bar rejected ({exc}); replaced with the "
                        f"lab default")
        criterion = dict(DEFAULT_BAR)

    horizons = [int(h) for h in (data.get("horizons") or [5, 10, 20])
                if isinstance(h, (int, float))] or [5, 10, 20]
    primary = int(data.get("primary_horizon") or horizons[min(1, len(horizons) - 1)])
    if primary not in horizons:
        horizons.append(primary)

    signal_name = _snake(data.get("signal_name"), f"slot{slot}_signal")
    if store.get_signal(signal_name) is not None:
        warnings.append(f"signal name {signal_name!r} has already been scored "
                        f"on this data; rename it before dispatch")

    restated = _restates_existing(title, question)
    if restated:
        warnings.append(f"reads as a restatement of {restated}. Check that "
                        f"entry before spending anything on this.")
    if not lineage and not data.get("novelty_note"):
        warnings.append("no lineage and no novelty note. An unlinked "
                        "descendant is how a spent quarter gets read twice.")

    return Suggestion(
        id=sug_id or store.next_suggestion_id(),
        title=title,
        question=question,
        rationale=str(data.get("rationale") or "").strip(),
        what_it_measures=str(data.get("what_it_measures") or "").strip(),
        signal_name=signal_name,
        signal_sketch=str(data.get("signal_sketch") or "").strip(),
        family=_snake(data.get("family"), "general"),
        lineage=lineage,
        novelty_note=str(data.get("novelty_note") or "").strip(),
        evidence_basis=str(data.get("evidence_basis") or "").strip(),
        expected_correlation=str(data.get("expected_correlation") or "").strip(),
        horizons=sorted(set(horizons)),
        primary_horizon=primary,
        pass_criterion=criterion,
        falsification_condition=str(
            data.get("falsification_condition") or "").strip(),
        slot=slot,
        source=source,
        model=model,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# generation
# ---------------------------------------------------------------------------

def _failure_reason(res: agent.AgentResult) -> str:
    """Why the call failed, in the CLI's own words.

    The half that matters — "Not logged in · Please run /login" — arrives on
    stdout, while stderr often carries nothing but a benign warning about
    stdin. Reading stderr first reported the warning and dropped the reason.
    """
    parts = [re.sub(r"\x1b\[[0-9;]*m", "", part).strip()
             for part in (res.text, res.stderr) if part and part.strip()]
    return " | ".join(dict.fromkeys(parts))[:300] or "no output"


def _run(prompt: str, provider: str, model: str | None, timeout_s: int,
         cli: str | None, agent_fn) -> agent.AgentResult:
    if agent_fn is not None:
        return agent_fn(prompt)
    import pathlib
    return agent.run_agent(
        prompt, cwd=pathlib.Path.cwd(), timeout_s=timeout_s, max_turns=12,
        # Read-only on purpose: the generator is allowed to ground itself in
        # the ledger and the findings, and allowed to do nothing else.
        allowed_tools=("Read", "Grep", "Glob"), cli=cli, provider=provider,
        model=model, sandbox="read-only")


def generate(
    n: int = DEFAULT_COUNT,
    slots: list[int] | None = None,
    provider: str = agent.DEFAULT_PROVIDER,
    model: str | None = None,
    timeout_s: int = 900,
    cli: str | None = None,
    agent_fn=None,
    save: bool = True,
) -> list[Suggestion]:
    """Propose `n` experiments, grounded in everything already recorded.

    Falls back to `offline_suggestions` when no CLI is installed or the call
    fails, and the returned suggestions say which happened.
    """
    provider = agent.validate_provider(provider)
    slots = list(slots or range(n))[:n]
    while len(slots) < n:
        slots.append(max(slots, default=-1) + 1)

    if agent_fn is None and not agent.available(cli, provider=provider):
        out = offline_suggestions(n, slots, note=f"{provider} CLI not installed")
        return _persist(out) if save else out

    try:
        res = _run(build_prompt(n), provider, model, timeout_s, cli, agent_fn)
    except agent.AgentError as exc:
        out = offline_suggestions(n, slots, note=str(exc))
        return _persist(out) if save else out

    if not res.ok:
        out = offline_suggestions(
            n, slots, note=f"the generator failed ({_failure_reason(res)})")
        return _persist(out) if save else out

    try:
        raw = _extract_json_array(res.text)
    except ValueError as exc:
        out = offline_suggestions(n, slots, note=f"unparseable output ({exc})")
        return _persist(out) if save else out

    # One call produces the whole batch, so its cost is shared across the
    # suggestions it returned rather than attributed to any one of them.
    share = (res.cost_usd / max(1, len(raw[:n]))) if res.cost_usd else None

    out: list[Suggestion] = []
    for slot, item in zip(slots, raw[:n]):
        try:
            sug = coerce(item, slot=slot, source=provider,
                         model=model or "cli-default",
                         sug_id=_reserve_id(out))
            sug.cost_usd = share
            sug.turns = res.num_turns
            out.append(sug)
        except (ValueError, TypeError) as exc:
            # One malformed entry does not void the others; the shortfall is
            # made up mechanically and labelled.
            continue
    if len(out) < n:
        short = offline_suggestions(
            n - len(out), slots[len(out):],
            note=f"{provider} returned {len(out)} usable suggestion(s) of {n}",
            taken=out)
        out.extend(short)
    return _persist(out) if save else out


def _reserve_id(pending: list[Suggestion]) -> str:
    """Next id, counting the ones in this batch that are not written yet."""
    base = store.next_suggestion_id()
    if not pending:
        return base
    highest = max(int(s.id[1:]) for s in pending if re.fullmatch(r"S\d+", s.id))
    return f"S{max(int(base[1:]), highest + 1):03d}"


def _persist(suggestions: list[Suggestion]) -> list[Suggestion]:
    """Write a batch, retiring whatever it displaces.

    Generating into a slot that is already occupied replaces its occupant
    rather than stacking on it, so the inbox never shows two suggestions in
    one slot. The displaced one becomes `replaced`, not deleted — it still has
    to be checkable as something already proposed, which `_restates_existing`
    does against every suggestion whatever its status.
    """
    incoming = {sug.slot for sug in suggestions}
    new_ids = {sug.id for sug in suggestions}
    for existing in store.list_suggestions(status="open"):
        if existing.slot in incoming and existing.id not in new_ids:
            existing.status = "replaced"
            store.save_suggestion(existing)
    for sug in suggestions:
        store.save_suggestion(sug)
    return suggestions


def open_suggestions() -> list[Suggestion]:
    """What the inbox currently holds, in slot order."""
    return sorted(store.list_suggestions(status="open"),
                  key=lambda s: (s.slot, s.id))


def refresh(
    suggestion_id: str,
    provider: str = agent.DEFAULT_PROVIDER,
    model: str | None = None,
    timeout_s: int = 900,
    cli: str | None = None,
    agent_fn=None,
) -> Suggestion:
    """Replace one suggestion with a new one, leaving its neighbours alone.

    The displaced suggestion is marked `replaced` rather than deleted, so a
    proposal that reads as the same idea comes back flagged as a restatement
    of it rather than as something new.
    """
    old = store.get_suggestion(suggestion_id)
    if old is None:
        raise KeyError(f"no suggestion {suggestion_id!r}")
    if old.status != "open":
        raise ValueError(
            f"suggestion {suggestion_id} is {old.status}, not open; only an "
            f"open suggestion can be refreshed")

    old.status = "replaced"
    store.save_suggestion(old)
    try:
        new = generate(1, slots=[old.slot], provider=provider, model=model,
                       timeout_s=timeout_s, cli=cli, agent_fn=agent_fn,
                       save=False)[0]
    except Exception:
        # A failed refresh must not eat the slot it was replacing.
        old.status = "open"
        store.save_suggestion(old)
        raise
    new.replaces = old.id
    store.save_suggestion(new)
    return new


# ---------------------------------------------------------------------------
# promotion — the only path from an idea to something the ledger knows about
# ---------------------------------------------------------------------------

def promote(suggestion_id: str) -> tuple[Suggestion, Hypothesis]:
    """Register a suggestion as a real hypothesis, ready to be dispatched.

    `spec.validate_spec` refuses to run an experiment against an unregistered
    id — resolving an unknown one to a "general" family once granted it
    confirmatory access to spent quarters. So pressing play registers first:
    the hypothesis is created with the suggestion's family and its lineage
    edges, which is precisely what the budget ledger reasons over.

    Idempotent: a suggestion already promoted returns its existing hypothesis.
    """
    sug = store.get_suggestion(suggestion_id)
    if sug is None:
        raise KeyError(f"no suggestion {suggestion_id!r}")
    if sug.hypothesis_id:
        existing = store.get_hypothesis(sug.hypothesis_id)
        if existing is not None:
            return sug, existing

    hyp = Hypothesis(
        id=store.next_hypothesis_id(),
        title=sug.title,
        statement=sug.question,
        rationale=sug.rationale or f"Suggested by {sug.source} ({sug.id}).",
        status="proposed",
        family=sug.family,
        edges=[Edge(target_id=e["target_id"], relation=e["relation"])
               for e in sug.lineage],
        tags=["suggested", f"from_{sug.id}"],
    )
    store.save_hypothesis(hyp)
    sug.hypothesis_id = hyp.id
    sug.status = "launched"
    store.save_suggestion(sug)
    return sug, hyp


# ---------------------------------------------------------------------------
# the offline path
# ---------------------------------------------------------------------------

# The class-to-next-move table of the refactor plan §5.11, written as whole proposals
# rather than as verbs. This is mechanical follow-up, not insight, and it says
# so — but a mechanical follow-up of a real measured failure is still grounded
# in something, which is more than a generic idea would be.
_FOLLOW_UP: dict[str, dict[str, str]] = {
    "SIGNAL_BUT_BETA": {
        "title": "{signal} survives once its factor exposure is removed",
        "question": "Does {signal} retain cross-sectional predictive content "
                    "after it is ranked within sector rather than across the "
                    "universe?",
        "rationale": "The raw score was classified SIGNAL_BUT_BETA, so most of "
                     "its IC was standard factor exposure. Ranking inside the "
                     "sector removes the exposure without removing the claim.",
        "relation": "specialises",
    },
    "NO_SIGNAL": {
        "title": "{signal} carries information only in one market regime",
        "question": "Does {signal} predict forward returns when conditioned on "
                    "the market regime, having shown nothing unconditionally?",
        "rationale": "An unconditional null is consistent with an effect that "
                     "switches sign across regimes and averages to zero. "
                     "Conditioning is the cheapest test of that.",
        "relation": "conditions-on",
    },
    "SIGNAL_TOO_SMALL": {
        "title": "{signal} is worth holding as a combination weight",
        "question": "Does {signal} add incremental predictive value on top of "
                    "the strongest existing signal, despite being too small to "
                    "trade alone?",
        "rationale": "A spread inside transaction costs can still be valuable "
                     "if it is uncorrelated with what is already held — the "
                     "objective is several weak independent alphas.",
        "relation": "adjacent-to",
    },
    "HIGH_TURNOVER": {
        "title": "{signal} keeps its edge when smoothed to a tradeable turnover",
        "question": "Does a smoothed version of {signal} retain its IC while "
                    "cutting rank turnover below the level where costs eat it?",
        "rationale": "The content was real and the churn was what killed it. "
                     "Smoothing tests whether the information is in the level "
                     "or only in the daily change.",
        "relation": "specialises",
    },
    "UNSTABLE": {
        "title": "{signal}'s instability is itself predictable from volatility",
        "question": "Does conditioning {signal} on the prevailing market "
                    "volatility state recover a stable effect?",
        "rationale": "Yearly ICs that swing sign are a regime story. If the "
                     "regime is observable in advance, the instability is a "
                     "conditioning variable rather than a defect.",
        "relation": "conditions-on",
    },
    "SUCCESS": {
        "title": "{signal} holds up outside the window it was found in",
        "question": "Does {signal} retain its effect on a partition that was "
                    "not used to form it?",
        "rationale": "An exploratory success is a hypothesis, not a result. "
                     "The forward lane is the only clean confirmation left for "
                     "anything descended from the spent quarters.",
        "relation": "retest-of",
    },
}


# A coverage probe is only worth proposing on a column that can actually rank
# a cross-section. Two whole classes of column cannot:
#   - a price *level* (`ema_fast`, `prior_high_20`) ranks by share price, which
#     says nothing about one company against another;
#   - a market-wide series (`mkt_*`) is a constant within a session, so the
#     rank is degenerate and the report would be scoring nothing.
_RANKABLE_SUFFIXES = ("_pct", "_pctile", "_ratio", "_slope", "_steps",
                      "_squeeze", "_breadth", "_k", "_5", "_20", "_50")
_RANKABLE_PREFIXES = ("rs_", "dist_", "ret_", "deliv_", "px_vs_", "base_",
                      "range_", "body_", "atr_", "bb_", "vol_", "n_",
                      "days_since_", "open_base_", "sec_ret_")


def _rankable(name: str) -> bool:
    if name.startswith("mkt_"):
        return False
    return (name.startswith(_RANKABLE_PREFIXES)
            or name.endswith(_RANKABLE_SUFFIXES))


def offline_suggestions(n: int, slots: list[int] | None = None,
                        note: str = "", taken: list[Suggestion] | None = None
                        ) -> list[Suggestion]:
    """Follow-ups derived from the store, honest about being mechanical.

    Draws first on real measured failures — each class has one defined next
    move — and then, if the store cannot supply enough of those, on catalogue
    features nothing has ever been scored on. It may return fewer than `n`;
    inventing the difference is what this module exists to avoid.
    """
    slots = list(slots or range(n))
    warning = ("Generated without a model" + (f": {note}" if note else "")
               + ". This is a mechanical follow-up of a recorded result, not "
                 "a reasoned proposal — read it as a prompt, not a plan.")
    out: list[Suggestion] = list(taken or [])
    start = len(out)
    seen = {s.title for s in store.list_suggestions()} | {s.title for s in out}

    for exp in reversed(store.list_explorations()):
        if len(out) - start >= n:
            break
        template = _FOLLOW_UP.get(exp.failure_class)
        if template is None:
            continue
        signal = (exp.signals_produced or [exp.spec.get("signal_name", "the signal")])[0]
        title = template["title"].format(signal=signal)
        if title in seen:
            continue
        seen.add(title)
        hyp = store.get_hypothesis(exp.hypothesis_id)
        out.append(Suggestion(
            id=_reserve_id(out),
            title=title,
            question=template["question"].format(signal=signal),
            rationale=template["rationale"],
            what_it_measures=f"The same standard report as {exp.id}, on the "
                             f"modified score.",
            signal_name=_snake(f"{signal}_followup", "followup_signal"),
            signal_sketch=f"A variant of {signal} as described in the question.",
            family=hyp.family if hyp else "general",
            lineage=[{"target_id": exp.hypothesis_id,
                      "relation": template["relation"]}]
                    if store.get_hypothesis(exp.hypothesis_id) else [],
            novelty_note=f"Follow-up licensed by {exp.id}, classified "
                         f"{exp.failure_class}.",
            evidence_basis=f"{exp.id}: {exp.verdict}",
            pass_criterion=dict(DEFAULT_BAR),
            falsification_condition="mean IC indistinguishable from zero after "
                                    "the overlap correction, or a non-monotonic "
                                    "quantile profile",
            slot=slots[len(out) - start] if len(out) - start < len(slots) else len(out),
            source="offline",
            warnings=[warning],
        ))

    cat = catalogue.DEFAULT
    scored = {s.name for s in store.list_signals()}
    for feature in cat.all_features():
        if len(out) - start >= n:
            break
        if (not cat.scorable(feature.name) or feature.lookback == 0
                or feature.name in scored
                or not _rankable(feature.name)):
            continue
        title = f"{feature.name} ranks the universe on its own"
        if title in seen:
            continue
        seen.add(title)
        out.append(Suggestion(
            id=_reserve_id(out),
            title=title,
            question=f"Does ranking the liquid universe by {feature.name} "
                     f"predict forward returns at 5-20 sessions?",
            rationale=f"{feature.description}. No stored signal has ever been "
                      f"scored on it, so its marginal content is unmeasured.",
            what_it_measures="The standard report for a single-column score.",
            signal_name=_snake(feature.name, "coverage_probe"),
            signal_sketch=f"Cross-sectional rank of {feature.name}.",
            family="coverage",
            novelty_note="A coverage probe, not an idea: it exists because "
                         "nothing has measured this column.",
            evidence_basis="The feature catalogue, against the list of signals "
                           "already scored.",
            pass_criterion=dict(DEFAULT_BAR),
            falsification_condition="mean IC indistinguishable from zero after "
                                    "the overlap correction",
            slot=slots[len(out) - start] if len(out) - start < len(slots) else len(out),
            source="offline",
            warnings=[warning],
        ))

    return out[start:]
