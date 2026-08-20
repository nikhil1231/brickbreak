# brickbreak → alpha lab

A plan to refactor this repository from *"Abhijeet strategy research code"* into a
general-purpose alpha research environment: a small autonomous laboratory that can
ask hundreds of disciplined questions cheaply, keep every answer, and never
rediscover its own dead ends.

This document is deliberately **code-agnostic**. It describes objects, contracts
and stages, not modules, signatures or file layouts. Implementation planning
comes after this is agreed.

The refactor starts at the data layer, because that is where every failure in
this project's history has actually lived: §5.1 and §5.2 define a single module
that owns all market-data access and replaces the current chronological holdout
with versioned, purged, quarter-level splits.

Written 2026-08-20, replacing the phase-gated single-strategy plan. The prior
plan's content survives in `FINDINGS.md` and `HYPOTHESES.md`, which are the
project's actual memory and are **not** superseded by this refactor.

---

## 1. Why pivot now

Seven phases produced one positive-expectancy rule (H024), which reversed sign
out of sample, and one narrow surviving claim: selection *inside* the contraction
screen carries out-of-sample information at t>3 against the same-day pool, in
three independent rankings, on data none was fitted to. Nothing has beaten
buy-and-hold risk-adjusted in either window.

The valuable output of those phases is not any hypothesis. It is the accumulated
set of **things that are true about doing this work correctly** — four distinct
non-price lookaheads caught, clustered inference, permuted-maximum bars,
same-session matching, cash-charged annualisation, the uselessness of purged-block
stress as a promotion gate. That knowledge is currently encoded as prose warnings
in `AGENTS.md` and as conventions inside one strategy's code. It should be
encoded as **architecture**, and then reused across every future question.

The re-frame that drives everything below:

> The primary question is not *"did this strategy make money?"* but
> *"does this signal contain predictive information, under what conditions, and
> how robustly?"*

Strategy construction is a later, separate activity. Conflating the two is what
contaminated Phases 2.5 and 2.9.

---

## 2. Non-negotiables — lessons that become architecture, not convention

Each of these was learned expensively. In the new system, none of them may be a
thing a researcher has to *remember*.

| lesson | source | becomes |
| --- | --- | --- |
| The screener read date D's own close | H015 | `research_data` cannot express "today's close" without an explicit, logged, reviewed escape hatch |
| Normalisers are lookaheads too | 2026-08-20 | every derived feature declares its inputs; the catalogue rejects a feature whose denominator is unlagged |
| A current snapshot attribute is a lookahead | H030 | every feature carries `point_in_time: true/false`; non-PIT features are blocked from ranking/scoring by default |
| Gap-between-observations leaks inside a window | `time_above_open_frac` | intraday features are auto-tested by appending later bars and requiring invariance at `t` |
| Row-level t-stats inflated ~2.9x | H016 | every statistic in the standard report is clustered by session; the naive one is shown beside it, never alone |
| Matched controls must be same-session | H020 | matching is a first-class primitive with the market-offset diagnostic printed every run; a non-zero offset fails the run |
| A search reports a maximum | H019 | any scan's significance bar is the permuted maximum over the scanned family, computed automatically |
| Price the label before believing it | H018 | every path/outcome taxonomy is run through the canonical payoff before it may be used as a target |
| Charge a book for its cash | 2026-08-20 | the canonical backtest annualises across the calendar span, always, with no per-rule option |
| Purged-block stress is not a promotion gate | H032 | reported as a diagnostic, structurally excluded from any pass criterion |
| A score built by subtracting a factor is a sort on that factor | H038 | neutralisation diagnostics are mandatory, and a score is auto-projected off what it adjusts for |
| Write bars in units of the effect, not its sign | H037 | pass criteria require a *fraction of the exploration effect retained*; sign tests are rejected by the spec validator |
| Significance is not size | Phase 2.8 | every effect is reported in decision units (win rate by band, bps per trade) beside its t |
| The holdout sat *before* the training window, one window, one regime | Phase 3 | versioned quarter-level splits with purging, plus a permanent chronological forward lane (§5.2) |
| Thirty modules each opening their own parquet | this refactor | one data module, and direct file access from experiment code is a build error |
| Don't name a feature after a mechanism the data can't see | `persistent_demand` | catalogue entries require a description of what is *measured*; mechanism goes in the hypothesis, not the feature name |

### 2.1 The data budget is part of the architecture

