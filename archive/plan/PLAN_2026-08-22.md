# brickbreak → running the lab

A plan for operating the alpha lab at throughput without destroying the thing
that makes its answers worth having.

The previous plan described a system to build. That system is built: stages A–E
shipped, the v1 list is complete, and a hypothesis can go from a sentence to a
scored, manifested, multiplicity-adjusted result without a human touching a
terminal. This plan describes what to do with it, and it exists because the
binding constraint moved the moment the machine started working.

Like its predecessor this document is **code-agnostic** where it can be. Where
it cites a measurement it cites the real one, taken on this machine against this
data, because the whole argument turns on which resource actually runs out
first.

Written 2026-08-21, replacing the refactor plan. That document's §5 layer
architecture, §10 conventions and its entire non-negotiables table remain in
force — they describe what exists, and nothing here relaxes them. It is
archived at `archive/plan/PLAN_2026-08-21.md`. `FINDINGS.md` and
`HYPOTHESES.md` are, as always, not superseded by anything.

---

## 1. Why this plan now

The refactor plan closed with a risk it did not resolve:

> **The lab can overfit as a whole.** Hundreds of cheap experiments against one
> finite history is a multiple-comparisons machine. The permuted-maximum bar
> handles one scan; it does not handle a thousand explorations across months.
> […] this needs an explicit design decision, not a hope.

This document is that decision.

The trigger is that the lab now works well enough to hurt itself. Three coding-agent
subscriptions and a laptop that runs 24/7 can dispatch on the order of forty
explorations an hour. `train` holds 749 sessions. At a ten-session horizon that
is roughly **seventy-five independent observations**, and the Šidák bar for a
maximum over *n* tests climbs accordingly:

| tests against a partition | required \|t\| | P(≥1 spurious hit at α=0.05) |
| --- | --- | --- |
| 1 | 1.96 | 5% |
| 40 | 3.22 | 87% |
| 100 | 3.47 | 99.4% |
| 1,000 | 4.05 | ~100% |
| 5,000 | 4.41 | ~100% |

Run flat out and the statistical validity of `train` is consumed in about a
week. The lab would not stop producing results; it would stop producing results
that mean anything, and it would do so silently, because every individual run
would still look exactly as rigorous as it does today.

The re-frame that drives everything below:

> A test is not an act of *reading* the data. It is an act of *spending* it.
> Generation is free, dispatch is not, and the two must be different stages
> with a gate between them.

---

## 2. What the measurements say

Taken 2026-08-21 against the live panel (1,513,342 rows × 92 columns, 831 MB
resident) on the i5 laptop that is meant to run this continuously.

**One exploration, end to end** — `JOB_20260821_141432`, a real Claude Code run,
18 agent turns, 3m55s wall clock:

| stage | time | note |
| --- | --- | --- |
| `load_daily_panel` | 7.7 s | charged **twice** per job — once in `job.run_job`, once again inside `runner.run_exploration` |
| forward returns, 3 horizons | 2.5 s | |
| `evaluate_signal`, full battery | 24.5 s | IC, decay, quantile profile, backtest, neutralisation |
| **harness total** | **~43 s** | peak RSS 4.2 GB |
| **agent turns** | **~3 min 12 s** | 85% of the job |

Three conclusions follow, and they reorder the whole problem.

**The laptop is over-provisioned, not under.** One harness slot serves about
five concurrent jobs; two fit in 16 GB at 4.2 GB peak, which serves about
eleven. There are three subscriptions. Compute is nowhere near binding, and
buying more of it buys nothing.

**Tokens are the second constraint, not the first.** The exploration prompt is
~940 tokens and flat. The suggestion prompt was 9,866 and growing without bound
in three separate places. That is a real problem and §7 deals with it, but it is
an efficiency problem, and efficiency problems have solutions.

**Sample is the constraint, and it is the one that cannot be bought.** Seventy-five
independent observations, one market, a 2020 floor, and a forward lane that
grows at exactly one session per day no matter how many agents are running.

### 2.1 The finding underneath the finding

`H039` scored mean IC −0.0227 at **t = −5.02** after the Hansen-Hodrick
correction, over 729 sessions. It clears the Šidák bar for any test count this
lab will realistically reach. It was classified `NO_SIGNAL` because its Q5–Q1
spread was 19.5 bps against a 40 bps round trip.

