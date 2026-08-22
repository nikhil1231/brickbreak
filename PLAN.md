# brickbreak → the discretionary lab

A plan for finding out whether contextual judgement beats a screen, without
spending the sample to discover that it does not.

`MISSION.md` is the authority. This document is how the machine underneath it
is operated, and it replaces the operating plan of 2026-08-21, archived at
`archive/plan/PLAN_2026-08-22.md`. That document's §5 dispatch pipeline, §6
label-free pre-flight, §8 long-history work and **both non-negotiables tables**
remain in force without amendment — they describe a system that exists and
nothing here relaxes any of it. The refactor plan (`archive/plan/PLAN_2026-08-21.md`)
still owns the layer architecture. `FINDINGS.md` and `HYPOTHESES.md` are, as
always, superseded by nothing.

Written 2026-08-22.

---

## 1. What changed, and what did not

The previous two plans were about a **signal**: a function over the whole panel,
scored by rank IC and a quantile spread. That machine works. It is not being
retired, and the pivot is not a repudiation of it — it is a second unit of work
placed beside it, because the mission's question cannot be phrased in the first
one's vocabulary.

> Can an AI, given rich point-in-time context, identify unusually attractive
> opportunities better than strong simple quantitative baselines?

That sentence has no cross-sectional score in it. It has a **case** — one
situation, as a trader could have known it — and a **decision** committed
against that case before the future is visible. Nothing in the signal path can
express "the AI took 61 of these 500 and skipped the rest, and here is whether
that selection beat top-N-by-score on the same 500".

**What carries forward untouched**, and it is almost everything below the unit
of work: point-in-time access and forward labels (`research_data.frame`), the
partition split and its purge, the sample-budget ledger, the dispatch gate,
multiplicity accounting, the leakage guards, session-clustered and
Hansen-Hodrick inference, the manifests, the failure taxonomy, the hypothesis
ledger and the idea graph. A replay spends the partition exactly as an
exploration does and is counted by the same code.

**What retires** is the assumption that a result *is* a signal — visible in
`spec.validate_pass_criterion`, which speaks only in mean IC, quantile spread
and monotonicity. None of those is defined for a selection.

**What is demoted** is the opening-window family. It owned thirteen top-level
CLI commands and the dashboard's landing view, which made one belief about the
market look like the shape of the project. It now lives under
`src/research/families/` behind `python -m src.cli family opening-window`, with
its bracket simulator lifted into `alpha_eval.trade_sim` where the rest of the
lab can use it. Nothing was deleted. `tests/test_architecture.py` enforces the
one-way dependency.

---

## 2. The loop

```
  IDEA                     a sentence, from suggest or from a person
    │
  OPPORTUNITY DEFINITION   frozen: generator, sample, blocks, judge, bar
    │
  CANDIDATE GENERATION     broad, high-recall, never tuned
    │
  CASE CONSTRUCTION        point-in-time by test, anonymised by default
    │
  DECISION ─────────────┐  AI and every baseline, on identical cases
    │                   │
  ══ SEAL ══════════════╪═ decisions hashed and committed
    │                   │
  REVEAL                └─ the only phase that spends sample
    │
  EVALUATION               selector lift, not strategy return
    │
  LEARNING                 which reasoning preceded which outcome
```

Six phases, six commands, and the seal between the fourth and the fifth is the
experiment. MISSION §6 asks that a decision never be revised after subsequent
data is seen; an instruction to that effect is worth nothing, so `reveal`
refuses to run unless the decisions on disk hash to what was committed.

### 2.1 The distinction the whole design rests on

Candidate generation and discretionary selection are different jobs.

| | generation | selection |
| --- | --- | --- |
| purpose | find situations worth examining | the thing under test |
| bias | broad, high recall | whatever the judge brings |
| tuning | **none** | n/a — it is measured, not fitted |

A generator tuned until it looks profitable has stolen the experiment: the lift
is then measured against a baseline that already contains the answer. Generator
parameters are frozen in the definition, and re-tuning one is a new test.

The instinct this reverses is the one every screen in this repository encodes.
`families.opening_window.screener` has eight narrowing stages. That is right for
a mechanical strategy and wrong here, because **a narrow generator flatters the
selector by hiding its hard cases.** The default is `liquid_universe` — every
tradeable name, every session, a constant score — precisely so that no screen
does any of the work.

---

## 3. The fourth budget

The archived plan named three: compute, tokens, sample. Sample was the binding
one and the only one that cannot be bought. That is still true, and a fourth now
sits in front of it.