**2020-2023 has been read twice and is spent for the hypothesis families that
read it.** The only wholly untainted data is sessions after 2026-08-18.

The new system needs a **sample budget ledger**: a first-class record of which
partitions have been touched by which experiment, in which role (train /
validation / test / forward). Reading a partition in a confirmatory role burns it
for that hypothesis family, permanently and visibly. The runner refuses such a
run rather than filtering it — the existing fence-raises-rather-than-filters
behaviour, generalised beyond one hardcoded date.

The ledger and the split (§5.2) are two halves of one mechanism: the split says
what each partition *is*, the ledger says what has already been *spent* out of
it.

---

## 3. The four objects

Everything in the system is one of four things. This is the data model, the URL
structure, and the mental model.

```
Hypothesis  →  Exploration  →  Signal  →  Evidence
```

**Hypothesis** — a durable idea with a stable ID, in natural language, with an
economic or behavioural rationale. *"Stocks that resist a market selloff
outperform on the rebound."* It has a status, a lineage, and it lives forever.
Statuses: `proposed · exploring · promising · rejected · validated · decayed`.

**Exploration** — one concrete investigation of a hypothesis. Bounded, dated,
reproducible, with an immutable manifest. Produces zero, one, or several
candidate signals plus a verdict. An exploration is never edited after it runs;
a changed question is a new exploration.

**Signal** — a named, versioned, computable cross-sectional score over the
universe. `resilience_rel_20d_v2`. It has a definition, a coverage profile, a
turnover profile, and an owner hypothesis. Signals are the unit of comparison and
combination.

**Evidence** — one measured result attached to a signal or hypothesis, tagged
with the window it was measured on, the role that window played, and the
manifest that produced it. Evidence accumulates; it is never overwritten.
Supporting and contradicting evidence sit side by side on the hypothesis page.

The three-way distinction already enforced in `HYPOTHESES.md` — *generation*,
*exploratory*, *confirmatory* — is a required field on every piece of evidence,
because it determines how much the evidence is worth.

### 3.1 The idea graph

Hypotheses are nodes; typed edges connect them:

```
relative resilience
├─ specialises → sector-relative resilience
├─ specialises → beta-adjusted resilience
├─ conditions  → resilience during volatility spikes
├─ contradicts → momentum reversal at 20d
└─ subsumed-by → generic momentum      (added automatically by neutralisation)
```

Edge types worth having: `specialises`, `generalises`, `conditions-on`,
`contradicts`, `subsumed-by`, `adjacent-to`, `retest-of`.

The graph exists so that a failure produces a *branch*, not a restart. When
something dies, the system proposes nearby unexplored nodes rather than dreaming
up an unrelated strategy. It is also the guard against silently retesting the
same idea under a new name — a rule `AGENTS.md` already imposes on humans.

---

## 4. System architecture

```
  idea (natural language)
    ↓
  AI research planner            → an experiment spec, human-amendable
    ↓
  research job runner            → git worktree, isolated, manifest-stamped
    ↓
  Claude Code CLI worker         → writes experiment code against the data module
    ↓
  research_data                  → THE ONLY DOOR: point-in-time features,
                                   universes, benchmarks, forward labels,
                                   versioned deterministic splits
    ↓
  automatic leakage tests        → run before results are accepted
    ↓
  standard alpha report          → the same battery for every signal
    ↓
  canonical backtest             → one portfolio construction, for everything
    ↓
  AI interpretation              → verdict + failure class + follow-ups
    ↓
  hypothesis ledger + idea graph → evidence accrues, branches proposed
```

Two properties matter more than the individual boxes:

1. **The worker cannot reach the data except through `research_data`.** Arbitrary
   parquet reads are how three of the four lookaheads got in. Raw file access
   from experiment code is a build error, not a style preference.
2. **The worker's freedom is in the *code*, not in the *output*.** Every job ends
   by emitting a structured result conforming to a schema. The dashboard ingests
   the schema, not a terminal transcript.

---

## 5. Layer by layer

### 5.1 `research_data` — the only door to market data

Everything above the data layer is worthless if the data layer is wrong, and
every failure in this project's history has been a data-layer failure. So the
refactor starts here: **one module that is the sole route by which any experiment
reaches market data.** Nothing else opens a parquet file.

