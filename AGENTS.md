# brickbreak — agent notes

**What this is:** an AI-driven trading research laboratory for NSE equities.
`MISSION.md` is the authoritative statement of purpose and the question is:
*can an AI, given rich point-in-time context, identify unusually attractive
opportunities better than strong simple quantitative baselines?*

The unit of work is a *hypothesis*, investigated either by an **exploration**
producing a *signal* — a cross-sectional score over the panel — or by a
**replay** producing *decisions* on individual cases. Both accumulate
*evidence*, both spend the sample, and both are counted by the same
multiplicity machinery. See `PLAN.md` for how the lab is operated.

**Read order for a fresh session:** `MISSION.md` (what the project is for) →
`PLAN.md` (where this is going) → `FINDINGS.md` (what was measured) →
`HYPOTHESES.md` (the ledger, H001-H042).

**Three plans, and which one a `§` points at.** `PLAN.md` is the *current*
operating plan (2026-08-22), covering the discretionary loop. The plan it
replaced — the throughput-and-sample-budget plan of 2026-08-21 — is archived at
`archive/plan/PLAN_2026-08-22.md`, and **its dispatch pipeline, its label-free
pre-flight, its long-history section and both its non-negotiables tables remain
in force**; a `PLAN.md §5` or `§6` in a source docstring written before
2026-08-22 means that document. The architecture underneath both was specified
by the **refactor plan**, archived at `archive/plan/PLAN_2026-08-21.md`;
docstrings citing "the refactor plan §5.7" mean that one. Nothing in the pivot
relaxes anything in either.

**The phase gate is retired.** The old rule — no strategy or backtest code until
the current phase settles — served a single-strategy project and no longer
applies. What replaces it is stricter in the place that matters: no result counts
until it passes the leakage gate and the standard report.

## Repo layout, and the archive

| path | what |
| --- | --- |
| `MISSION.md` | why this project exists; authoritative over every other document |
| `PLAN.md` | current operating plan — the budgets and how they are spent |
| `FINDINGS.md` | evidence, chronological |
| `HYPOTHESES.md` | the research ledger, stable IDs, nothing deleted |
| `src/discretionary/` | the discretionary loop — cases, decisions, baselines, replay |
| `src/research/families/` | the opening-window screener. Every other (rejected) family was removed; see below. A **leaf**, never imported by the lab |
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

**Target state (see the refactor plan §5.1-5.2):** all market data reaches experiments
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

**The signal lab, end to end:** use the research-director path:
`discover --provider claude|codex` writes a provisional mechanism dossier;
`attack DOSSIER.json` sends it to an independent provider and preserves both
model and deterministic dissents; `qualify ADJUDICATION.json --signal NAME`
authors the signal in an empty, tool-free directory and freezes the E0
structural and signal preflights; `compile QUALIFICATION --reviewer NAME`
creates the immutable experiment contract and multiplicity batch; and only
`execute CONTRACT --confirm-outcome-access` crosses the outcome firewall. A
contract is one-shot: rerunning it is refused. `forward`, `burden`, `exposure`
and `serve` inspect results. The older `job`, `queue`,
`preregister` and `explore` commands remain compatibility plumbing while their
UI callers migrate; do not begin new research through them. Claude and Codex
are the supported subscription lanes. Install and log in to at least one:
`npm install -g @anthropic-ai/claude-code` then `claude`, or
`npm install -g @openai/codex` then `codex login`.

**The discretionary loop, end to end.** `python -m src.cli opportunity "<idea>"
--hypothesis H0xx` freezes an experiment definition — generator, case budget,
which judge, and the bar, all immutable from that moment. Then
`replay <ID> --phase generate | build | decide | reveal | evaluate`, one phase
at a time. `cases <ID>` prints a case exactly as the judge saw it and
`decisions <ID> --full` prints what it decided and why. The phases are separate
commands because `decide` and `reveal` sit on opposite sides of the seal, and a
single command that ran both would make it easy to forget which side you were
on.

