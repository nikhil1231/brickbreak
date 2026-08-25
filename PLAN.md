# brickbreak → the contextual price-action programme

> **Status:** current operating plan.
>
> **Written:** 2026-08-24.
>
> **Authority:** `MISSION.md` remains authoritative. This plan says how the next
> research programme is built and tested; it does not change the mission or
> convert a plausible trading story into evidence.

The research-director plan that this document replaces is preserved byte for
byte at `archive/plan/PLAN_2026-08-24.md`. Its contracts, council, data broker,
outcome firewall, structural and shape gates, multiplicity accounting, provider
policy, memory, and replacement rules **remain in force**. This document applies
those systems to one concrete programme: causal, contextual price action on NSE
equities.

Code written before today that cites `PLAN.md` sections in the research-director
plan means `archive/plan/PLAN_2026-08-24.md`. The earlier throughput and refactor
plans retain the force assigned to them by `AGENTS.md`. Nothing here revives a
claim or a plan from the archive as current evidence.

### 2026-08-25 branch: H057 level reaction, and the universe correction

Two facts retired the H056 *configuration* on the day it started acquiring, and
neither is about whether price action works.

**The universe was not tradable.** Every intraday and every bearish claim in
this programme is executable only in F&O for this account: an NRI cannot square
off intraday in the cash segment and cannot short cash equities. NSE's
stock-futures eligibility floor sits far above the ₹3-25 crore cash turnover
band the manifest screened, so the two universes barely intersect. The H056 pull
was stopped at 9,526 of 53,303 requests. Its 7.18M rows are retained as
cash-delivery research data and are resumable; they are not H057 provenance.

The replacement universe is point-in-time NSE stock-futures membership,
reconstructed from each session's own derivatives bhavcopy — a symbol was in the
universe on a session if and only if a `stock_future` row for it appears in that
session's file. This is not a convenience: 305 distinct symbols appear over
2020-2026 and only 102 are present throughout, so a present-day F&O list is a
survivorship trap. Levels are drawn on the continuous cash series; execution,
costs and capacity come from the futures series, which also supplies open
interest and lot size.

The correction is not merely a restriction. It moves the programme out of the
worst corner of the cost/horizon/liquidity space and into the best one available
to it: a futures round trip is roughly 6-10 bps of notional against the 40 bp
cash floor, so the gross move a setup must produce to be worth taking falls by
more than half without any new information being found.

**The detector was measuring its own density.** `causal_zones` seeded levels
from 2/2 five-minute fractals, which fire every few bars. That single choice
explains both prior failures: PA7's composite kappa of 0.087 with 1.52 ATR of
centre disagreement (the owner drew distant, older levels; the machine drew
micro-pivots), and the 3,222 → 16 structural funnel whose dominant rejections
were `target_room` and `reward_risk` — with a level every few bars the nearest
opposing level is a fraction of an ATR away, so a structural target can never
clear 80 bps. Neither number was a fact about the market.

`research_data.pipelines.levels` replaces the seeder with four detectors on one
schema — `fractal` (the incumbent, retained as a baseline), `anchor`,
`volume_profile`, `multi_touch` — and H057 chooses between them on evidence
rather than on aesthetics.

**H057 asks the question underneath H056.** Before asking whether a retest
predicts anything, ask whether a level interrupts the path at all more than a
matched fake level does. It is the necessary condition every later claim rests
on and the cheapest thing that can falsify the mechanism. Its statistic, grid,
controls, primary cell and frozen bar are registered in HYPOTHESES.md and were
fixed before the study ran. H056 remains outcome-untested; its manual retest
priors are unchanged and it resumes only if H057 survives.

**Decisions move to completed hourly bars.** The five-minute series is retained
and is not optional: an hourly bar reports a high and a low but not their order,
so an hourly-only backtest cannot say whether a stop or a target was hit first
whenever both sit inside one bar — which, at a sub-ATR barrier, is most of them.
Five-minute data is the intra-hour path; hourly is the decision.

---

### 2026-08-25 branch: H056 machine geometry

H055's PA7 result is retained: its frozen human/coded representation failed
agreement and does not advance. H056 asks a different question—whether a
machine-discovered representation can predict executable outcomes without
resembling human annotations. For H056 only, the human-agreement requirement in
§7, the representation part of E0 in §10, and PA7's representation exit
condition in §13 do not gate outcome access. Source, PIT, density, power,
capacity, leakage, exposure, multiplicity, cost and once-only final-test gates
all remain in force.