**Naming.** `data/` is already the on-disk store of parquet files, so a Python
package of the same name would be a permanent source of confusion. The module is
`research_data`; `data/` stays what it is — bytes on disk that only
`research_data` is allowed to open.

**Responsibilities, all of them:**

| responsibility | what it guarantees |
| --- | --- |
| point-in-time features | nothing knowable only after the stated timestamp is reachable |
| universes | point-in-time membership, survivorship handled, ETFs and defects excluded |
| adjusted vs raw prices | indicators get adjusted; tradeability claims get raw; the choice is explicit at every call |
| benchmarks | market, sector and peer series that are same-session by construction |
| forward labels | the only route to the future, and labelled as such so it can never be an input |
| splits | deterministic, versioned, purged partitions — identical for every experiment |
| catalogue | machine-readable metadata for every feature (§5.3) |
| lineage | dataset hashes and version stamps for the manifest |

The API shape the researcher works with:

- `frame.asof(date)` — the panel as it was knowable at a moment, not a
  date-filtered view of a fully-built panel.
- `feature.lag(n)` — explicit, and the default for anything not declared knowable.
- `forward_return(horizon)` — the only way to obtain the future.
- `universe(date)`, `market()`, `sector()`, `peers()`.
- `split(version).train / .validation / .test / .forward` — partitions, never
  raw date ranges.
- `match(controls)` — matched-set construction with the same-session constraint
  and the market-offset diagnostic built in.

### 5.2 Deterministic dataset splits

**The problem being fixed.** The current arrangement is backwards: the holdout
(2020-04 → 2023-08) sits *before* the exploration window (2023-08 → present).
Rules were developed on recent data and tested on older data. That inverts the
direction of every real deployment, tests nothing about forward robustness, and
hands each window a different regime — the holdout window's market compounded at
41.78% at a Sharpe of 2.25, which is why H026 could beat the pool by t=4.98 and
still fail the portfolio clause. One window, one regime, one shot, and no way to
tell a regime effect from a decay effect.

**The design.**

- **Assign whole calendar quarters** to `train` / `validation` / `test` by a fixed
  seeded shuffle. Chronological order is preserved *within* each quarter; only
  the assignment of quarters is randomised. This buys regime diversity in every
  split without the leakage of shuffling individual stock-days.
- **Purge around every cross-set boundary** so that overlapping forward-return
  windows cannot cross. Sized to the dataset version's declared maximum horizon.
- **Version the split manifest and store it beside the dataset.** Every
  experiment uses exactly the same partitions unless a new dataset version is
  deliberately created. The split version goes in every manifest.

The panel holds **27 quarters** (2020Q1 → 2026Q3), median 62 sessions each. That
is a small number of blocks, which drives most of the refinements below.

#### Purging, and what it costs

Leakage across a boundary is directional, so the purge should be too:

- **Purge**: drop rows from the *end* of a quarter whose forward-return window
  reaches into a following quarter that belongs to a different set. Length = the
  version's maximum forward horizon.
- **Embargo**: drop rows from the *start* of a quarter following a different-set
  quarter, whose features overlap the neighbour's label window. Shorter than the
  purge, because it blocks a second-order leak (a lookback aggregate spanning
  the neighbour's outcome path) rather than a first-order one (the outcome
  itself). **Built at `max_horizon // 4` = 5 sessions**; a full-horizon embargo
  was measured at 33.0% of train sessions against 20.6% at five, for the
  second-order case only.
- **The panel's own tail is purged too.** `forward` begins where the panel ends,
  so a train row twenty sessions before the cutoff carries a label determined by
  sessions inside the forward lane. This is the one boundary that exists in every
  split regardless of the draw, and it was missing from this plan until a test
  caught it.

**Purge asymmetrically: always drop from the lower-priority set, never from
test.** Train gives way to validation, validation gives way to test. Evaluation
sample is the scarce resource; training rows are not.

**Measured on the real panel** (split `v1`, seed 0, `max_horizon=20`): 17 of 26
internal boundaries are cross-set, plus the panel/forward boundary. The purge
drops 240 of 1,647 sessions — **14.6% of the panel, 22.7% of raw train sessions,
2 of 372 validation sessions, and none at all of test.** Train keeps 749 clean
sessions, validation 352, test 306. The manifest states this rather than leaving
it to be discovered later.

Because the purge length is a function of the maximum horizon, **`max_horizon` is
a property of the dataset version.** An experiment requesting a longer horizon
than its version was purged for is an error, not a warning.