**Built so far:** `src/research_data/splits.py` — versioned, purged,
quarter-level partitions, frozen as `data/metadata/split_v1_frozen.json`
(hash `657db79f7d380880`). Select rows with `splits.assign(df)`, never with a
date range. `python -m src.cli split --show` describes it.

**Current state, until the rest of the refactor lands:**
`research_data.pipelines.daily_panel.load()` defaults to the lagged
`screen_metrics_asof.parquet`. Extend `research_data`, do not add parallel
access paths beside it.

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
| **point-in-time F&O universe, futures OHLC, OI, lot size** | **NSE derivatives bhavcopy — legacy `fo{DDMMMYYYY}bhav.csv.zip` and UDiFF `BhavCopy_NSE_FO_*`** | **2020+ synced; both eras verified live 2026-08-25** |
| bulk / block deals, short selling | NSE `historicalOR/bulk-block-short-deals` (CSV) | bulk 2004-01-04, block 2005-11-17 |
| corporate announcements | NSE `api/corporate-announcements` | 2003 onward, dense from 2005 |
| result filings + XBRL | NSE `corporates-financial-results` **and** `integrated-filing-results` | 2005-03 onward, two regimes |

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

## Derivatives-archive gotchas (measured 2026-08-25)

The F&O bhavcopy is the only point-in-time source for *which securities were
tradable in derivatives on a session*. It matters because an NRI cannot trade
cash intraday and cannot short cash equities, so the executable universe is
F&O membership — not any cash turnover band.

- **Two eras, and the crossover is abrupt.** The legacy
  `content/historical/DERIVATIVES/{YYYY}/{MMM}/fo{DDMMMYYYY}bhav.csv.zip` serves
  through **2024-07-05** and 404s from 2024-07-08. UDiFF
  `content/fo/BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip` serves from
  ~2024-05 and 404s before. They overlap for about two months. Column names,
  instrument-type spellings (`FUTSTK`/`OPTIDX` vs `STF`/`IDO`) and units all
  differ; `sources/nse_derivatives.py` normalises both to one schema.
- **Units differ silently.** Legacy `VAL_INLAKH` is lakh rupees; UDiFF
  `TtlTrfVal` is rupees. A naive concat under-reports the legacy era by 10^5.
- **Only UDiFF reports lot size.** `NewBrdLotQty` exists from 2024 only. Before
  that the lot is *derived* as `traded_value / (contracts × close)`, which is
  exact to a rounding error but is a derived field — `lot_size_source` records
  which, because position quantisation on a small book is decided by the lot.
- **The holiday trap applies here too.** Same host, same convention as the
  equity bhavcopy: file the session under the date *inside* the file
  (`TIMESTAMP` / `TradDt`), never the date in the URL.
- **`UndrlygPric` is only in UDiFF**, and the legacy era has no underlying
  column at all — the cash leg must come from the equity bhavcopy.
- **Stock-futures lots are ~₹3-15 lakh, median ₹6.8 lakh** (measured across
  303,401 symbol-sessions), *not* ₹15 lakh. SEBI's Oct-2024 ₹15-lakh minimum
  contract value applies to **index** derivatives; single-stock futures kept the
  older floor. Only 0.5% of symbol-sessions exceed ₹15 lakh. At ~18% SPAN+
  exposure that is ~₹1.2 lakh of margin per position.
- **The universe churns.** 305 distinct symbols over 2020-2026, 140-216 live per
  session, and **only 102 present throughout**. A present-day F&O list is a
  survivorship trap for anything before today.

## Corporate-event gotchas (measured 2026-08-22, all silent)

The three event feeds — deals, announcements, result filings — come from
`www.nseindia.com`, not the archive host, through `sources/nse_api.py`. They
are collected by `sync-deals`, `sync-announcements` and `sync-filings`, and
timestamped by `build-events`.