This is the most important single number in this document. With 1,500 names
across 749 sessions the lab has ample statistical *power*; a genuine IC of 0.02
announces itself at |t| ≈ 5. What it is short of is effects large enough to
survive costs.

> The lab is not primarily fighting significance. It is fighting magnitude.

Which is good news, because multiplicity punishes *marginal* findings hardest.
Anything actually worth trading arrives at t = 8 and does not care whether the
bar is 1.96 or 4.05. The real exposure is not "the budget runs out before we
find the good thing" — it is "the budget is spent accumulating marginal things
until one of them looks real."

That reframing is what the pass criteria and the dispatch gate below are built
around: **rank candidates by expected effect size, not by expected
significance.**

---

## 3. The three budgets

| budget | size | replenishes | binds when |
| --- | --- | --- | --- |
| compute | 4 cores, 16 GB, 24/7 | continuously | never, at three lanes |
| tokens | 3 subscriptions | on a rolling window | the prompt grows with the ledger (§7) |
| **sample** | ~75 independent blocks in `train`; forward at 1 session/day | **not at all** | immediately, and permanently |

Everything in this plan is a consequence of the third row. The design goal is
not to maximise explorations per hour. It is to **maximise information extracted
per unit of sample spent**, and those two objectives are in direct opposition
past a very low throughput.

### 3.1 The prior is the lever, not the threshold

Multiplicity accounting sets a bar. It does not improve the odds that what
clears the bar is real — that is set by the quality of the ideas going in:

| | shotgun | mechanism-first |
| --- | --- | --- |
| ideas dispatched | 100 | 20 |
| genuinely real among them | 3 | 5 |
| true positives found | ~1.5 | ~2.5 |
| false positives | ~5 | ~1 |
| **share of "discoveries" that are junk** | **~76%** | **~29%** |

Identical α. Identical statistics. The only difference is that the second lab
refused to dispatch anything without a named mechanism and a named counterparty,
and it tested a fifth as much and learned more.

The suggestion prompt already demands exactly this — *"who is on the other side
of the trade and why they keep taking it."* That requirement is the single
highest-leverage line in the repository, and §5 makes it a gate rather than a
request.

---

## 4. Non-negotiables, continued

Extending the refactor plan's table. Same rule: none of these may be something a
researcher has to remember.

| lesson | source | becomes |
| --- | --- | --- |
| A test spends the partition whether or not it finds anything | §1 | dispatch is rate-limited per partition per period; generation is not limited at all |
| Most of what disqualifies an idea never needed the label | `signal_mechanics` | a label-free pre-flight stage that costs no budget and precedes every dispatch (§6) |
| An idea rejected before dispatch is free | §1 | pre-flight rejections are recorded but do not enter `burden.count_tests` |
| Cherry-picking is a property of *sequence*, not intent | §5 | explorations are dispatched in pre-registered batches and corrected as batches |
| Significance is cheap here; magnitude is not | H039, t=−5.02 at 19.5 bps | candidate ranking is by expected spread against costs, never by expected t |
| Two counters of the same quantity will drift apart | `partition_summary` vs `count_tests` | any second count of "tests absorbed" derives from the first, or does not exist |
| A statistic not persisted cannot be corrected for | evidence lacked `t_stat` | anything the multiplicity layer reads is written by the runner in the same step that computes it |
| A test that writes to the real store pollutes the ledger | 18 fixture rows in `research_store` | tests write to an isolated store; the real one is not a test fixture |
| Families have different data floors | `nse.py` delivery is 2020+ | the panel version records its floor per feature, and a price-only family is not confined to a delivery-era window (§8) |

---

## 5. The dispatch pipeline

The core structural change. Today a suggestion is promoted and dispatched in one
motion. That is correct for a lab running three experiments a week and
catastrophic for one running three an hour.

Five stages, with the budget spent only at stage 4.

