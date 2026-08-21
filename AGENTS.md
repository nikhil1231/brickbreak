# brickbreak — agent notes

**What this is:** an alpha research environment for NSE equities. Not a
backtester, and no longer a single-strategy project. The unit of work is a
*hypothesis*, investigated by an *exploration*, producing *signals* that
accumulate *evidence*. See `PLAN.md` for the architecture and the build order.

**Read order for a fresh session:** `PLAN.md` (where this is going) →
`FINDINGS.md` (what was measured) → `HYPOTHESES.md` (the ledger, H001-H038).

**The phase gate is retired.** The old rule — no strategy or backtest code until
the current phase settles — served a single-strategy project and no longer
applies. What replaces it is stricter in the place that matters: no result counts
until it passes the leakage gate and the standard report.

## Repo layout, and the archive

| path | what |
| --- | --- |
| `PLAN.md` | current architecture and plan |
| `FINDINGS.md` | evidence, chronological |
| `HYPOTHESES.md` | the research ledger, stable IDs, nothing deleted |
| `src/` | current code |
| `data/` | on-disk parquet store — **bytes only**, opened through the data module |
| `tests/` | keep green |
| `archive/` | superseded documents and code |

**Archive policy.**

- **Do not read `archive/` by default.** It is superseded material, kept for
  provenance and for the rare "what did we think in August?" question. Reading it
  as if it were current is how a retracted claim gets resurrected. Only open it
  when specifically asked, or when tracing why something changed.
- **When a document is substantially rewritten, archive the old one rather than
  losing it**: `archive/<kind>/<NAME>_<YYYY-MM-DD>.md` —
  e.g. `archive/plan/PLAN_2026-08-20.md`, `archive/agents/AGENTS_2026-08-20.md`.
- **When code is superseded**, move it to `archive/src/` rather than deleting it,
  if it encodes a measurement someone might want to reproduce. Delete freely if
  it is merely obsolete plumbing — git has it.
- **Never archive `FINDINGS.md` or `HYPOTHESES.md`.** They are append-only
  research state and outlive every refactor. A wrong result is annotated and kept
  in place, never moved out of sight.
- Nothing in `archive/` is ever cited as current evidence.

## The data module is the only door

**Target state (see `PLAN.md` §5.1-5.2):** all market data reaches experiments
through one module, `research_data`. Nothing else opens a parquet file. It owns
point-in-time features, universes, adjusted/raw prices, benchmarks, forward
labels, the feature catalogue, and the versioned dataset splits.

Two rules that hold from now on, whatever the migration state:

- **Partitions, never hand-written date ranges.** An experiment names a dataset
  version and a partition (`train` / `validation` / `test` / `forward`). A
  hard-coded window in experiment code is how a holdout gets read twice.
- **If data is missing, add it to the module.** Do not work around it with a
  direct read. Three of this project's four lookaheads entered through ad-hoc
  parquet access.

**The lab, end to end:** `python -m src.cli suggest` reads the research inbox —
what to test next, proposed against the whole ledger and the graveyard so
nothing already tested returns in new words (`--new` regenerates the three
slots, `--refresh Sxxx` replaces one; reading costs nothing, generating spends
a model call). `python -m src.cli plan "<idea>"` proposes an
experiment; `python -m src.cli job --hypothesis H0xx --question "..." --signal
name --provider claude|codex [--model MODEL]` runs one in an isolated worktree
with the selected coding agent; `jobs`,
`forward`, `burden` and `serve` inspect the results. The worker writes exactly
one file — `job/signal.py` with `compute(df) -> Series` — and the harness runs
from the canonical checkout, never from the worktree, so an agent cannot loosen
the evaluation it is judged by. Claude remains the default. Install and log in
to at least one supported CLI: `npm install -g @anthropic-ai/claude-code` then
`claude`, or `npm install -g @openai/codex` then `codex login`.

**Built so far:** `src/research_data/splits.py` — versioned, purged,
quarter-level partitions, frozen as `data/metadata/split_v1_frozen.json`
(hash `657db79f7d380880`). Select rows with `splits.assign(df)`, never with a
date range. `python -m src.cli split --show` describes it.