- **The bulk/block route in every guide is dead.** `/api/historical/bulk-deals`
  and `/api/historical/block-deals` 503 permanently. The live route is
  `/api/historicalOR/bulk-block-short-deals?optionType=bulk_deals|block_deals|short_selling`.
  A dead route and a rate-limit block are both 503, so a collector written
  against the documented route retries forever instead of failing.
- **That endpoint's JSON form silently caps at 70 rows** — for any range, one
  day or one year — keeps the *earliest* 70, and honours no pagination
  parameter (`page`, `limit`, `start`, `length` all tried). A year-long request
  comes back looking like a complete answer for the first session of the year.
  `&csv=true` on the identical request is complete: 25,863 rows over 247
  sessions. **Always CSV.** This is the Breeze 1,000-row tail cap again.
- **A range wider than one year returns 500.** History is walked in yearly
  chunks.
- **Deal quantities use Indian digit grouping** ("6,91,650"). A thousands-
  separator parser mangles or drops exactly the large deals worth looking at.
- **The announcement feed is not capped** — two single days sum exactly to the
  two-day range. That equality is the check the deals endpoint fails, and it is
  worth re-running rather than assuming.
- **Announcement and filing timestamps are date-only in the early era.** 100%
  of 2005 announcements carry `an_dt` at 00:00:00; real intraday times appear
  from ~2008. Result periods start 2005-03 but the earliest broadcast timestamp
  is 2007-07. Reading a parsed midnight as the disclosure moment hands an
  experiment a full trading day. `time_known` records the distinction, which
  cannot be recovered later — NSE's overnight batch really does disseminate at
  00:00:04, so "is it midnight?" is not the test.
- **The results endpoint froze at the Integrated Filing switch.** Legacy
  `corporates-financial-results` holds periods to 2024-12-31 and broadcasts to
  2025-01, then stops; the post-2025-04-01 regime lives at
  `integrated-filing-results`. Reading only the legacy one looks healthy and
  holds no earnings after 2024. Both are fetched and `regime` records which.
- **There is no date-range form of the results endpoint** — `from_date`/
  `to_date` returns zero rows. It is per-symbol only, so a full backfill is
  ~3 requests per symbol rather than a date sweep. This is the expensive
  collector by an order of magnitude.
- **`(symbol, quarter)` is not a key.** Restatements are real and common —
  RELIANCE 6 periods with more than one filing, SUZLON 8, INFY 4. Every version
  is kept, `supersedes` links them and `is_latest` marks the survivor. The
  original is what the market traded on; the revision is what is true.
- **The XBRL files themselves only exist from 2018.** The metadata reaches
  2005, and it links a filing for every one of those records — but 556 of 940
  URLs across five symbols return 404, and the split is by date, not by
  symbol: **0% retrievable for period ends before 2018-03-31, ~60% from 2018
  onward** (the remainder being rows with no distinct filing). So filing
  *timing* is available from 2005 and filing *contents* from 2018. Any earnings
  study should state which of the two it depends on. This is also the argument
  for archiving: what NSE links today it may not serve tomorrow, and more than
  half of what it links right now is already gone.
- **In XBRL, the period does not identify a fact.** HDFC Bank's Q3 FY25 filing
  declares contexts `OneD` and `FourD` with the same entity, the same start and
  end dates and no dimensions, reporting InterestEarned as 850bn against one
  and 2,496bn against the other — the quarter and the year to date, with the
  YTD context's dates simply wrong. 30 such collisions in that filing, 37 in
  Reliance's, 0 in an integrated-regime one. `sources/xbrl.py` therefore returns
  a **long** fact table carrying `context_ref`, and `ambiguous_facts` reports
  the collisions. Assert it is empty over the elements you select before
  flattening anything into named columns.
- **Priming is insurance, not a requirement.** All four endpoints answered a
  completely cold session when measured. The client primes anyway, because
  NSE's tolerance varies by IP and over time — but no behaviour here depends
  on it, and a 503 is not evidence that priming failed.

### Event data is dated by disclosure, not by the event