```
  ┌── 0. GENERATE ────────┐   continuous, unbounded, costs tokens only
  │   agents propose      │
  └───────────┬───────────┘
              ▼
  ┌── 1. PRE-FLIGHT ──────┐   label-free; costs compute only; kills ~70%
  │   no forward returns  │
  └───────────┬───────────┘
              ▼
  ┌── 2. RANK ────────────┐   by prior and expected magnitude, not cleverness
  │   the queue           │
  └───────────┬───────────┘
              ▼
  ┌── 3. PRE-REGISTER ────┐   a batch is frozen before any of it is scored
  │   N per period        │
  └───────────┬───────────┘
              ▼
  ┌── 4. DISPATCH ────────┐   ← the only stage that spends sample
  │   score, correct as   │
  │   a batch, record     │
  └───────────────────────┘
```

**Stage 0 — Generate continuously.** All three subscriptions, around the clock,
into a queue that may hold hundreds. This is the part the current system already
does well and the part that should be turned up, not down. It costs tokens and
nothing else. The research inbox becomes a deep queue rather than three slots.

**Stage 1 — Label-free pre-flight.** §6. The decisive new component.

**Stage 2 — Rank the survivors.** On things that predict effect size rather than
statistical luck: is there a named mechanism and a named counterparty; is the
falsification condition one that could actually trigger; is the expected spread
plausibly above 40 bps at all; is it orthogonal to what is already held; is its
family's window already spent.

**Stage 3 — Pre-register a batch.** Freeze *N* candidates before any of them is
scored, and record the batch in the manifest. Two things follow, and both matter
more than they look:

- Benjamini-Hochberg applies across the batch, which is far gentler than Šidák
  applied to a lengthening sequence.
- Cherry-picking becomes structurally impossible rather than merely discouraged.
  Five candidates chosen in advance is five tests. Five candidates chosen one at
  a time, each after seeing the last, is one test repeated five times, and the
  distinction is invisible after the fact unless it was recorded before.

**Stage 4 — Dispatch, tiered strictly.** `train` for exploration. `validation`
only for what already cleared `train`. `test` only for what cleared
`validation` — realistically three things, ever. The split already encodes this;
the discipline is never reaching for the next tier early, and the sample budget
ledger already refuses rather than filters.

### 5.1 The dispatch rate is a first-class setting

Not a convention, not a habit — a configured number of dispatches per partition
per period, visible on the dashboard alongside how much of the current period
remains. A starting proposal is **five per week against `train`**, zero against
`validation` until something clears `train`, and unlimited against `forward`,
which is the only lane where a test does not consume anything scarce.

The number should be defensible from the burden table rather than chosen for
comfort. Five a week is ~250 a year, which puts the bar near 3.7 — survivable
for a real effect, fatal for a marginal one, which is exactly the selection
pressure this lab wants.

---

## 6. Label-free pre-flight

The single highest-value component in this plan, and it is half-built already.

[`diagnostics.signal_mechanics`](src/alpha_eval/diagnostics.py) takes
`signal_col`, `date_col` and `symbol_col` — and no `forward_col`. Coverage,
turnover and rank autocorrelation are all computed without the outcome ever
being touched. But it is called from inside `evaluate_signal`, alongside the IC
and the backtest, so today there is no way to run it without spending a test.

Split it out. A pre-flight stage receives the same worktree-authored
`compute(df)` the dispatcher would have run, evaluates it on the full panel,
and looks at everything that does not involve `fwd_ret_*` or `excess_ret_*`:

- **Degeneracy and coverage.** Does it produce a real cross-section every
  session, or forty names on a good day? An `INSUFFICIENT_SAMPLE` verdict that
  costs nothing to reach is strictly better than one that costs a test.
- **Turnover.** A score churning 0.8 of rank per session cannot survive 40 bps
  round trip at any plausible effect size. This is arithmetic, not inference,
  and it needs no label.
- **Correlation against every existing signal, and against beta, size,
  volatility and momentum.** This is the important one. It requires no forward
  returns at all — and it is precisely how H038 would have been caught before it
  cost anything, since `r − beta·r_mkt` is visibly just `beta` the moment the two
  are correlated. The novelty objective (weakly-correlated alphas, not one
  strong one) becomes enforceable at zero budget.
- **Spent-family membership**, from lineage.

The load-bearing property: **a candidate killed here never enters
`burden.count_tests`, because it was never scored against the outcome.** Every
pre-flight rejection is budget preserved. If pre-flight kills 70% of the queue —
a conservative expectation given how much of the current failure taxonomy is
mechanical rather than statistical — it triples the effective sample budget
without touching a single statistical assumption.