**Current state, until the rest of the refactor lands:**
`research_data.pipelines.daily_panel.load()` defaults to the lagged
`screen_metrics_asof.parquet`, `research.opening_window.explore.fence()` raises
on holdout rows, and `research.opening_window.family.holdout()` /
`research.resilience.semi_stale()` re-hash frozen specs
before reading. Treat those as the module's ancestors — extend them, do not add
parallel access paths beside them.

### Splits and the sample budget

The old arrangement was backwards: the holdout (2020-04 → 2023-08) sat *before*
the exploration window (2023-08 → present), so rules were developed on recent
data and tested on older data, one window, one regime, one shot.

The replacement is whole calendar quarters assigned to train/validation/test by a
constrained seeded draw, chronological within each quarter, purged around
cross-set boundaries, with a versioned split manifest — plus a permanent
chronological `forward` partition for everything after the dataset version was
created. Shuffled `test` answers *does it work across regimes?*; `forward`
answers *does it still work?* They are never averaged.

**What is already spent, and stays spent:** 2020-2023 has been read twice —
first against the opening-window family (H033, FAIL), then against the frozen
resilience spec (H037). Any descendant of H024, H026 or H034-H038 is blocked from
scoring on those quarters; the `forward` lane is its only clean confirmation.
Prior exposure is recorded per quarter, so an unrelated new signal may use them
with a stated caveat. **When lineage is ambiguous, block.**

## Data sources — which to use when

| need | source | depth |
| --- | --- | --- |
| daily OHLCV + universe | NSE bhavcopy (`sec_bhavdata_full`) | **2020-01-01 onward** |
| daily OHLCV (fallback) | Breeze `1day` | ~2002 onward |
| 1-second opening ticks | Breeze `1second` | 2018-04-02 onward |
| symbol renames | NSE `equities/symbolchange.csv` | full history, 1999 onward |
| sector / size tiers | NSE `ind_nifty*list.csv` | current snapshot |
| market regime, breakout levels, RS | `src/research_data/pipelines/context.py` (derived, as-of) | 2020-01-01 onward |
| ETF exclusion | NSE `eq_etfseclist.csv` | current snapshot |

**Prefer bhavcopy for daily.** Free, unauthenticated, carries turnover and
delivery %, and is **point-in-time** — each file lists exactly what traded that
day, which is what removes survivorship bias.

### The 2020 floor is a tradeoff, not a hard limit

Bhavcopy 404s before 2020 and the legacy `cmDDMMMYYYYbhav.csv.zip` format is
retired. But **Breeze daily reaches ~2002**, and 2018-2020 fits under the
1,000-row cap: ~1 call per symbol, ~2,900 calls, ~12 min.

The cost: Breeze needs the symbol list up front, so that window would be screened
against **today's** master (~57 inactive stubs vs hundreds of real delistings) —
reintroducing survivorship bias for those years only, while 2020+ stays
point-in-time. Mixing the two silently biases cross-period comparison. Also loses
`turnover` (fall back to price x volume, already the code path) and delivery %.

Decision left open. If backfilled, tag those years as survivor-biased **in the
feature catalogue**, not in a comment.

## Breeze gotchas (all measured, all silent failures)

- **1,000-row hard cap, returns the TAIL.** Wide requests drop the *start* with
  HTTP 200 and no cursor. Chunk under 1,000 and assert the returned span.
- **Rate limit is real**: ~4-5 req/s safe, 429s from ~7.5 req/s. Client throttle
  must stay lock-guarded across threads or the rate silently overshoots.
- **`stock_code` must be the ISEC code**, not the NSE ticker. `RELIANCE` returns
  0 rows with no error; `RELIND` works. ~5% of symbols fail to map (renames).
- **Session tokens expire daily** (~midnight IST). No headless auth.
- **Corporate actions unadjusted after ~2023** — splits appear as -50%/-90%
  single-day steps. Handled as of 2026-08-19 via `sync-corp-actions`.
- **Negative volume** on a few bars, repeated identically by the 1-minute
  endpoint — archive defect, unfixable by re-fetching. Flag and exclude; never
  clip to zero.
- **`1second` is not tick data** — ~5s snapshots with volume smeared behind
  price. 30-second buckets are the practical floor.
- Use **v2** for everything; v1 cannot serve 1-second data.

## NSE gotchas