H056 may repeatedly adapt on old NSE and separately contracted foreign-market
data, but every market and period used for that adaptation is development data.
Development uses nested chronological walk-forward folds and leave-one-market-
out transfer tests. It may not turn the best-looking fold into “validation.” A
survivor is frozen—geometry, model, abstention, entry, exit, costs and portfolio
construction—before one untouched NSE test/forward read.

The manual setup prior is intentionally narrow: trade only a completed
support/resistance role reversal and later retest, in the direction of a
completed 60-minute EMA trend. The first configuration requires 12 completed
five-minute bars from zone confirmation to break and three from break to
retest. The retest must close on the new-role side; a completed close through
the far edge invalidates the level. Entry is the next available five-minute
open, the structural stop sits beyond that far edge, and the preferred target
is the nearest already-known opposing significant zone. Require at least 1.5R
and 80 bps gross target room. Six-, twelve- and twenty-four-bar stagnation cuts
are a declared development grid, not discretionary hindsight. The selector may
abstain, and missing entries, gap-through stops and source failures stay in the
population.

Practical trading guidance motivates these priors but does not validate them.
CME and Fidelity describe levels as zones and role reversal after a break;
Fidelity describes EMA as a lagging trend-direction tool; Schwab discusses
targets at prior opposing levels and stops beyond invalidation structure. The
Osler evidence finds that support/resistance can predict intraday *trend
interruptions* in FX, which is weaker than direction or net alpha. H056 must
therefore beat trend-only and pseudo-level baselines after costs, and the whole
adaptive search is judged with a maximum-statistic/data-snooping correction.

The first foreign transfer candidate is US cash equities through a contracted
historical consolidated feed, not Alpaca's free IEX-only live feed: Alpaca's
own documentation says IEX is one exchange and roughly 2.5% of US volume,
while SIP covers the consolidated US tape and historical data reaches 2016.
Before any pull, freeze the feed, adjustment, regular-session, timestamp,
delisting, symbol-change, split, coverage, rate and licence contract. A
current-survivor symbol list may be used only as explicitly survivor-biased
development data; it cannot serve as the untouched cross-market estimate.
Alpha Vantage documents 20+ years of month-addressable five-minute history but
puts historical intraday behind a premium plan; Twelve Data covers many markets
but its credit/plan and historical-depth terms must be priced before use. Do not
buy either merely to add rows: first measure whether one consolidated US market
adds distinct regimes and enough eligible H056 retests to change the power
calculation.

---

## 1. The decision

Build a serious test of this question:

> Given only information available at a decision timestamp, can causal price
> structure plus contextual judgement identify long opportunities whose future
> excess returns are better than strong, simple, fully specified baselines by an
> economically useful amount after costs?

The programme starts with liquid cash equities, an hourly setup horizon, and
five-minute decision bars. It does **not** start with one-minute pattern mining,
futures, stops, targets, or a large vocabulary of named chart patterns.

This is not a declaration that support, resistance, flips, or order blocks
work. The plausible thesis is narrower:

1. traders may react to remembered price regions;
2. a causal representation of those regions may contain information;
3. context may determine which interactions matter; and
4. an AI may be better at that contextual selection than one fixed score.

Each link is tested separately. If a link fails, the result identifies what
failed instead of allowing a discretionary story to absorb the failure.

### What success would mean

There are four claims, in increasing order of difficulty:

1. **Representation:** independent observers can identify materially similar
   regions from the same past-only case.
2. **Information:** causal interactions with those regions have a useful future
   distribution relative to matched controls.
3. **Judgement:** a frozen contextual judge improves on the strongest coded
   price-action baseline at the same take rate.
4. **Deployment:** the result survives validation, costs, capacity checks, and
   untouched forward data.

A success at one level is not promoted as a success at the next. A profitable
algorithm that humans would not call support/resistance can still be useful, but
it has not mimicked discretionary trading. Agreement without return information
is likewise not alpha.

---

## 2. Scope and priors

Broad filters are allowed when they are declared as economic priors rather than
chosen after seeing outcomes.