| budget | size | replenishes | binds when |
| --- | --- | --- | --- |
| compute | 4 cores, 16 GB, 24/7 | continuously | never |
| tokens | 3 subscriptions + API | rolling | — |
| **cases** | ~500 per replay | per replay, at a price | immediately, at one call per case |
| **sample** | ~75 independent blocks in `train` | **not at all** | permanently |

**Cases are the new near-term constraint.** A broad generator over `train`
yields ~500,000 situations. At one model call each that is not an experiment,
it is a budget request. So the sampler is part of the frozen definition rather
than something applied afterwards, and the default is 500 cases stratified
across sessions.

Measured on this data: a case is ~1,350 tokens, a replay arm ~500 calls. On the
API path that is minutes and single-digit dollars; on the subscription CLI it is
serial and slow, which is why the CLI is for working on a prompt and the API is
for running a replay.

### 3.1 The take rate is the real multiplier, and it is small

Measured on the first live replay (`RPL_20260822_020607`, 8 cases, broad
`liquid_universe` generator, Claude via the sealed CLI):

> **take rate 0%.** Six SKIP, two WATCH, no TAKE. Zero failed calls.

That is not a defect and the reasoning was not thin — each decision named
specific unusual features, argued a real competing explanation (one cited a
failed high-volume spike *earlier in the same case's own window*), gave a
concrete invalidation level, and assessed asymmetry explicitly against the
0.40% cost floor. It is the design working: a broad generator shows mostly
ordinary situations, and the prompt says in as many words that skipping is free
and that "nothing unusual" is the right answer most of the time.

The consequence is arithmetic and it governs how a replay is sized:

    cases needed  ≈  takes wanted  /  take rate

At a take rate somewhere in 5–15%, a replay needs **300–600 cases to yield
30–60 takes**, and 30 takes is the floor at which any breakdown by regime or
sector means anything. A 50-case pilot cannot answer the mission's question; it
can only estimate the take rate — which is a legitimate and cheap thing to spend
50 cases on, and should be done before committing to a full replay against a
generator nobody has run yet.

Two corollaries worth stating before they are discovered the expensive way:

- **A zero take rate is a valid outcome and the report says so** rather than
  manufacturing a contrast — `INSUFFICIENT_SAMPLE`, and every lift reads "—"
  rather than a number.
- **The take rate is a property of the generator and the prompt jointly.**
  Narrowing the generator raises it, which is a reason to reach for a narrower
  generator that is *not* about making the numbers work. Change one at a time,
  and remember that changing the prompt is a new test.

### 3.2 What 500 cases can and cannot detect

500 cases spread over a few hundred sessions at a ten-session horizon is
**tens of independent blocks**, not hundreds. `evaluate` reports
`independent_blocks` in the headline for exactly this reason — and note that
§3.1 makes this worse than it looks, because only the *taken* cases carry the
contrast.

Measured here, on 60 coin-flip selectors against synthetic data with a realistic
session factor:

| | null selector |
| --- | --- |
| corrected \|t\| > 1.96 | **13.3%** (nominal 5%) |
| standard deviation of t | **1.40** (should be 1) |
| cleared the frozen bar | **1 in 60** |

The first two rows are the residual over-rejection AGENTS.md already documents
at this block count, and the corrections are working — they are simply unable to
invent independent observations. The third row is the point:

> A bar denominated in **basis points** rejected the same null selectors 98% of
> the time, where a bar denominated in **t** would have passed 13% of them.

This is the same conclusion the archived plan reached from H039 — the lab is
fighting magnitude, not significance — arriving from a different direction. It
is why `MIN_MEANINGFUL` in `opportunity.py` is in bps with a floor at the 40 bps
round trip, and why the report says in words not to promote on a t-statistic.

---

## 4. Non-negotiables, continued

Extending both prior tables. Same rule: none of these may be something a
researcher has to remember.

| lesson | source | becomes |
| --- | --- | --- |
| A decider is not frozen the way a function is | a prompt is editable; a signal is not | test identity is (prompt hash, model, case-set hash); any change counts as a new test |
| A model may remember what a named stock did in a named quarter | the leak is in the weights, not the frame | cases are anonymised **by default**; revealed identity is a deliberate paired control (H042) |
| A judge that can read a file can read the outcome | `runner.agent` defaults to Bash/Read/Write | the decision path passes `allowed_tools=()` and an empty directory, asserted by test |
| A dropped failure is a changed population | baselines see every case | every case yields a decision, including failures; `failure_summary` reports them |
| Selectivity is confounded with skill | a 12% arm beats a 100% arm on any above-average pool | baselines run at the AI's own realised take rate |
| A stale baseline is a weak baseline | a single early fit drifts | `rank_model` refits walk-forward; the bias must run against the AI |
| A control from another session carries that session's market | H020 | every contrast is a per-session paired difference |
| A narrow generator hides the selector's hard cases | §2.1 | generator parameters are frozen; re-tuning is a new test |
| A correction cannot invent observations | §3.1, 13.3% at nominal 5% | the bar is in bps; `independent_blocks` is in the headline |
| An unresolved analogue is a leak wearing a disguise | a case 3 sessions old has not resolved at h=10 | analogues and the rank-model fit filter on `resolved_by`, never on their own date |

---

## 5. Where the budget is spent

Not at `freeze`, and not at `decide`. A replay that is defined, generated, built
and judged has read **nothing** about what happened next — it has spent tokens
and compute, both replaceable. `reveal` is the first moment the partition is
touched, so `gate.enforce_dispatch_gate` and `ledger.enforce_permission` fire
there.

This is the same economics as label-free pre-flight in the archived plan §6, and
for the same reason: **a candidate killed before the outcome is read costs
nothing.** A replay whose cases turn out to be degenerate, whose judge failed on
half of them, or which was simply thought better of, can be abandoned for free.

The dispatch rate of five per week against `train` is unchanged and now covers
replays too — a replay files an `Evidence` record under `signal_id =
"replay:<id>"`, so `runner.burden` counts it beside every signal ever scored,
and Benjamini-Hochberg sees it, without either knowing the discretionary package
exists.

---

## 6. What is owed

| stage | delivers | state |
| --- | --- | --- |
| **K** | families demoted, `trade_sim` extracted, CLI namespaced | **done** |
| **L** | opportunity, generators, case; future-blindness test | **done** |
| **M** | prompt, decider, both providers, sealed execution | **done** |
| **N** | replay, seal, baselines, outcomes, budget at reveal | **done** |
| **O** | selector report, paired contrasts, calibration, null control | **done** |
| **P** | `inconclusive`/`frozen` statuses; forward registration of a frozen decider | statuses done; forward lane **owed** |
| **Q** | docs; a read-only Replays view in the dashboard | docs done; UI **owed** |
| **R** | the memorisation control (H042) run as a paired replay | **owed, and it gates everything** |
| **S** | long-history extension — archived plan §8 | **owed, and now worth more** |

**R before any finding is believed.** H042 is the control that licenses reading
an anonymised result as judgement rather than as recall. It is two replays on
one case set differing in a single field, and until it has been run every
discretionary result in this lab carries an asterisk.

**S is worth more than it was.** The archived plan argued that the legacy
bhavcopy archive reaches 1995 and would give a price-only family roughly four
times the independent blocks. §3.1 above is the sharpest possible statement of
why that matters: a case-budgeted loop is short of independent blocks
specifically, and history is the only thing that buys them. It remains the
highest-expected-value idle work in the repository and the least urgent, which
is exactly the profile of work that never happens unless it is scheduled.

---

## 7. Risks and open decisions

- **The counterparty question is unanswered, and it is the honest weak point.**
  The archived plan's highest-leverage line is the demand that a proposal name
  who is on the other side of the trade and why they keep taking it. For a
  discretionary judgement the answer is genuinely unclear. If nobody is
  persistently on the other side, a measured edge is a data artefact — and it
  will not announce itself as one. Recorded in H041's rationale rather than
  argued away.

- **The judge can be gamed by the thing it is judged on.** Prompt tuning against
  a visible score is overfitting with extra steps, and it is *cheap* — which
  makes it the likeliest way this lab hurts itself now. The prompt hash counting
  as test identity makes it visible; it does not make it hard. A prompt should
  be worked on against cases whose outcomes have not been revealed, and the
  discipline is not yet enforced by anything.

- **Tag analysis is association, not cause.** A tag is claimed by the judge, not
  assigned by the lab, so a tag that reads well may only mark the cases where the
  judge felt articulate. `_by_tag` says so where it prints.

- **WATCH is untested as a category.** It is currently scored as a non-position.
  Whether it carries information — whether WATCH outperforms SKIP — is a real
  question this loop can answer and has not.

- **The case is a design choice, not a given.** Sixty sessions of bars, ten
  blocks, five analogues. Every one of those is a parameter nobody has varied,
  and varying them is itself a multiple-comparisons exercise against the same
  sample. Treat the case format as frozen infrastructure and change it
  deliberately, in the open, with the change recorded — it is part of the test
  identity in spirit even where it is not yet in the hash.

- **This plan still optimises for correctness of inference and will still feel
  slow.** If the lab feels underutilised, that is the design working, and the
  correct response remains to point the spare capacity at §8 of the archived
  plan rather than at `train`.