- **Holiday URLs serve the previous session's file** instead of 404ing. Trust the
  file's own `DATE1`, reject mismatches. Regression-tested.
- **Muhurat (Diwali) dates have no 09:15 session** — evening session only, but
  they do appear in bhavcopy. Detect via dates where all symbols return empty.
- **NSE trades on some weekends** (budget Saturdays, Muhurat, DR drills). Never
  restrict a bhavcopy sync to Mon-Fri, and file every response under the date
  *inside* the file — 2021-11-04's session is served at the 05112021 URL.
- **bhavcopy OPEN != the first 1-second tick.** NSE's opening print comes from the
  pre-open call auction at 09:15:00; Breeze's series starts at the first
  continuous trade, often seconds later. They disagree on the *sign* of the
  morning gap on 10.6% of candidate days. Compute gaps from bhavcopy OPEN.
- **ETFs trade in the EQ series** and pass volatility-contraction screens
  trivially (near-zero vol by design). Exclude them.
- **`PREV_CLOSE` is not a usable adjustment source** — NSE leaves it raw on
  TATASTEEL's split and pre-adjusts it on DRCSYSTEMS'. Take ratios from the
  corporate-actions API and apply them only where the tape confirms them.
- No free market-cap file exists; `size_tier_rank` is index membership
  (50/100/200/500/750/9999), i.e. buckets, not a true cap rank — **and it is a
  present-day snapshot, so it is a lookahead. See below.**
- **Renamed tickers split a company's history in two.** NSE publishes the list
  (`symbolchange.csv`) but the tape decides: a link is merged only on a clean
  handover with continuous **raw** prices. Test continuity on `close_raw`, never
  the adjusted close — factors accumulate per ticker, so the adjusted series has
  a bookkeeping step at every handover.
- **`change_date` is the filing date, not the handover.** QUALITY printed on its
  own stated change date. Split on the tape.
- 9 symbol-days carry negative volume (archive defect) and are excluded.

## Lookahead is this project's characteristic failure

Four distinct non-price lookaheads have been caught here, none of them in an
obvious place. Assume there is a fifth. In the target architecture each of these
is caught by the data module or the leakage gate rather than by vigilance.

- **Selecting on the entry day's own close (H015).** Fixed 2026-08-19 via
  `src/research_data/pipelines/asof.py`; `daily_panel.load()` defaults to the lagged panel. Everything
  built before that sits on the contaminated pool and must be **re-run, not
  adjusted**: the corrected screen overlaps the old one on only **61%** of
  candidate mornings. *Why it inverts rather than inflates:* the contraction
  filters read date D's own high and low, so a morning whose opening demand kept
  running all day has a wide range, fails contraction, and is excluded — while
  one that faded into a narrow range is kept. The pool retains the failures and
  discards the successes, which alone can manufacture "sustained opening demand
  is bearish".
- **Normalisers are lookaheads too.** `behaviour.py` divided opening volume by
  `median_vol_20` off the *unlagged* panel — a 20-session median containing date
  D's own full-day volume. **Check every denominator, not just every numerator.**
  In the catalogue, PIT status is inherited from a feature's inputs precisely so
  this is mechanical.
- **A "current snapshot" attribute is a lookahead.** `size_tier_rank` is NSE's
  *present* index membership applied to every historical row, and membership is
  assigned on market cap — i.e. on the returns being scored. Ranking on it in a
  2021 test means ranking small names by whether they were still small in 2026.
  Caught by `tests/test_family.py` one step before the holdout was opened. Sector
  labels come from the same snapshot; they are kept because a classification does
  not move with the stock's return, but that distinction must be **stated**. Rule:
  non-PIT features may stratify, never score.
- **A gap *between* observations inside a window leaks.** Cumulative statistics
  sampled at `t` are safe by construction; anything using the interval to the
  *next* observation is not, because that interval is only known once it has
  printed. `behaviour.py` shipped exactly that in `time_above_open_frac`.
  `test_features_at_t_ignore_everything_after_t` appends later bars and requires
  every feature at `t` to be unchanged. **Write that test before trusting a
  feature.**

Standing practice regardless: split every forward outcome at the entry-day close
and quote the **day-D close → D+h** segment separately.

## Statistical practice