Two constraints on the design. Pre-flight results are recorded as first-class
objects, so a rejection is visible and re-derivable rather than a silent drop.
And pre-flight must never be permitted to read a forward column, which is a
leakage-gate concern and belongs in the existing gate (§5.4 of the archived
plan), not in a convention.

---

## 7. Token economics of the loop

Fixed 2026-08-21, and recorded here because the same failure will recur wherever
prompts are assembled from a growing store.

The suggestion prompt had three unbounded terms and one badly-ordered one:

| section | was | growth |
| --- | --- | --- |
| every suggestion ever proposed | 499 tok | **unbounded**, ~220 chars each |
| the graveyard | 197 tok | unbounded, up to 250 chars each |
| the live ledger | 914 tok | unbounded, ~94 chars each |
| measured evidence | 4,087 tok | capped at 80 lines — **by recency** |
| the feature catalogue | 2,946 tok | fixed, but positioned sixth |

Projected to 300 hypotheses and 900 lifetime proposals that is ~88k tokens per
call, dominated by the inbox.

**What changed.** The inbox listing was removed from the prompt entirely. Its
only purpose was preventing restatement, and `_restates_existing` does that job
after generation against the same corpus for none of the tokens; it was extended
to cover prior suggestions as well as recorded hypotheses. The prompt was then
reordered static-first — role, catalogue, rules, worked example, all
byte-identical between calls — so the ~3.6k-token prefix caches instead of being
invalidated by whatever the store did since the last run. The requested count
was moved out of the opening line for the same reason.

**What is still owed.** The evidence cap truncates on the wrong axis: `[-40:]`
means the best result the lab has ever produced silently falls out of context
once forty newer ones exist. It should be family-level rollups with the extremes
retained verbatim. The ledger and graveyard should collapse to family
summaries once either exceeds a few hundred lines.

The general rule, which is the part worth keeping:

> A prompt section that exists to *prevent* something is almost always cheaper
> as a filter on the way out than as context on the way in.

---

## 8. Extending the sample

The only intervention in this document that increases the scarce resource rather
than rationing it, and it costs zero test budget.

`data/normalized/daily_bars.parquet` begins 2020-01-01, and
[`sources/nse.py`](src/research_data/sources/nse.py) records why: the unified
bhavcopy carrying `DELIV_QTY`/`DELIV_PER` 404s before ~2020.

**That constraint binds only on delivery-based families.** NSE's legacy bhavcopy
format — price, volume, trades, no delivery — extends back to the 1990s.
Momentum, reversal, volatility, sector diffusion and most of the catalogue need
no delivery column at all. Right now every family is confined to the shortest
common window because the panel has a single floor.

The work, in order:

1. **Establish the true floor per feature.** The catalogue already declares
   `available_as_of` per feature; make the panel honour it rather than
   intersecting everything to 2020.
2. **Pull the legacy-format archive** and normalise it into a long-history
   dataset version alongside `v1`. The rename map and corporate-action
   machinery already exist and are the hard part; this is a puller and a
   schema map.
3. **Verify pre-2020 delivery availability** in the older per-security delivery
   files before assuming the delivery families are stuck. This is unconfirmed
   and worth an afternoon.
4. **Split the sample budget ledger by dataset version**, so a price-only
   family spending twenty-year history does not draw down the delivery-era
   budget, and vice versa.

A price-only family tested on 2005-2026 instead of 2020-2026 gets roughly four
times the independent blocks. That is a larger improvement to this lab's
statistical position than any conceivable gain in throughput, and it is pure
engineering that an idle laptop should be doing while nothing else needs it.

The same argument applies, more weakly, to breadth: extending the universe past
the liquid 1,500 adds genuinely independent cross-section, and small caps are
where a small book has a structural advantage that large capital cannot contest.
Weaker than history because same-session names are correlated, but real.

---

## 9. Build order

Continuing the archived plan's stage lettering.