#### Constraints on the draw

A blind seeded shuffle over 27 blocks can produce a degenerate assignment — all
of 2020 in test, or a test set that never sees a drawdown. So the draw is
seeded *and* constrained, with the constraints recorded in the manifest:

- each set spans at least three distinct calendar years;
- each set contains at least one high-volatility quarter and one trending
  quarter, by a regime label fixed before the draw;
- no set receives more than **three** consecutive quarters. Two was the original
  proposal and it is measurably worse: forcing alternation creates *more*
  cross-set boundaries and therefore more purging — 21 boundaries and 26.4% of
  train lost at two, against 17 and 20.6% at three. Three consecutive quarters is
  nine contiguous months, nowhere near rebuilding a chronological split.

The draw iterates seeds until the constraints hold, and the manifest records the
seed, the constraints and the resulting assignment. Reproducible, and honest
about not being uniformly random.

#### The test set is drawn once and never re-drawn

A subtlety worth building in from the start: re-shuffling to get a second opinion
reads the test data twice, which is exactly how 2020-2023 was spent.

- **Test quarters are frozen at dataset-version creation.** They are read once per
  hypothesis, at promotion, and the read is logged to the ledger.
- **Train and validation may be re-drawn** within the remaining quarters under a
  sub-seed, giving k-fold-style repetition and split-stability diagnostics
  without touching test.
- A new dataset version that re-draws test is a deliberate, recorded act with a
  stated reason — not something a researcher does by passing a different seed.

#### Two axes of generalisation, kept separate

The shuffled split answers *does this work across regimes?* It cannot answer
*does this still work?*, because a shuffled test set is interleaved with training
in time. Alpha decay is invisible to it.

So the module exposes a fourth partition, `forward`: **all sessions after the
dataset version was created**, strictly chronological, never shuffled, growing by
one session a day. Every promoted signal accrues forward evidence automatically.
The two axes are reported separately and never averaged, because they answer
different questions:

| partition | question | failure mode it catches |
| --- | --- | --- |
| shuffled `test` | does it work across regimes? | regime-specific fitting |
| chronological `forward` | does it still work? | decay, crowding, structural change |

#### Reconciling the split with the burned window

This is the one genuinely awkward part and it needs deciding, not glossing.
2020-2023 has been read twice. A seeded shuffle will inevitably assign some of
those quarters to `test`.

The proposal: **prior exposure is a property recorded per quarter, not a reason to
discard the quarter.** Each quarter carries a `prior_exposure` list naming the
hypothesis families that have already read it. Then:

- a genuinely new signal, unrelated to anything previously tested, may use those
  quarters as test with a noted caveat;
- any descendant of the opening-window family or the resilience family — anything
  the idea graph links to H024, H026 or H034-H038 — is **blocked** from scoring on
  them, by the ledger, automatically;
- the `forward` partition is the only unqualified confirmatory evidence for those
  families, and the interface should say so plainly rather than showing a clean
  green tick.

The alternative — declaring all of 2020-2023 permanently unusable — throws away
55% of the history to protect against a contamination that only applies to two
hypothesis families. The graph-aware version is stricter where it matters and
cheaper everywhere else, and it degrades honestly: when in doubt about lineage,
the ledger blocks.

### 5.3 The feature catalogue

The catalogue is the agent's map of the world, so it never has to grep source
files to discover what exists. It lives inside `research_data` because PIT status
is a data-layer fact. Every feature carries:

| field | why |
| --- | --- |
| `available_as_of` | the timestamp at which this value is knowable |
| `lookback` | how many sessions of history it consumes |
| `adjusted / raw` | indicators on adjusted prices; tradeability claims on raw |
| `point_in_time` | false for snapshot attributes — sector, index tier |
| `universe_coverage` | what fraction of symbol-days it exists for, over time |
| `inputs` | the features it derives from, so PIT status is inherited |
| `max_horizon_safe` | the longest forward horizon it can be paired with |
| `known_caveats` | censoring at zero, illiquidity bias, archive defects |
| `owner` | which pipeline stage produces it |

Initial catalogue, all already computable here: price OHLCV, turnover, delivery %,
market and index series, sector label, index tier, ATR and volatility measures,
Bollinger width, base depth, relative strength, rolling highs/lows and distance to
them, gap, opening-window tick features, corporate actions, rename lineage,
listing age, liquidity percentiles, market regime labels.