| dimension | first programme | deferred |
| --- | --- | --- |
| instrument | NSE EQ cash equities, ETFs excluded | stock futures and shorts |
| direction | long entries and abstention | short deployment |
| setup context | completed daily data through D-1 and rolling hourly structure | news, fundamentals, order book |
| decision resolution | completed five-minute bars | one-minute refinement |
| entry | next available five-minute bar open after the decision | limit-order simulation |
| universe prior | point-in-time, tradable low/mid-turnover names; initial 20-session median traded-value band of ₹3–25 crore | current market-cap buckets |
| capacity | intended position no more than 2% of lagged median daily traded value | institutional capacity |
| cost floor | 0.40% round trip | broker-specific optimisation |

The ₹3–25 crore band is a first, frozen prior, not a claim that this is the
best band. E0 may report coverage and representation quality across predeclared
liquidity strata. Changing the production universe after E0 requires a new data
contract and is recorded; it cannot be chosen using returns.

Present-day index membership or market-cap tiers may not score or screen
historical rows. Current sector labels may describe results but may not silently
stand in for point-in-time size. Every tradability field must carry its
`available_at` semantics.

### Why cash and five-minute bars come first

- A ₹5–10 lakh account can diversify cash positions without contract-lot and
  roll constraints dominating the experiment.
- NSE stock futures cover a selected, changing universe and introduce
  point-in-time eligibility, lot size, basis, expiry, roll, margin, and
  settlement data. A cash backtest cannot license a futures trade.
- Five-minute bars preserve the local path around an hourly setup while keeping
  data volume, API calls, and false precision tractable.
- One-minute data is tested later as an *incremental-information* question. It
  is not assumed to be better because it is more detailed.

---

## 3. One programme inside the existing laboratory

There will be no second lab, second exposure ledger, or `price_action_lab`
command tree.

The coded-signal question uses the research-director route:

```text
discover → attack → qualify → compile → execute
```

The contextual-judgement question uses the existing discretionary route:

```text
opportunity → replay generate → build → decide → reveal → evaluate
```

Both routes share a programme ID, hypothesis lineage, dataset version,
candidate manifest, case schema, exposure ledger, and multiplicity batch. The
AI arm is not permitted to see a hand-picked chart set produced after the coded
arm's outcomes are known.

### Reuse, generalise, retire

| existing component | treatment |
| --- | --- |
| `src/contracts/` | keep; add intraday source and case declarations to existing dossier/data/experiment contracts |
| `src/council/` | keep; attack mechanism, leakage, alternatives, and costs before data spend |
| `src/data_broker/` | keep; source feasibility and bootstrap coverage are E0 |
| `src/firewall/` | keep; all structural, shape, exposure, and outcome gates remain authoritative |
| `src/research_data/splits.py` | keep; intraday rows inherit their session's frozen partition and purge rules |
| `src/research_data/frame.py` | extend with the only public intraday loader |
| source clients and validators | keep; expose shared capped-request, throttle, span, and schema checks |
| `pipelines/opening.py` and `pipelines/bulk_intraday.py` | extract reusable acquisition/normalisation primitives into one generic intraday pipeline |
| `src/discretionary/` | keep; add a price-action case adapter and renderer, not a separate replay engine |
| baselines, `alpha_eval`, burden, forward, memory, distillation | keep; add price-action implementations behind their existing interfaces |
| hypothesis-specific remote pull scripts | retain while needed for reproduction, then archive measurement-bearing versions and remove redundant plumbing |
| direct parquet reads or family-local data loaders | forbidden; migrate rather than add another exception |

The migration rule is simple: make the common implementation reproduce the
existing opening and H047 artifacts before switching their readers. Archive
code only when it embodies a measurement that git history alone is not enough
to reproduce. Delete ordinary duplicated plumbing after replacement.

---

## 4. The intraday data product

The first infrastructure deliverable is not a strategy. It is a versioned,
causal intraday data product reached only through `research_data`.

### 4.1 Probe before backfill

The data broker first measures, with a tiny local probe:

- which Breeze intervals actually work and how their bars are aligned;
- the earliest reliable date at each candidate interval;
- whether a native five-minute or thirty-minute endpoint is stable enough to
  avoid reconstructing everything from one-minute bars;