- **Row-level t-statistics are inflated ~2.9x (H016).** 63,698 mornings are ~650
  sessions and the cross-section moves together within a session. Use
  `explore.cluster_stats`, which reports clustered and naive side by side.
  `labelling.horizon_summary` still emits the naive one.
- **Matched controls must come from the same session (H020).** Drawing them from
  +/-2 sessions to fill thin cells tripled every contrast in Phase 2.8. Winners
  cluster on local market troughs, so a control two days away sits 0.45% higher
  in the market index on 71.2% of sets. `discovery.market_offset` prints the
  diagnostic every run and it must read 0.0000%. The tell was a discontinuity —
  |t| went from 4.3 at a 0-session band to 16.8 at 1 session, and real effects do
  not do that.
- **A search reports a maximum, so the bar is the permuted maximum.** Over 68
  features the 95th percentile of max |t| under the null is ~3.4, not 1.96.
  `discovery.permutation_null` shuffles the winner label *inside each matched
  set*, keeping every stratum intact and destroying only what is claimed.
- **A permutation null over a scan must shuffle the outcome within date.**
  Shuffling date-level means while leaving within-date deviations attached
  preserves the cross-sectional signal being tested and cannot reject anything.
- **Overlapping forward windows inflate every t-statistic, and clustering does
  not fix it.** A return over [t, t+h] shares h-1 days with the next one, so a
  daily IC series or a daily long-short spread is autocorrelated by
  construction. Measured on a null with *zero* predictive power: at h=20 the
  uncorrected t had a standard deviation of 5.1 instead of 1 and rejected at
  |t|>2 in **68%** of runs; at h=5, 37%. This is a *second* inflation on top of
  H016 — clustering by session fixes the cross-section within a day, this fixes
  the serial overlap across days, and a long-horizon claim needs both.
  `diagnostics.rank_ic`, `quantile_profile` and `cluster_stats(lags=...)` apply
  a Hansen-Hodrick (rectangular, lag h-1) correction and report the naive
  statistic beside it. Bartlett tapers away exactly the terms that carry the
  correction and is measurably worse here.
- **The correction cannot invent independent observations.** At h=20 over 400
  sessions there are ~20 non-overlapping blocks and residual over-rejection is
  8-13%. `rank_ic` reports `effective_n`; read a marginal long-horizon t
  against it. On real data this matters: `rs_60d_vs_mkt` on train reads naive
  t=-3.26 at h=5 and HAC t=-1.55 — significant becomes not.
- **A significant contrast is not a large one.** Phase 2.8's top feature has
  |t| = 4.3 over 2,446 matched sets and a win-rate lift of **1.06x**. A paired
  design detects shifts far below anything tradeable. Always report the effect in
  decision units — win rate by band, bps per trade — beside the t-statistic.
- **Price an outcome label before using it (H018).** A path-aware state called
  `clean_winner` — large MFE, reached fast — simulated at **+0.05% excess** under
  the stated exit rule. Naming a state does not make it a winner.
- **A score built by subtracting a factor is a sort on that factor (H038).**
  `resid = r − beta·r_mkt` looks like "resilience", but within one session
  `r_mkt` is a constant, so conditional on `r` the score is algebraically nothing
  but `beta` (per-session correlation 1.000000). Before believing an adjusted
  score is a new idea, project it off the thing it adjusts and look at what is
  left.

## Evaluation conventions

- **Divide the book by every slot it can hold, not by `top_k`.** The canonical
  construction opens a new cohort of `top_k` names every session and holds each
  for `holding_sessions`, so `top_k * holding_sessions` positions are open at
  steady state. Dividing by `top_k` runs it at `holding_sessions` leverage —
  it reported **334% CAGR on a universe compounding at 28.4%** at hold=10, and
  4600% at hold=20, while Sharpe looked fine because Sharpe is scale-invariant.
  A long-only book cannot out-compound every one of its constituents; if it
  does, the arithmetic is wrong.
- **Benchmark a partition-restricted book against both benchmarks.** On a
  shuffled split the test partition is non-contiguous, so the book sits in cash
  between quarters while a buy-and-hold index compounds straight through.
  `canonical_backtest` reports `market_benchmark` (invested throughout) and
  `market_benchmark_matched` (same cash pattern as the book); quoting only the
  first is not a comparison.