Two catalogue rules that follow directly from this project's history:

- A feature whose `point_in_time` is false may be used for *stratification*
  (report by sector) but not for *scoring* (rank on sector), and the module
  enforces the difference rather than documenting it.
- **PIT status is inherited from inputs.** This is what would have caught the
  unlagged `median_vol_20` denominator automatically — a clean numerator over a
  contaminated one.

### 5.4 Leakage tests as a gate

Standard tests run automatically on every experiment, before its results are
accepted:

- append-future-bars invariance for anything computed at a time `t` inside a
  window;
- shuffle-the-future invariance for cross-sectional scores;
- a PIT audit that recomputes sampled rows from the as-of frame and requires an
  exact match;
- a **split-integrity check** — no symbol-day appears in two partitions, and no
  training row's forward window reaches into validation or test.

An experiment whose leakage tests fail does not produce a "result with a caveat".
It produces a failure.

### 5.5 The experiment specification

Every exploration is defined by a spec before it runs — generated by the planner,
amendable by hand, validated before dispatch. It names:

- hypothesis ID and the question in one sentence;
- universe, dataset version and **partition** (train / validation / test /
  forward) — never a hand-written date range — checked against the sample-budget
  ledger before dispatch;
- the signal(s) to construct, and their parameter neighbourhood;
- the outcome(s): horizons, and whether the canonical payoff applies;
- the standard report to run (usually: all of it);
- neutralisation set;
- pass criterion, in units of the effect — required, and validated as not a sign
  test;
- what would falsify it.

The spec is the contract between the human, the planner and the worker. It is
also what makes two runs comparable.

### 5.6 Immutable manifests and lineage

Every experiment emits a manifest it cannot edit:

code hash · dataset version and hash · **split version** · catalogue version ·
hypothesis ID · spec · parameters · universe · partition · model used · prompt ·
runtime · environment · result hash.

This is what lets the dashboard answer **"why did this result change?"** instead
of the answer arriving six hours later as "the parquet was stale". Dataset
hashing is the cheap part and pays for itself the first time it fires.

### 5.7 The Claude Code job runner

The web layer never executes generated shell text. It creates a **job**, and a
worker consumes it:

```
dashboard → job spec → queue → worker → Claude Code CLI (headless, JSON output)
          → isolated git worktree → research_data → leakage tests
          → experiment runner → experiment_result.json → ingest → dashboard
```

Design points:

- **Isolated git worktree per job.** One exploration cannot trash another or
  mutate the canonical data pipeline. Data is mounted read-only; only the job's
  own output directory is writable.
- **Claude Code CLI in headless mode**, so the existing subscription is the
  billing path. No API keys, no separate metering. *(Prerequisite: the CLI is not
  currently installed on this machine.)*
- **The worker gets a scoped toolkit**: `research_data`, the catalogue, the
  standard report, the canonical backtest, and the repo's test runner. It writes
  the experiment-specific code — the part that genuinely needs intelligence — and
  is structurally prevented from re-implementing data plumbing badly.
- **Schema-conformant output or failure.** The job's last act is writing a result
  document that validates against the schema. Non-conforming output is a failed
  job, not a partial one.
- **Bounded**: wall-clock, token and retry limits per job; a killed job is a
  recorded outcome with its partial manifest.
- **Idempotent re-runs.** Re-running a manifest must reproduce its result, and a
  divergence is itself a finding.

### 5.8 The standard alpha evaluation suite

Every exploration gets the same battery unless the spec explicitly opts out with
a stated reason. Consistency is the point: it produces a comparable *fingerprint*
per alpha, and it removes the researcher's freedom to report only the flattering
cut.

**Core predictive content**
- rank IC / Spearman with forward returns
- IC by horizon: 1, 5, 10, 20 sessions (and decay curve)
- quantile/decile returns — **the headline visual**
- monotonicity across buckets
- top-minus-bottom spread
- hit rate and effect size in decision units
- same-day market- and sector-relative returns
- clustered confidence intervals (by session), naive shown beside

**Signal mechanics**
- turnover of the signal
- persistence / autocorrelation of the score
- coverage over time and across the universe

**Conditioning**
- by year
- by sector
- by market-cap tier / liquidity bucket
- by market regime
- parameter-neighbourhood sensitivity — is this a plateau or a spike?