`pipelines/events.py` derives `available_at` and `first_tradable_session`, and
those are the join keys. Every one of these rows carries an appealing date that
is *not* when the information existed: a bulk deal dated 14-Aug was published
after that day's close, a result for the quarter to 31-Dec was broadcast on
23-Jan, and a 2005 announcement carries no time at all. Joining an event table
to the daily panel on its own date is the H015 lookahead wearing a new hat.
Reach them through `frame.load_events`, which partitions on the tradable
session and will not hand back a row before it was knowable.

`load_events(..., latest_revision_only=True)` is off by default and warns:
restated figures are correct for describing a company and a lookahead for
scoring one.


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

- **The as-of-open panel's four price columns are not one candle.**
  `daily_panel.load()` serves the as-of panel, where `open` is date D's opening
  print — knowable at 09:15 and deliberately unlagged — while `high`, `low` and
  `close` carry date D-1's session (`pipelines.asof`). That is correct for a
  morning screener and wrong for anything that draws a bar, computes a body, or
  prices against a range: it mispaints the candle *and* hands you the next
  session's opening print. `assert_no_forward_labels` does not catch it, because
  it looks for `fwd_ret_`-prefixed columns and this arrives in a column called
  `open`. Draw from `corporate_actions.load_adjusted()`, which is session
  aligned. The cheapest tell is that an honest bar's open always sits inside its
  own `[low, high]`; `setup_grind.assert_session_aligned` checks exactly that and
  is worth reusing. Found while building H058's deck, after the first render
  showed only 38% of bars closing at or above their open.

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

## Discretionary conventions

The signal path's rules all still apply — a case is a bundle of features, so it
inherits every lookahead rule above. These are the additional ones.

- **The case is the dangerous object.** Everything downstream of it is
  arithmetic. `tests/test_case_pit.py` builds a case against a panel truncated
  at D and against the full panel and requires the bytes to be **identical**;
  write that test before trusting any new block. `case.py` deliberately derives
  almost nothing — it *selects* columns the pipelines already build under test,
  because the denominator trap is how three of the four lookaheads got in.
- **A decider is not frozen the way a function is.** A signal is code: run it
  twice on the same frame and it is the same test. A decider is a *prompt
  version, a model and a case set*. Changing the prompt while keeping the other
  two asks a new question of the same finite history with nothing about it that
  looks like a second dispatch. `identity_hash` is that triple and `burden`
  counts it.
- **Anonymise by default, and treat revealed identity as a paired control.** A
  model may simply remember what a named NSE stock did in a named quarter, and
  no frame hygiene closes a leak that lives in the weights. H042 is the control
  that licenses reading an anonymised result as judgement; until it has been
  run, every discretionary finding carries an asterisk.
- **A judge gets the case and nothing else.** `runner.agent.run_agent` defaults
  to Read/Write/Edit/Bash because it exists to author signals. The decision path
  passes `allowed_tools=()` and an empty directory. A judge with Bash can open
  the parquet holding the outcome it is scored on, and would not have to intend
  anything for the result to be worthless.
- **Never drop a failed call.** Baselines see every case; an arm missing its
  failures is scored on an easier population, and the difference looks exactly
  like skill. A failure is a recorded SKIP carrying its error.
- **Baselines run at the AI's own take rate.** Selectivity and skill are
  otherwise confounded — a 12%-selective arm beats a 100% arm on any pool that
  is better than average, with no skill involved. `take_all` is the exception
  and is not matched: it *is* the pool.
- **A weak baseline flatters the selector, so the bias must run the other way.**
  `rank_model` refits walk-forward rather than fitting once and going stale, and
  it fits on the whole dataset version rather than the evaluation partition.
- **Every contrast is paired within the session (H020).** A per-session
  difference of means, on sessions carrying both arms. A session with only one
  arm says nothing about their difference, and including its level smuggles the
  session's own market move into the contrast.