- **A market benchmark with too few priced names is unknown, not flat.** A
  silent 0.0% benchmark makes every signal look like alpha. Same `ret_guard`
  (0.6) and minimum breadth (50 names) as `context._daily_returns`.
- **Charge a book for its cash.** Annualise across the calendar span with cash
  sessions counted at zero, not over the sessions the book happens to hold
  something — that flatters any rule that goes flat. `family.span_stats` is
  correct; `shotgun.book_stats` is not. Compare against buy-and-hold over the same
  span, invested throughout.
- **Do not gate promotion on a purged-block stress test (H032).** Scored against
  the holdout afterwards, it killed two rules that were positive out of sample —
  one the phase's best — and kept one that was negative. Six blocks hold one
  regime apiece, so leave-one-block-out measures regime uniformity, not
  robustness. Compute it, report it, never let it decide.
- **Write the pass bar in units of the effect, not its sign (H037).** "Both
  horizons negative" was satisfied by −0.037%, indistinguishable from zero, and
  scored a PASS it had not earned. `family.PASS_CRITERION` demands a *fraction of
  the exploration effect retained* — copy that, not the sign test.
- **Freeze the bar before the run, and honour it after.** A bar applied only when
  it is passed is not a bar.
- **Keep the three layers separate**: signal diagnostics (*does information
  exist?*), canonical backtest (*is it economically large enough to care
  about?*), strategy research (*how would one trade it?* — later). Conflating the
  first two is what contaminated Phases 2.5 and 2.9.
- Transaction costs: 0.40% round trip is this project's measured conservative
  floor. Judge everything on **excess** return — a wider stop lengthens the hold
  and collects more market return, so raw payoff improves while excess worsens.

## Hypotheses — `HYPOTHESES.md` is research state, not documentation

Every meaningful hypothesis — proposed, tested, supported, rejected, or noticed
in passing — is recorded with a stable ID (`H001`, `H002`, …). It is the
project's research ledger and outlives any single refactor.

- **Record before moving substantially beyond it.** Writing the entry after the
  fact loses what the experiment actually tested, which is often not what it was
  later described as testing.
- **Never discard a negative result.** A rejected hypothesis is a result. One
  invalidated by a modelling bug is marked `SUPERSEDED`, kept, and annotated with
  the bug and the retracted claim — the next person with the same idea needs to
  know it was tried and why the answer did not count.
- **Never silently retest the same hypothesis under a new name.** Link the prior
  ID and say what changed. Under the new architecture this is also what the idea
  graph is for, and an unlinked hypothesis needs justifying.
- **Distinguish the three kinds of work** in every entry: hypothesis generation
  (noticing something in data already seen), exploratory testing (testing it on
  that same data), and confirmatory testing (testing on data not used to form
  it).
- **A hypothesis generated from a dataset is not confirmed by that dataset.**
- **Do not name a feature after a mechanism the data cannot see.** Volume is not
  buying volume; every trade has both sides. `persistent_demand` should have been
  `sustained_high_activity` — unusually much trading is equally consistent with a
  news event, two-sided disagreement, chasers, or institutions unloading. The
  catalogue describes what is *measured*; mechanism belongs in the hypothesis.

## Opening-window specifics (still true, now one family among many)

- **The entry time inside the window is a free variable.** For any `t`,
  `stop_price < running_low_t <= entry_price` must hold, where `running_low_t` is
  the minimum low from 09:15:00 through `t`. A stop above an entry is a bug — it
  means the low and the price were read at different moments. Phase 2.4 shipped
  exactly that (H004). Never use information after `t` to build the entry, the
  running low or the initial stop.
- **"Running low near the open" is a setup measure, not a stop-distance
  measure.** They are independent: open 100, running low 99.80, entry 103 gives a
  low 0.2% below the open and a stop 3.2% below the entry.
- **The stated stop is not a stop as measured.** At t=180s its median distance is
  0.41% against a median ATR of 3.37%. `discovery` floors risk at 0.5 x ATR.
  Widening a stop cannot break the invariant; narrowing one can.

## Conventions

- **`research_data` is the only door.** No experiment, report or worker opens a
  data file directly; if something is missing, add it to the module.