The quantile plot goes at the top of the report. An orderly slope across
Q1→Q5 is the thing worth looking at; one magic bucket surrounded by garbage is a
much weaker object, and the report should make that visually obvious in one
second.

### 5.9 Neutralisation diagnostics

For every candidate, mandatory: *does this survive after removing exposure to
market, sector, size, beta, volatility and generic momentum?*

The output is a decomposition, reported as such:

```
relative resilience  =  70% generic momentum
                     +  20% low beta
                     +  10% genuinely unusual resilience
```

The 10% is the object of interest. H038 is the cautionary case in the other
direction — a score built by subtracting beta was *algebraically* beta — so the
suite also projects a score off what it claims to adjust for and reports what
remains. Both directions of that error are now covered by the same machinery.

### 5.10 The canonical backtest

Deliberately simple, identical for every alpha, and never optimised:

> Each day, rank the universe by signal. Hold equal-weight top 5/10/20 for N
> sessions. Charge conservative costs (this project's measured floor: 0.40%
> round trip). Compare against the index and against the equal-weight universe.
> Annualise across the calendar span, charging cash for uninvested sessions.

It answers exactly one question: **if this predictive relationship were exploited
naively, is it economically meaningful?** Not "what is the best version of this".
No stop tuning, no holding-period search, no sizing, no regime timing at this
stage — that is how signal discovery got contaminated by strategy optimisation
before.

The three layers stay separate and are labelled as such everywhere:

| layer | question |
| --- | --- |
| signal diagnostics | does information exist? |
| canonical alpha backtest | is it economically large enough to care about? |
| strategy research | how would one actually trade it? — **later** |

### 5.11 AI interpretation and the failure taxonomy

The post-experiment analysis produces a paragraph a human can act on:

> *Relative resilience contains a modest monotonic signal over 5–15 sessions.
> Strongest after broad drawdowns beyond X; largely disappears after controlling
> for sector momentum. Three follow-up hypotheses suggested.*

Not a transcript, not a wall of tables. The tables stay one click away.

And failure is **classified**, never just `FAILED`:

`NO_SIGNAL` · `SIGNAL_BUT_BETA` · `SIGNAL_ONLY_ONE_REGIME` · `SIGNAL_TOO_SMALL` ·
`HIGH_TURNOVER` · `UNSTABLE` · `LIKELY_OVERFIT` · `INSUFFICIENT_SAMPLE` ·
`DATA_QUALITY` · `REDUNDANT_WITH_EXISTING_ALPHA`

Because the class determines the follow-up:

| class | the system's next move |
| --- | --- |
| `SIGNAL_BUT_BETA` | residualise against sector and beta; re-run |
| `SIGNAL_ONLY_ONE_REGIME` | characterise those periods; is the regime itself predictable? |
| `NO_SIGNAL` | branch laterally — *"raw drawdown resilience failed; resilience conditional on unusually high sector volume is conceptually adjacent"* |
| `SIGNAL_TOO_SMALL` | check whether it combines with a low-correlation existing alpha |
| `REDUNDANT_WITH_EXISTING_ALPHA` | record the subsumption edge; stop |
| `LIKELY_OVERFIT` | shrink the parameter space, re-run on the neighbourhood |

This is what makes suggestions *coherent* rather than Claude randomly proposing
another strategy. Note that this project already has a worked example of every
one of these classes in `HYPOTHESES.md`, which is a good corpus for calibrating
the classifier.

### 5.12 Signal comparison and the novelty objective

A Signal Compare view over any 2–10 signals:

- correlation between scores;
- correlation between realised returns;
- overlap in top-ranked names;
- does one subsume the other (incremental predictive value, both directions);
- combined-portfolio behaviour under the canonical construction.

The end goal is not the single strongest alpha. It is **several relatively
independent weak alphas**. So the suggestion engine must explicitly value
novelty:

> *"This performs slightly worse than Signal 17, but correlation is only 0.14,
> so it may be more valuable in combination."*

Without that, the system will optimise the same momentum family forever — which
is, recognisably, what the last seven phases did within one strategy family.

---

## 6. The dashboard

### Explore — the research console
Type a vague idea. *"Do stocks that hold up unusually well during Nifty drawdowns
rebound harder?"* The planner returns a research plan and shows what it intends
to measure; you amend it; you launch. Progress is visible; the deliverable is the
interpretation, with the report and the raw transcript behind it.