| stage | delivers | done when |
| --- | --- | --- |
| **F. Pre-flight** | `signal_mechanics` split out of `evaluate_signal`; a label-free verdict object; leakage gate extended to forbid forward columns in pre-flight | a candidate can be rejected for turnover, coverage or correlation without `burden.count_tests` incrementing |
| **G. The gate** | a deep queue; configured dispatch rate per partition per period; batch pre-registration written into the manifest before any member is scored | dispatching a sixth exploration in a five-per-week period is refused, not warned about |
| **H. Batch correction** | Benjamini-Hochberg applied across a pre-registered batch rather than a lengthening sequence; both counts derived from one function | `count_tests` and `partition_summary` cannot disagree — enforced by test, not by review |
| **I. Long history** | per-feature floors honoured by the panel; legacy bhavcopy pulled and normalised as a second dataset version; ledger split by version | a momentum hypothesis scores on 20 years and a delivery hypothesis on 6, from the same catalogue |
| **J. Prompt compaction** | evidence as family rollups with extremes retained; ledger and graveyard summarised past a threshold | the suggestion prompt is flat in the size of the store, not linear |

**F and G before anything else, and in that order.** They are what make
continuous operation safe. Turning throughput up before the gate exists is the
one move in this plan that cannot be undone, because the multiplicity count is
monotonic and there is no way to un-ask a question of a partition.

I is the highest expected value of the five and the least urgent, which is
exactly the profile of work that never gets done unless it is scheduled.

---

## 10. Risks and open decisions

- **The dispatch rate is a guess.** Five a week is defensible from the burden
  table but it is not derived from anything. It should be revisited once
  pre-flight is running and the real pre-flight kill rate is known rather than
  assumed at 70%.
- **Pre-flight can be gamed by the thing it gates.** If the queue ranking is
  itself model-authored and the model can see the pre-flight criteria, proposals
  will drift toward passing pre-flight rather than toward being true. The same
  argument the archived plan makes about who writes the pass criterion applies
  here, and probably has the same answer: the criteria are lab-owned, frozen,
  and not negotiable by the proposer.
- **A deep queue is a new place for stale ideas to accumulate.** A proposal
  ranked 400th on a Tuesday may be ranked 400th forever. Queue entries need an
  expiry, or a periodic re-rank, or both.
- **Batch pre-registration is only honest if the batch is honoured.** A batch of
  five where three are quietly abandoned mid-run because they looked
  unpromising is a batch of two with extra steps. Abandonment must be recorded
  and must still count against the budget.
- **Correlated tests are not independent tests, and Šidák assumes they are.**
  The bar computed by `burden` is conservative when proposals overlap, which is
  most of the time. It errs in the safe direction, but it means the reported bar
  is not the true bar and should not be quoted as though it were.
- **The forward lane is the only clean sample and it is also the slowest.**
  Everything that makes this plan work in the long run depends on signals being
  pre-registered onto the forward lane early, and the lane accruing while
  attention is elsewhere. Expect the validated column to stay empty for months;
  the archived plan was right that this must look normal rather than broken.
- **Shorter timeframes are not the escape hatch they appear to be.** Higher
  frequency does buy more non-overlapping windows, but the opening tick data is
  ~5s snapshots with volume smeared behind price, H006 already found the traded
  intraday payoff worse than the D+5 label, and halving the holding period
  roughly doubles cost drag per unit of time against an edge that is already
  fighting 40 bps. Recorded here as considered and rejected, not overlooked.
- **This plan optimises for correctness of inference and will feel slow.** It
  deliberately trades throughput — the thing that is abundant — for sample
  integrity, the thing that is not. If it ever feels like the lab is
  underutilised, that is the design working, and the correct response is to
  point the spare capacity at §8 rather than at `train`.

---

## 11. What carries forward

Everything in the archived plan that describes the system as built: the four
objects, the idea graph, the layer architecture of §5, the dashboard, the
conventions of §10. None of it is relaxed here. The sample budget ledger, the
leakage gate, the manifests and the failure taxonomy are what make a rationed
dispatch enforceable rather than aspirational — without them this document would
be a set of good intentions.

What changes is the operating model layered on top:

- **generation and dispatch become separate stages** with a gate between them,
  where today promotion and dispatch are one motion;
- **the budget is spent at stage 4 of five**, not at stage 1 of 1;
- **the queue is deep and the throughput is high**, and neither of those facts
  touches the sample;
- **the sample itself is treated as extensible** (§8) rather than as fixed.

What retires: the assumption, implicit in the current Explore console, that a
good proposal should be run promptly. Promptness was the right instinct when
running an experiment was expensive in effort. Now that it is cheap in effort
and expensive in sample, it is the wrong one.