- **Partitions, never date ranges.**
- **Forward labels are counted in market sessions, and start at date D.**
  `groupby(symbol).shift(-h)` takes the h-th *traded bar*, which for a
  suspended name can be years away — 1.49% of rows spanned more than 20
  sessions, the worst 1,404, and 3,681 of them reached across a purged
  boundary. The purge is defined in sessions, so the label must be too or the
  purge does not bind. And the entry price comes from the bars, never from the
  panel: the as-of panel's `close` is *D-1's*, which made a "5-day" label span
  six sessions and swallow date D's own move (RELIANCE 2022-08-02 read +0.297%
  where D-close to D+5 was -0.083%).
- **A guard not called from the path it guards is documentation.** The
  catalogue knew `size_tier_rank` was unscorable and `evaluate_signal` scored
  it anyway. Guards belong at the chokepoint: `alpha_eval.guards.assert_scorable`
  runs inside `evaluate_signal` and `canonical_backtest`, and the ledger check
  runs inside `validate_spec`.
- **A bar has to be able to fail.** `spec.validate_pass_criterion` rejects a
  threshold of zero — a sign test wearing a number's clothes, which is how H037
  passed on -0.037% — and rejects anything inside transaction costs or inside
  the noise.
- **Count the questions, not just the answer.** A lab asking hundreds of cheap
  questions of 27 quarters is a multiple-comparisons machine running slowly.
  `runner.burden` records how many distinct signals a partition has already
  been scored against and moves the bar with it (Šidák on the running count,
  Benjamini-Hochberg across the set). At 50 tests the 5% bar is |t| > 3.28 and
  92% of runs that far would throw up at least one hit by luck. It labels, it
  does not veto — but "significant" must not quietly mean "significant among
  the fifty things we tried". Voided results do not count.
- **A result from a pipeline later found wrong is voided, not deleted.**
  `store.void_exploration(id, reason)` hides it from anything that aggregates
  and keeps it visible with the defect named. Nine explorations from before the
  hot-path fixes are voided on exactly this basis.
- **The forward lane is empty and that is normal.** `runner.forward.status()`
  says so in words, because an interface that looks broken gets worked around.
  Register a promoted signal with `forward.register(...)` and `forward.accrue()`
  scores it on whatever sessions have arrived.
- **A job records where it is, not just whether it lives.** `state` says
  alive or not; `phase` says which of `job.PHASES` it is in, written through
  to disk on entry, because almost all of an exploration's wall-clock is spent
  inside one state and one step of it. A job runs inside the request that
  dispatched it, so anything still `running` when the server starts belongs to
  a dead process: `job.reap_orphans()` marks those `interrupted` with the
  phase they died in, and never deletes them.
- **A suggestion is not a hypothesis until someone presses play.** Minting an
  H0xx for every idea a model has overnight would fill the ledger with entries
  no experiment ever ran against, so proposals live in `runner.suggest` and
  only `promote()` registers one — with its family and lineage edges, which is
  what the budget ledger reasons over. Nothing is deleted there either: a
  refreshed-away suggestion is kept as `replaced`, because the list of things
  already proposed is what stops the next generation proposing them again.
- **An unregistered hypothesis is blocked, not defaulted.** Resolving an
  unknown id to a "general" family granted it confirmatory access to spent
  quarters, because nothing is recorded against a family that does not exist.
  Register the hypothesis and its edges first.
- Thresholds live on config objects — never hardcode a belief.
- Daily panel order is **renames → corporate actions → indicators**, and it
  matters: adjusting before merging bakes a fake step into every handover.
  Anything keyed on symbol folds through `renames.canonical_map()`.
- Indicators on adjusted prices; anything asserting what was tradeable on `*_raw`.
- All Breeze traffic goes through `src/research_data/sources/breeze.py` (throttle, 429 retry,
  call logging to `data/metadata/api_calls.jsonl`).
- Verify empirically rather than trusting docs; that has repeatedly paid off.
- Long pulls run on the server (`user@server`) under tmux via
  `scripts/run_pull.sh`; resumable from the manifest. Watch the **log timestamp**,
  not the process list — a hung pull never exits and the supervisor cannot see it.
- `.venv/bin/python -m pytest tests/ -q` — keep green (403 tests). Tests marked
  `network` hit live NSE and are deselected by default; run with `-m network`.
  Leakage tests are part of the suite, not optional extras.