### Hypotheses — the centre of the system
One durable page per hypothesis: the original natural-language idea, the
rationale, the status, every experiment ever run against it, universes and
windows used, charts and diagnostics, related hypotheses, supporting evidence,
contradicting evidence, the AI interpretation, and the next suggested
investigations.

**Failed hypotheses stay visible.** This project has already learned why that
matters, and `HYPOTHESES.md` is the prototype.

### Idea graph
The hypothesis lineage, navigable. Where the branches are, what is unexplored.

### Signal Compare
As above. Correlation, overlap, subsumption, incremental value.

### Alpha leaderboard — not ranked by CAGR
Columns: `Alpha · IC · Q5–Q1 · Robustness · Turnover · Cost-adjusted · Novelty ·
OOS · Confidence`, plus an overall research score.

A boring alpha with modest returns, excellent monotonicity, low turnover and low
correlation to everything else should rank **highly**. A 26.8% CAGR fitted rule
with one magic bucket should not — H024 would have ranked poorly here before the
holdout was spent on it, which is the whole argument for the leaderboard.

### Graveyard
Every dead alpha, one line, with the reason:

> *Volume persistence — rejected; effect largely contaminated by selection
> lookahead.*
> *H024 proximity-to-high — strong exploration result, reversed OOS.*

It stops both the human and the AI from rediscovering the same seductive ideas in
six months. It is also the cheapest possible input to the suggestion engine.

### Research inbox
Auto-populated from three sources: AI-generated hypotheses from existing findings,
patterns noticed incidentally inside experiments, and your own notes. Each item
states **why it exists** — *"suggested because H041 found relative-strength
predictive power only in high-volatility periods"* — so research forms a tree
rather than a random walk.

---

## 7. v1 scope

Build only these ten. Everything else in this document is v2+.

1. Explore / new-hypothesis interface
2. Standard experiment specification
3. Claude Code job runner (worktree-isolated, schema-conformant output)
4. `research_data` — the single data module, with versioned purged splits
5. Standard cross-sectional alpha report
6. Canonical backtest
7. Hypothesis and evidence pages
8. Experiment manifests and data lineage
9. Failure classification and suggested follow-ups
10. Signal comparison and correlation

Deferred by design: idea-graph visualisation, leaderboard scoring, research
inbox automation, combination/portfolio construction across alphas, strategy
research of any kind, execution.

### Suggested build order

| stage | delivers | done when |
| --- | --- | --- |
| **A. Foundations** | `research_data`: catalogue, PIT API, split v1, leakage gate | ~~split manifest frozen and hashed~~ **done 2026-08-20** (`split_v1_frozen.json`, hash `657db79f7d380880`); H026 (the surviving finding) reproduces through the module; each of the four known lookaheads is caught by a test |
| **B. Evaluation** | standard alpha report + canonical backtest + neutralisation | H024 and H026 both produce full fingerprints that match what is already known about them |
| **C. Persistence** | hypothesis/evidence/signal store, manifests, sample-budget ledger | `HYPOTHESES.md` H001–H038 are migrated as real records, each mapped onto the partitions it actually read, so prior exposure is machine-readable |
| **D. Automation** | experiment spec, job runner, Claude Code worker, result schema | a job dispatched from a spec runs end-to-end unattended and ingests cleanly |
| **E. Interface** | Explore console, hypothesis pages, signal compare | a vague sentence becomes a plan, a run, and an interpretation without touching a terminal |

Stage A is the one that must not be rushed. Everything downstream inherits its
guarantees, and this project's entire failure history is a history of Stage A
defects. Within Stage A, the split is the irreversible part — every result the
lab ever produces is denominated in it, so freeze it deliberately and version it
from day one rather than settling it after a few experiments have already been
run against a provisional draw.

---

## 8. What carries over, what retires

**Carries over unchanged** — this is the genuinely valuable inventory:

- the point-in-time daily panel, 2020-01-01 → present, with corporate-action
  adjustment, rename merging and the pipeline order that makes both correct;
- the as-of lagging machinery and its audit — the single most important piece of
  code in the repo;
- market regime, breakout location and relative-strength context;
- opening 1-second tick data, 2023-08 → present, and its at-`t` invariance tests;
- clustered statistics, permutation nulls, matched-set construction with the
  market-offset diagnostic, stability splits, quantile profiling;
- the payoff simulator and span-based book statistics;
- `FINDINGS.md` and `HYPOTHESES.md` in full.