- the 1,000-row cap, tail behaviour, repeatability, and maximum safe request
  spans;
- mapping success from historical NSE symbols and rename chains to ISEC codes;
- timestamp timezone, session boundaries, auction treatment, and special
  sessions;
- OHLC and volume reconciliation against daily bhavcopy;
- negative volume, duplicates, gaps, halts, empty responses, and schema drift;
- approximate request count, wall time, storage size, and daily token-expiry
  behaviour for a full manifest.

No preferred interval is assumed before this probe. Prefer native five-minute
bars if the probe establishes their depth and integrity. Otherwise pull
one-minute bars remotely and derive five-minute bars deterministically. Do not
build hourly structure from a provider-specific `1hour` convention; derive it
from the canonical base bars so that 09:15 session alignment is explicit.

At roughly 500 symbols over six years, five-minute history is on the order of
55–60 thousand capped requests; one-minute history is about five times that.
The frozen request manifest, not this estimate, is the budget authority.

### 4.2 Point-in-time identity is a source gate

The daily bhavcopy defines which securities actually traded on a session. The
intraday manifest is built from that tape plus the rename registry; it is never
built from today's symbol master alone.

The probe reports mapping coverage by year, liquidity stratum, survivor status,
and traded value. Unmapped and delisted securities remain explicit missing
requests, not silently excluded rows. A historical claim over the PIT universe
requires at least 95% symbol-session coverage and 98% traded-value coverage in
every evaluated era, with no obvious outcome-related missingness. If Breeze
cannot meet that bar, the broker must source an alternative vendor or narrow the
claim to an explicitly survivor-biased universe and reserve confirmation for
forward data. The latter is exploratory evidence, not a clean historical test.

### 4.3 Canonical schema

Every base bar carries at least:

```text
instrument_id, symbol_asof, session, bar_start, bar_end, available_at,
open_raw, high_raw, low_raw, close_raw, volume_raw,
source, source_interval, request_id, quality_flags, dataset_version
```

Derived bars and features carry lineage to their inputs. Raw price is used for
as-of chart geometry. A corporate action invalidates or causally rebases an old
zone only when that action is known; a future split may not rewrite the case the
judge supposedly saw. Canonical adjusted returns may be used for outcome
evaluation through the existing return machinery.

Daily context used at time D comes only from completed sessions through D-1.
Intraday volume surprises use prior-session, same-clock denominators. No day's
full volume, range, close, delivery percentage, or later intraday bucket may
enter a decision made during that day.

### 4.4 Dataset and split semantics

Create `intraday_v1` only after the source contract passes. It contains:

- immutable raw request manifests and response hashes;
- normalised canonical base bars;
- deterministic derived five-minute and rolling-hour views;
- a feature-catalogue entry for every field and its PIT lineage;
- coverage and quality reports by session and instrument;
- the parent daily dataset version and split-manifest hash.

An intraday row inherits the train/validation/test/forward assignment of its
whole session. Bars are never shuffled across partitions. Purges use the longest
registered outcome horizon and apply at session boundaries. Experiment code
asks for a dataset version and partition, never a date range.

### 4.5 Required data tests

The product is not usable until these tests pass:

1. appending bars after timestamp T leaves every feature available at T
   byte-identical;
2. building a case from data truncated at T and from the full store produces
   identical case bytes;
3. one-minute → five-minute → rolling-hour aggregation has declared boundary
   and partial-bar behaviour;
4. daily/intraday OHLC and volume reconcile within declared tolerances;
5. corporate actions, symbol changes, special sessions, circuits, halts, and
   missing bars are flagged rather than imputed into normal observations;
6. split and purge assignment is inherited from the session;
7. a capped or tail-truncated response fails loudly;
8. repeated ingestion and remote resume are idempotent;
9. no module outside `research_data` opens the intraday store; and
10. entry and exit prices are taken from the first genuinely available bar,
    with unavailable trades retained as failures rather than dropped.

---

## 5. Remote acquisition is part of the architecture

Any historical pull expected to exceed 1,000 requests or 15 minutes runs on the
remote laptop. Local execution is limited to source microprobes, fixtures, and
small debugging slices.

### 5.1 Division of responsibility

The local/canonical machine:

1. constructs a label-free, hashed request manifest from PIT daily data;
2. freezes the source contract and pinned code revision;
3. sends only requests and acquisition code to the remote laptop;
4. receives immutable response shards and status artifacts;
5. verifies hashes, coverage, spans, and errors; and
6. alone builds the dataset, candidates, cases, and research reports.

The remote laptop:

1. authenticates with its own local Breeze session;
2. executes the manifest with a lock-guarded safe throttle;
3. chunks every request below the measured cap and asserts returned spans;
4. checkpoints successes, empty responses, mapping failures, and retryable
   errors separately;
5. stops clearly on expired authentication instead of looping forever;
6. resumes idempotently after token refresh or restart; and
7. never receives labels, selects cases, or evaluates a signal.

### 5.2 Implementation

Generalise the proven `server_pull.py` and `server_h047_pull.py` pattern into:

```text
scripts/server_intraday_pull.py
scripts/run_intraday_pull.sh
scripts/sync_intraday_from_remote.sh
```

The supervisor runs under `tmux` on `hp-ts`, emits a small machine-readable
status file, and keeps raw response shards separate from normalised output. The
sync command transfers only immutable or content-addressed artifacts, then the
local verifier checks the request-manifest hash, row spans, schema fingerprint,
and per-shard checksum before admitting bytes to `research_data`.

First run a stratified bootstrap pull: enough symbols, eras, liquidity strata,
and contiguous warm-up history to test coverage and zone density without
reading outcomes. A full-history manifest is released only after that E0 report
passes. Long repairs and backfills remain remote as well.

---

## 6. Causal price structure

The feature layer describes observable geometry. It does not name an unseen
market participant.

### 6.1 Zone lifecycle

A support/resistance zone has an explicit state machine:

1. a pivot or consolidation seed occurs;
2. it becomes knowable only after its confirmation bars have closed;
3. nearby seeds may merge under a frozen, volatility-scaled rule;
4. later approaches, touches, rejections, and breaks update only after their
   bars close;
5. a resistance-to-support flip exists only after a completed close confirms
   the break and a later bar performs the retest; and
6. age, decay, corporate actions, and invalidation are deterministic.

Every zone carries `origin_at`, `known_at`, price bounds, width in bps and ATR,
touch history, approach side, age, and invalidation reason. A decision cannot
use a zone before `known_at`.

The first representation should favour continuous fuzzy memberships over a
forest of hard cutoffs:

- distance to zone in lagged ATR units;
- overlap with the zone;
- approach speed and direction;
- close location and rejection strength;
- prior touch count and time since last touch;
- break depth and time since break;
- lagged time-of-day volume surprise;
- completed daily and rolling-hour trend context; and
- distance to recent highs/lows and broad market context.

One small neighbourhood of representation choices may be declared in a single
multiplicity batch. Its result is the maximum over that neighbourhood, judged
against the corresponding permuted maximum. Unrecorded threshold tweaking is a
new attempt.

### 6.2 “Order blocks”

`order_block` is not a primitive feature and must not be described as evidence
of institutional orders. The tape cannot see that mechanism. A later dossier
may define a measurable `pre_displacement_base` region—a compact consolidation
preceding a large move—and test it under that descriptive name.

### 6.3 First setup families

Keep the first registered batch small:

1. **Bullish rejection:** price approaches an already-known support region and
   closes a completed decision bar away from it.
2. **Bullish flip/retest:** price previously closed above known resistance,
   later retests that region from above, and closes a completed decision bar.

Trend and volume are contextual fields and baselines, not separate combinatorial
switches. Additional patterns require new dossiers linked to the result of this
batch.

---

## 7. Does the representation resemble human judgement?

Before asking whether it predicts returns, run a label-free annotation study on
the training partition.

Cases are sampled by a frozen, high-recall rule across sessions, eras, and
liquidity strata. Each case shows only the history available at its timestamp.
At least one human annotation pass and multiple independent, frozen model passes
mark:

- whether a relevant zone exists;
- its upper and lower bound;
- whether the current interaction is a rejection, break, retest, or none;
- the directional stance and confidence; and
- which observed facts drove the answer.

Report zone-overlap, ATR-normalised centre distance, class agreement, and
directional kappa. Freeze the acceptance bar before the study; the initial bar
is class kappa of at least 0.40 and median zone-centre disagreement no greater
than 0.5 lagged ATR. Failure does not prove that the algorithm lacks alpha. It
does block the claim that it is a test of a shared human price-action concept.