- **`resolved_by`, never the row's own date.** An analogue from three sessions
  ago has not resolved at a ten-session horizon; filtering on its date hands the
  judge a return from after its own decision. The same rule governs the
  rank-model fit.
- **The bar is in basis points, not in t.** Measured on 60 null selectors here:
  the corrected |t| exceeds 1.96 **13.3%** of the time at this block count
  (sd 1.40), while a bps-denominated bar rejected the same nulls 59 times in 60.
  The report prints `independent_blocks` and says outright not to promote on a
  t-statistic. This is the same lesson H039 taught the signal path — the lab is
  short of magnitude, not of significance — arriving from a different direction.
- **Generation is not selection.** A generator tuned until it looks profitable
  has stolen the experiment, because the lift is then measured against a
  baseline that already contains the answer. A narrow generator also flatters
  the selector by hiding its hard cases. Prefer `liquid_universe`.
- **The budget is spent at `reveal`, not at `freeze` or `decide`.** Everything
  before the reveal is replaceable — tokens and compute. A replay abandoned
  before it costs nothing, which is the same economics as label-free pre-flight.

## Families are a leaf, not the architecture

`src/research/families/` holds only the opening-window screener, which the
screener API and one discretionary generator bind to. Nothing in
`src/discretionary`, `src/alpha_eval`, `src/research_data`, `src/persistence`,
`src/runner` or `src/core` may import from it — the dependency runs one way and
`tests/test_architecture.py` enforces it, including for dynamic imports.
`src/interface` is exempt.

**Removed code.** The opening-window research pipeline (H001-H033), resilience,
wheel, covered-call, bulk-deals, setup-grind, level and price-action studies,
their one-off scripts, the setup-review UI and the `suggest`/`plan` plumbing were
deleted once their hypotheses were rejected. Their measurements are in
`HYPOTHESES.md` and `FINDINGS.md`; to reproduce one, check out the git tag
`pre-compression`.

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
- **Any data pull estimated to take more than five minutes runs on the remote
  laptop, never in the local agent session.** Connect through Tailscale using
  the local SSH alias `hp-ts` (`ssh hp-ts`); keep the actual Tailscale IP in
  `~/.ssh/config`, not in repository documentation. Start the pull inside a
  named `tmux` session, make it resumable from a manifest/checkpoint, and write
  progress to a durable log/status file. Verify the tmux session, a fresh log
  timestamp and a moving checkpoint before considering the handoff successful.
  Watch the **log timestamp**, not merely the process list — a hung pull can
  remain alive while making no progress. The existing opening-data supervisor
  is `scripts/run_pull.sh`; use the same pattern for new long-running pulls.
- The corporate-event equivalent is `scripts/run_events.sh` ->
  `scripts/server_events.py`, status in `data/metadata/events_pull_status.json`,
  pulled back with `scripts/sync_events_from_server.sh`. Only the filings +
  XBRL stage is worth offloading (hours to days); deals is ~2 minutes and
  announcements ~10, so run those locally. Resumption needs no checkpoint —
  every collector caches its raw payload before parsing and skips what it
  holds, so killing and restarting resumes exactly where it stopped.
  **The sync-down brings back raw caches only**: the normalized event tables
  are rebuilt locally by `build-events`, because availability timestamps are
  derived against the local trading calendar and a table built on a staler
  tape would disagree with the panel.
  There is no session token here, so the overnight-death failure the Breeze
  pull guards against cannot happen. The one that replaces it is **blocking**:
  Akamai judges a datacenter IP more harshly than a residential one, and the
  endpoints were only verified from a laptop. `server_events.py` makes one
  cheap request before doing anything and exits 2 if NSE will not answer that
  host, because a backfill that discovers this on request 6,000 leaves a
  directory of empty payloads indistinguishable from "this symbol has no
  filings".
- `.venv/bin/python -m pytest tests/ -q` — keep green. Tests marked
  `network` hit live NSE and are deselected by default; run with `-m network`.
  Leakage tests are part of the suite, not optional extras.