**Becomes generic** — currently strategy-specific, should be signal-agnostic:
the screener (one universe filter among many, not *the* pool), the exploration
scan machinery, the outcome taxonomy, and the freeze/holdout mechanism, which
generalises into the split plus the sample-budget ledger.

**Absorbed into `research_data`**: every direct parquet read scattered across the
current modules; the as-of panel; the rename map and corporate-action adjustment;
universe construction; benchmark and context series; forward labelling. These
keep their logic and lose their independence — after the refactor they are
internals of one module, not thirty entry points.

**Retires**: the phase gate itself; the assumption that the contraction screen is
the universe; strategy-specific naming throughout; and the single hardcoded
chronological holdout, replaced by the versioned split.

**Stays parked**: the uncle's 30–50 dated real picks remain the single
highest-value input available, and are now easier to use, not less relevant —
a labelled set of real decisions is exactly the kind of thing the new system can
evaluate as a signal in one afternoon. Same for the WhatsApp group data.

---

## 9. Risks and open decisions

- **The lab can overfit as a whole.** Hundreds of cheap experiments against one
  finite history is a multiple-comparisons machine. The permuted-maximum bar
  handles one scan; it does not handle a thousand explorations across months. The
  sample-budget ledger and a lab-level accounting of how many questions the data
  has been asked are the mitigation, and this needs an explicit design decision,
  not a hope.
- **Data is the binding constraint, not method.** 2020-01-01 floor, 1,647
  sessions, 27 quarters, one market. Some questions in this document are not
  answerable at this sample size, and the system should say so
  (`INSUFFICIENT_SAMPLE`) rather than produce a fragile answer.
- **27 blocks is a small number to shuffle.** With ~5 test quarters, the test
  estimate carries real assignment variance: a different seed would give a
  materially different number, and there is no way to average that away without
  reading test repeatedly. Mitigations are the constrained draw (§5.2) and
  reporting test results with a stated block count rather than as a point
  estimate. This is a genuine limitation of the design, not a detail — it should
  be visible on the evidence page, not buried in a manifest.
- **Purging costs training rows.** Roughly 15-20% at a 20-session horizon, and it
  scales with the maximum horizon. A dataset version supporting 60-session
  forward returns would purge far more, which is an argument for keeping the
  default `max_horizon` modest and creating a separate long-horizon version only
  when a hypothesis actually needs one.
- **Prior exposure of 2020-2023 is handled by lineage, which requires the idea
  graph to be honest.** If a hypothesis is a descendant of H024 or H034-H038 and
  nobody records the edge, the ledger will let it score on quarters it should not
  touch. Default to blocking when lineage is ambiguous, and make "unlinked
  hypothesis" a thing the planner must justify rather than the easy path.
- **Claude Code CLI is not installed here.** Installing it and confirming the
  headless/JSON-output mode works under the subscription is a Stage D
  prerequisite worth verifying early, since it gates automation entirely.
- **Cost of the agent loop.** Worktree isolation plus full data means each job
  has real setup cost. Job granularity — one hypothesis or one whole exploration
  family — is an open design question.
- **Who writes the pass criterion.** If the AI proposes the bar and also
  evaluates it, the bar drifts. Proposed rule: the planner drafts it, the human
  approves it, and it is frozen into the manifest before dispatch.
- **Deciding when a signal is "validated"** requires forward data, and forward
  data accrues one session a day. Expect the validated column to stay empty for
  months, and design the interface so that is visibly *normal* rather than
  looking broken.

---

## 10. Conventions that survive the refactor

- **`research_data` is the only door.** No experiment, report, notebook or
  worker opens a data file directly; if something is missing, it is added to
  the module rather than worked around.
- **Partitions, never date ranges.** An experiment names a dataset version and
  a partition; hand-written windows are how a holdout gets read twice.
- Thresholds are configuration, never hardcoded beliefs.
- Indicators on adjusted prices; tradeability claims on raw prices.
- Pipeline order is renames → corporate actions → indicators, always.
- Anything keyed on symbol folds through the canonical rename map.
- Verify empirically rather than trusting documentation — that has repeatedly
  paid off here.
- Negative results are never deleted, and an idea invalidated by a bug is marked
  superseded and kept, with the bug described.
- Record a hypothesis before moving substantially past it.
- Keep the test suite green; leakage tests are part of it, not optional extras.