The same study provides a fidelity set for any later distilled local model.
Fidelity is measured against the frozen judge on unseen training cases, never
against returns.

---

## 8. Cases and LLM leakage

The price-action case adapter belongs in `src/discretionary/` and selects only
catalogued fields already built under PIT tests. It produces:

- a deterministic, rebased chart ending exactly at the decision bar;
- a compact numeric sidecar with the same history and PIT context;
- relative time and anonymised instrument identity by default;
- no company name, ticker, calendar date, news clue, or future-derived caption;
- schema, renderer, prompt, and content hashes; and
- an explicit decision vocabulary: `TAKE`, `SKIP`, confidence, invalidation,
  and observed reasons.

Chart rendering is deterministic and tested as data, not presentation. If a
provider cannot consume the frozen image form, the registered fallback is a
compact bar table; switching modalities after outcomes is a new prompt version.

Anonymisation is necessary because an LLM may remember a famous stock and date,
but it is not assumed sufficient. Run the H042 paired identity control: the same
cases, once anonymised and once identity-revealed, with order randomised and the
prompt/model frozen. Until that control is resolved, historical AI judgement
results retain the memory-leakage caveat. Untouched forward cases remain the
decisive control.

The judge runs tool-free in an empty directory. Failed calls become recorded
`SKIP`s. Cases are never removed because the model errored or because the chart
later proved awkward.

---

## 9. Candidate generation and baselines

Candidate generation must be broad, deterministic, and label-free. Generate
every PIT-universe interaction satisfying the frozen geometric proximity rule;
do not curate visually convincing examples. Preserve non-events and awkward
cases so the selector cannot inherit an easy population.

To prevent one volatile symbol or one market day from manufacturing sample
size, retain at most one active candidate per symbol over the registered holding
window. All contrasts are paired within session where possible.

The minimum baseline set is:

1. take-all on the candidate pool;
2. random selection at the AI's take rate, stratified within session;
3. prior high/low or pivot zones with no contextual judgement;
4. trend-only and simple momentum/mean-reversion scores;
5. the full coded zone score without the AI;
6. a walk-forward rank model using the same PIT numeric fields; and
7. pseudo-zones matched on session, symbol volatility, width, and distance.

The AI and every selector baseline except take-all operate at the AI's realised
take rate. The strongest eligible baseline, not the weakest convenient one, is
the comparison bar.

---

## 10. Testing ladder

Every stage spends sample according to the existing exposure ledger. Passing a
stage permits the next read; it does not retroactively upgrade the evidence.

### E0 — source, representation, and power

E0 sees no forward-return values. It reports:

- source and identity coverage by era and liquidity;
- missingness, cap failures, corporate-action density, and bar quality;
- zone count, width, age, touch count, and interaction density;
- candidates per session, concentration, take-rate feasibility, and independent
  session blocks;
- annotation agreement and model stability;
- the empirical cost and capacity distribution from lagged information; and
- minimum detectable effect using sessions/blocks, not bars, against the useful
  default effect of 80 bps gross per taken trade.

The initial data product passes only if mapping and bar coverage pass §4.2,
representation agreement passes §7, there are enough independent blocks to
detect a useful effect, and the intended positions fit the declared capacity
rule. Failure retires or redesigns the representation without touching returns.

### E1 — one optional shape read

If the structural case is credible, one registered shape-only query may ask
whether candidate windows have enough post-decision movement to contain an
economic trade. It may inspect symmetric absolute excursion, realised range,
and the probability of reaching either side of a predeclared 80 bp barrier. It
may not inspect sign, bullish hit rate, net payoff, or choose a direction.

Compare the entire frozen scan with real-size, same-session matched pseudo-zones
and judge its maximum against a maximum-statistic permutation null. This read is
logged exposure. If candidates do not even contain movement large enough to pay
costs at a usable frequency, retire this mechanism; do not manufacture movement
with tighter bars or wider stops on the same sample.

### E2 — first directional batch

Compile the first two questions together so their multiplicity is explicit:

1. **PA-signal:** does the causal zone score predict one-session-ahead excess
   return better than the baseline set?
2. **PA-judge:** on the identical frozen candidate population, does one frozen,
   anonymised contextual judge beat the strongest coded baseline at the same
   take rate?

The decision is made after a completed five-minute bar. Entry is the next
available five-minute open. The primary exit is the same clock on the next
tradable session; a session-close path report is diagnostic. MFE, MAE, stops,
and targets describe the path but cannot select the winner or be optimised in
this batch.

The default economic bar is at least 80 bps gross excess per taken trade,
positive after the 40 bp round-trip cost floor, and positive lift over the best
baseline. Statistical evidence uses session-clustered contrasts, the registered
horizon's overlap correction, block-aware uncertainty, and the batch's
permutation maximum. Report bps and win rates beside every t-statistic.

### E3 — untouched validation

Only an E2 result that passes its exact frozen economic bar advances. Validation
uses the unchanged signal, prompt, model, renderer, universe, take rule, and
costs. A prompt edit, added context field, changed zone rule, or different model
is a descendant hypothesis and a fresh multiplicity burden.

### E4 — forward operation

The surviving system is run prospectively. Cases and decisions are sealed
before outcomes exist, then revealed on schedule. Forward performance is never
averaged with shuffled historical validation. Historical LLM judgement can
suggest a system; only this lane resolves the remaining memorisation concern.

---

## 11. Statistical and economic conventions

- The independent unit is the session or a non-overlapping session block, not
  an hourly or five-minute bar.
- Cross-sectional comparisons are paired within session. Market offset must be
  reported and read zero by construction.
- Overlapping horizons use the established Hansen–Hodrick correction and report
  effective independent blocks. Clustering and serial-overlap correction solve
  different problems; both are required.
- A scan is judged against the permuted maximum of that scan. Report the full
  registered search neighbourhood, including failures.
- Candidate density, take rate, and data coverage are part of the result. Never
  drop a missing bar, circuit, halt, failed model call, or unavailable entry to
  create an easier population.
- Signal diagnostics, canonical fixed-hold economics, and later execution
  research remain separate layers.
- Costs are charged to every completed trade. Slippage stress increases for
  thinner names; raw returns are never substituted for excess returns.
- The account is divided by every slot the portfolio can hold. Concurrent
  cohorts do not receive implicit leverage.

There is no global rule saying alpha stops existing after N attempts. The budget
instead limits what can be claimed from a finite sample. Each failed mechanism
is retired or materially changed and linked; the broader search may continue
with new mechanisms, new data, or forward observations. This is disciplined
search, not a lottery ticket whose odds improve by repeatedly reading the same
history.

---

## 12. Token and execution policy

Explorations run **in series at the hypothesis level**. Source feasibility,
representation, shape, direction, and judgement each inform whether the next
stage is worth buying. Hundreds of adaptive hypotheses are not launched in
parallel.

Parallelism is safe inside one frozen task:

- remote acquisition requests from one immutable manifest;
- independent attacks on one dossier;
- case construction from one schema; and
- tool-free decisions over one sealed case set.

That parallelism changes latency, not the number of attempts.

Use Claude/Codex subscription lanes for dossier generation, attack,
qualification, and the first judge where possible. Before a paid replay, run
synthetic and outcome-free training cases to measure prompt length and failure
rate. The first historical judge is capped at one model, at most 100 cases, and
one million total input-plus-output tokens unless its compiled contract states a
smaller limit. The compiler estimates current provider cost and refuses a batch
that would take monthly incremental model spend above ₹4,000 (approximately
$50) without explicit approval.

Keep cases compact: one deterministic chart, a small numeric sidecar, and a
short decision schema. More verbose reasoning is not evidence. A second model,
prompt ensemble, self-consistency vote, or critic loop is a new arm and is not
added merely because the first result is marginal.

---

## 13. Build order and gates

| stage | deliverable | exit condition |
| --- | --- | --- |
| PA0 | mechanism dossier and attacked data/source contract | exact representation claim, alternatives, universe, costs, and exposure declared |
| PA1 | migration inventory and shared intraday interfaces | every reused, generalised, archived, and deleted path named; no parallel loader planned |
| PA2 | local source microprobe | interval, depth, mapping, cap, alignment, integrity, call, and storage report frozen |
| PA3 | generic remote acquisition worker | hashed manifest runs, stops, resumes, syncs, and verifies idempotently on `hp-ts` |
| PA4 | stratified remote bootstrap dataset | representative label-free coverage and quality report admitted through `research_data` |
| PA5 | causal zone and context features | state-machine, future-append, denominator, action, and split tests green |
| PA6 | anonymised case adapter and renderer | truncated/full case bytes identical; H042 pairing supported; failures retained |
| PA7 | E0 annotation, density, power, cost, and capacity report | source, representation, and useful-effect gates pass without outcomes |
| PA8 | full remote `intraday_v1` backfill | manifest complete or explicit failures; local hashes, coverage, catalogue, and splits frozen |
| PA9 | optional E1 shape report | frozen shape bar passes; directional fields remain sealed |
| PA10 | compiled PA-signal and PA-judge E2 batch | one-shot execution and standard report complete |
| PA11 | E3 validation and prospective E4 replay | unchanged system passes validation; forward decisions sealed before reveal |
| PA12 | one-minute or futures descendant | opened only by positive prior evidence and a new source/experiment contract |

PA3 and feature development may proceed against synthetic fixtures while the
bootstrap pull runs. No feature code may infer source behaviour that PA2 has not
measured. The full historical pull is deliberately after PA7: the programme
earns the expensive backfill by showing that its data and representation are
coherent without consulting outcomes.

---

## 14. What later descendants must prove

### One-minute refinement

If the five-minute programme contains information, create paired cases from the
same frozen setups: one with five-minute detail and one with one-minute detail.
Everything else stays identical. The one-minute arm must add net bps or better
calibration, not merely produce more confident explanations. Pull only the
registered event windows remotely before considering a full one-minute store.

### Futures and short setups

A futures descendant needs a PIT contract-master dataset with eligibility, lot
size, expiry, roll, basis, price limits, margin, and settlement conventions. It
must be evaluated on actual contracts with account-level margin and position
sizing. Bearish cash signals may be studied descriptively before then, but a
cash-series short backtest is not executable evidence.

### Strategy research

Stops, targets, scaling, limit orders, multiple simultaneous setups, and
portfolio optimisation begin only after a fixed-horizon signal survives. They
use new contracts and data exposure. The initial report's path diagnostics are
not a free menu from which to select an exit.

---

## 15. Non-negotiables

1. No chart or zone contains information printed after its decision timestamp.
2. No historical universe is reconstructed from today's surviving symbols.
3. No present-day size tier scores a historical case.
4. No intraday case uses that day's close, range, delivery percentage, or full
   volume in a numerator or denominator.
5. No long-running historical pull runs locally.
6. No remote worker receives outcome labels or research authority.
7. No attractive chart is hand-selected after looking at what followed.
8. No “order block” is described as institutional activity the data cannot see.
9. No five-minute or hourly bar is counted as an independent trial.
10. No one-minute scan begins merely because the five-minute result is weak.
11. No cash-equity result is presented as a tested futures strategy.
12. No prompt, renderer, threshold, horizon, or baseline is improved after an
    outcome read without becoming a new, counted hypothesis.
13. No significant statistic substitutes for a tradeable effect in bps.
14. No failed source request, missing entry, circuit, or model call disappears
    from the evaluated population.
15. The programme is allowed to fail. Its deliverable is reliable evidence, not
    a promised trading system.

---

## 16. Definition of done

The infrastructure phase is done when:

- all intraday market data enters through one versioned `research_data` API;
- the remote worker can complete and resume a frozen manifest without research
  logic;
- source, symbol, time, adjustment, aggregation, split, and PIT invariants are
  tested;
- cases are deterministic, anonymised, tool-free, and byte-stable under future
  truncation;
- existing opening/H047 paths have either migrated or remain explicitly frozen
  for reproduction; and
- the ordinary test suite plus the new intraday leakage tests are green.

The first research cycle is done when the PA-signal and PA-judge hypotheses are
recorded whether supported or rejected, every exposure is in the ledger, the
standard report includes distributions, baselines, costs, capacity, independent
blocks, and failure counts, and any survivor is running in the forward lane.

If the result is dry, the failure should say *where*: data coverage,
representation agreement, lack of movement, lack of directional information,
no contextual lift, costs, or forward decay. That is what makes the next idea
less of a gamble than the last one.
