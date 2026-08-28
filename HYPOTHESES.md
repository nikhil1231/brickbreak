# HYPOTHESES.md — research ledger

Persistent record of every meaningful hypothesis this project has proposed,
tested, rejected or stumbled into. **Nothing is deleted.** A hypothesis that
failed is a result; a hypothesis invalidated by a modelling bug is marked
`SUPERSEDED` and kept, with the bug described, because the next person to have
the same idea needs to know it was already tried and why the answer did not
count.

**Source relocation (2026-08-21).** Historical `src/<module>.py` references
below identify the code paths used at the time. Their current homes are under
`src/research_data/` and `src/research/`; hypothesis text and evidence remain
unchanged.

Statuses: `PROPOSED` · `TESTING` · `SUPPORTED` · `REJECTED` · `INCONCLUSIVE` ·
`SUPERSEDED`

Three kinds of test are distinguished throughout, because they carry very
different weight:

- **hypothesis generation** — noticing something in data already looked at;
- **exploratory** — testing it on that same data;
- **confirmatory / out-of-sample** — testing it on data not used to form it.

Nothing in this project has yet reached the third category. The 2020-04 → 2023-08
backfill, in progress as of 2026-08-19, is the first genuinely unseen data.

Entries H001–H006 were written retrospectively on 2026-08-19, covering work
already done in Phase 2. They record what each experiment actually tested, which
is not always what it was described as testing at the time.

---

## H001 — Enter at 09:20 at the close of the opening window

Status: **REJECTED** (as stated; see caveats)

Date proposed: 2026-08-19 (retrospective — this is what Phase 2.4 actually built)
Date last tested: 2026-08-19

**Hypothesis:**
Take the screener's candidates, wait for the five-minute opening window to
complete, and buy at `close_5m` (the last traded price by 09:20). Holding for
1/3/5/10 sessions produces a positive return in excess of the market.

**Origin:**
Not the uncle's rule. It is the simplification Phase 2.4 adopted so that a
single, unambiguous entry price existed to label against — the first price a
rule reading five-minute features could definitely have acted on. It was
described in the Phase 2.4 write-up as *the* strategy entry, which was wrong;
see H004 and the correction note below.

**Test:**
63,698 candidate symbol-days, 2023-08-21 → 2026-08-18. Entry `close_5m` lifted
onto the adjusted price basis. Forward returns to the adjusted close at +1/3/5/10
sessions, against an equal-weighted same-session benchmark of all EQ symbols.
`src/labelling.py`, `python -m src.cli label`. Exploratory.

**Result:**

| horizon | n | mean | median | hit | mean excess | t |
| --- | --- | --- | --- | --- | --- | --- |
| +1d | 63,562 | +0.11% | -0.14% | 47.1% | +0.05% | 4.2 |
| +3d | 63,297 | +0.16% | -0.26% | 46.7% | +0.04% | 2.2 |
| +5d | 63,009 | +0.20% | -0.34% | 46.5% | +0.02% | 1.0 |
| +10d | 62,069 | +0.47% | -0.48% | 46.8% | +0.05% | 1.5 |

**Interpretation:**
Unconditional holding of these candidates from 09:20 has no economically
meaningful edge. The mean is positive while the median is negative at every
horizon — a right-skewed distribution in which fewer than half the mornings
work. The excess is 0.02–0.05%, inside any realistic cost, and at +5d is not
statistically distinguishable from zero either.

**Caveats:**
This rejects the 09:20 entry, **not the discretionary strategy**, which enters
at an unknown point inside the window (H004). Single regime, 2023-2026, rising
market. No exits modelled — see H006.

**Two corrections added 2026-08-19, neither of which rescues the entry:**
- **The t-statistics above are naive** and overstate significance by ~2.9x
  (H016). Date-clustered they are 1.41 / 0.99 / 0.45 / 0.83. The +1d excess,
  the one number here that looked solid, is not distinguishable from zero. The
  rejection stands more firmly, not less.
- **The pool itself is contaminated** (H015): the screener selects each morning
  using that morning's own closing price. This does not change the verdict on
  the 09:20 entry but it means the pool is not one that could have been traded.

**Next step:**
Re-run on the 2020-2023 backfill when it lands. Keep as the baseline any
intrawindow entry rule must beat.

---

## H002 — Tighter gap and opening-volume cut-points concentrate the edge

Status: **REJECTED**

Date proposed: 2026-08-19 (Phase 2.3 posed it; Phase 2.4 tested it)
Date last tested: 2026-08-19

**Hypothesis:**
The uncle's entry filters — a "modest gap" and "strong opening volume" — select
better mornings, so raising either threshold should raise forward returns. Phase
2.3 produced a grid of candidate cut-points and explicitly deferred the choice
to forward returns.

**Origin:**
The uncle's stated rules, made numeric.

**Test:**
Same panel and entry as H001. Excess return at +5d for each cell of the Phase
2.3 grid, plus a gap-floor scan. Exploratory.

| gap band | vol ≥ 5% | vol ≥ 10% | vol ≥ 20% |
| --- | --- | --- | --- |
| [0, 1] | -0.22% (n=10,765) | -0.46% (n=3,425) | -0.95% (n=916) |
| [0, 2] | -0.24% (n=13,114) | -0.51% (n=4,709) | -1.02% (n=1,480) |
| [0, 3] | -0.25% (n=13,636) | -0.52% (n=5,071) | -1.04% (n=1,699) |
| [-1, 2] | -0.17% (n=16,045) | -0.48% (n=5,508) | -0.98% (n=1,678) |

Gap-floor scan, excess at +5d: -0.02% above 0%, -0.13% above 1%, -0.46% above
2%, -0.99% above 3%.

**Result:**
Every cell is negative. t-statistics run -3.3 to -7.0. Both filters worsen
monotonically as they tighten.

**Interpretation:**
At this entry, the filters are not merely uninformative — they are inverted.
Raising either threshold destroys value rather than concentrating it. The Phase
2.3 question "where should the cut-points go?" has an answer, and it is "not
higher".

**Caveats:**
Conditional on the H001 entry, and H005 shows the entry is doing much of the
damage. This does not establish that gap and volume are uninformative at an
intrawindow entry — only that filtering on them and then buying at 09:20 loses.

**Corrections added 2026-08-19:** the cell t-statistics of -3.3 to -7.0 are
naive; clustered by date they are roughly -1.1 to -2.4 (H016). The direction
survives, the confidence does not. The pool is also subject to H015.

**Partly answered by H009.** Entering *earlier* does not rescue the volume
filter: the top-minus-bottom volume quintile spread is -0.47% at t=30s against
-0.54% at t=300s. Whatever the volume filter is doing wrong, it is not the
entry-slippage of H003.

**Next step:**
Re-test once an intrawindow entry model exists (H004), and on the backfill.
Until then the filters should not be used to gate anything.

---

## H003 — The first five minutes consume the apparent edge

Status: **SUPPORTED** (mechanism, exploratory)

Date proposed: 2026-08-19 (data-generated, while investigating H002)
Date last tested: 2026-08-19

**Hypothesis:**
The move between the opening print that selects a morning and the price
available at 09:20 runs systematically against the selected mornings, and
explains a large part of H002's negative result.

**Origin:**
Data-generated — proposed to explain H002, tested on the same data. Exploratory.

**Test:**
`entry_slippage_pct` = `close_5m / open_raw - 1`, profiled by gap bucket and by
opening-volume bucket. Then H001 re-run with entry at `open_raw` (the auction
print, which is *not* actionable for a rule reading the window) as a
counterfactual.

**Result:**
By opening volume: -0.06% mean in the lightest bucket rising monotonically to
+0.73% in the heaviest (>40% of median daily volume), with 62.9% of those
mornings up. By gap: +1.16% mean on mornings gapping below -2% (they recover),
falling to -1.13% above +5% (they give back). Re-running at `open_raw` improves
the heaviest volume bucket's +5d excess from -1.80% to -1.11%, and flips the
5–10% bucket from -0.01% to +0.07%.

**Interpretation:**
The window moves while it is being measured, and it moves against exactly the
mornings the stated filters select: gaps mean-revert and volume runs. Roughly
half of H002's damage is located here. This is a mechanism, not a strategy.

**Caveats:**
`open_raw` is not tradeable by anyone reacting to the opening window, so the
counterfactual locates the effect rather than offering an alternative. Same
single window and regime.

**Narrowed 2026-08-19 (H009/H014).** The slippage mechanism is real but it does
*not* account for the volume filter's negative result: measured at t=30s, before
almost any of the window's move, the volume quintile spread is essentially
unchanged (-0.47% against -0.54% at t=300s). H003 explains the *level* shift
between the auction print and 09:20; it does not explain the *cross-sectional*
ranking of heavy-volume mornings.

**Next step:**
This is the strongest argument for modelling the entry inside the window (H004)
rather than at its close.

---

## H004 — The stop sits close to the entry because the opening low is close to the open

Status: **SUPERSEDED**

Date proposed: 2026-08-19
Date last tested: 2026-08-19

**Reason:**
The test paired `om_low` — the low of the **first minute** (09:15–09:16) — with
an entry at **09:20**, five minutes later. Those are different times and nothing
ties them together, so the "stop" was not constrained to sit below the entry.
It exceeded the entry on **31.96%** of mornings, by up to +6.53%, and the
write-up reported that as a property of the strategy ("the stop is already
breached before the position exists"). It was a property of the pairing.

**What was claimed, and is now retracted:**
That "below the opening-candle low" is a median 0.22% from the entry, positive
above p75, and therefore "not a risk control but a near-immediate exit". None of
that survives the correction. **Do not cite it.**

**The correct formulation** (user, 2026-08-19). For any entry time `t`:

    stop_price < running_low_t <= entry_price

where `running_low_t` is the minimum low from 09:15:00 through `t`. Because the
running low includes the moment being entered on, it cannot exceed the entry
price; a stop above an entry is a bug, not a market state. Separately: the
running low being close to the day's open is a statement about the **setup** and
implies nothing about the **stop distance**, because the entry may sit well above
both. Open 100, running low 99.80, entry 103 — the low is 0.2% below the open
and the stop is 3.2% below the entry.

**Corrected result:**
Pairing the low and the price at the same `t` violates the invariant on 0.00% of
the same 63,698 mornings (`low_5m` vs `close_5m`), and on 0 of 464,318 rows
across a seven-point grid of entry times. `src/entry_window.py` computes the
grid and `check_invariant` raises on any violation; `src/labelling.py` asserts
the same before producing a stop. Superseded by H005.

---

## H005 — Stop distance is a function of the entry time, not a fixed property

Status: **SUPPORTED** (descriptive, exploratory)

Date proposed: 2026-08-19 (replaces H004)
Date last tested: 2026-08-19

**Hypothesis:**
With the running low and the entry price read at the same moment, the distance
from entry to stop varies systematically with where in the window the entry
happens, and in particular widens on the mornings where price has advanced from
the open — which are the mornings the setup is looking for.

**Origin:**
The user's correction to H004, made testable.

**Test:**
`src/entry_window.py`, `python -m src.cli entry-window`. 1-second ticks
evaluated at t ∈ {30, 60, 90, 120, 180, 240, 300}s after 09:15:00, no
information used past `t`. 464,318 symbol-day-times. Stop placed 0.10% below the
running low (a placeholder, not a tuned parameter). Exploratory.

**Result:**

| t | median low vs open | median stop distance | stop wider than 1% |
| --- | --- | --- | --- |
| 30s | -0.04% | -0.16% | 4.2% |
| 60s | -0.14% | -0.29% | 7.0% |
| 120s | -0.26% | -0.36% | 11.5% |
| 300s | -0.38% | -0.47% | 17.2% |

Conditioned on how far the entry has advanced above the open, at t=300s:

| entry vs open | n | median stop distance | median low vs open |
| --- | --- | --- | --- |
| below -0.5% | 15,719 | -0.27% | -1.09% |
| 0 to +0.5% | 16,606 | -0.49% | -0.13% |
| +0.5 to +1% | 9,443 | -0.83% | 0.00% |
| +1 to +2% | 5,505 | -1.36% | 0.00% |
| above +2% | 1,256 | -2.41% | +0.03% |

**Interpretation:**
The invariant holds everywhere. Stop distance widens with `t` — later entries
have had more chance to print a lower low — and widens sharply with how far the
entry has advanced from the open. On mornings where price is 2%+ above the open,
the running low sits *at* the open (median +0.03%, the tight setup the rule
wants) while the stop is a normal 2.41% below the entry. The pool-wide median of
-0.47% is an average dominated by mornings that never advanced at all, and is
not the number a real entry rule would face.

**Caveats:**
Descriptive across a grid; no entry rule has been chosen and `t` is still a
discovery problem. The 0.10% buffer is arbitrary. Selecting `t` per morning by
looking at the whole window would be lookahead — the grid is evaluated causally
at each `t`, but a *rule* that picks `t` must also be causal.

**Next step:**
Feed into the intrawindow entry discovery work. Do not pick one of these offsets
and call it the strategy.

---

## H006 — A stop-and-target rule can extract a positive expectancy despite H001

Status: **RESOLVED — REJECTED** (2026-08-19 via H017; was INCONCLUSIVE)

Date proposed: 2026-08-19
Date last tested: 2026-08-19

**Hypothesis:**
H001 rejects unconditional holding, but the strategy never holds
unconditionally: it uses a stop below the running low, a +15-20% target, a
half-off at target, a breakeven stop and a 10-EMA trail. That exit structure may
be where the expectancy lives.

**Origin:**
The uncle's stated rules; raised by H001's rejection.

**Test:**
Excursion bounds from daily bars at the H001 entry. Exploratory.

**Result:**
Mean MFE at +10d is +6.82% against mean MAE of -5.25%. 10.84% of mornings touch
+15% within ten sessions; 88.25% touch the stop implied by the running low
through 09:20 (0.10% buffer); **6.49% (4,030 mornings) touch both**. Rates are
computed only over completed horizons — counting truncated windows as "not
touched" deflated an earlier version of these numbers.

**Interpretation (superseded — see the corrected version below):**
Cannot be resolved. On the mornings that touched both, the outcome depends
entirely on **which came first**, and a daily bar does not record intraday
ordering. The bounds are wide enough that both a profitable and an unprofitable
answer sit inside them.

**Corrected 2026-08-19.** The bounds are *not* wide. Simulating the rule rather
than bounding it with MFE/MAE shows the expectancy is -0.13% excess and the
ordering ambiguity is worth 0.002% of it. The exit structure is not where the
expectancy lives; it makes the result modestly worse than the fixed-horizon
label. See H017.

**Caveats:**
The stop touch rates are computed at the H001 entry and inherit its problems;
H005 shows a real entry would face a wider stop, which would lower them. Daily
MFE/MAE also cannot see intraday paths within a single session.

**Next step — ANSWERED 2026-08-19 by H017, and the answer is no.**

**The premise of this entry was wrong.** It counted the 6.49% of mornings that
touched both the target and the stop *within ten sessions* as the ambiguous
set. But ordering across **different** sessions is known — the dates say which
came first. Only a stop and a target touched in the **same session** is
genuinely undetermined, and with a stop ~2% below entry and a target at +15%
that needs a ~17% single-session range. It is rare.

Simulating the full rule and resolving every same-session ambiguity first for
and then against the trade (`src/payoff.py`, `python -m src.cli payoff`):

- trades the data genuinely cannot resolve: **10 of 63,698 (0.02%)**;
- expectancy hanging on the answer: **0.002%**, and never above 0.009% at any
  stop width from 0.5% to 8%.

**The full-session intraday pull is not justified by this question.** It would
buy two thousandths of a percent of expectancy. Whatever else that pull is for,
H006 is no longer the reason, and the standing decision it was blocking is
settled.

---

## H007 — Gap-down mornings outperform gap-up mornings in this pool

Status: **PROPOSED** (data-generated, untested out of sample)

Date proposed: 2026-08-19
Date last tested: never — exploratory observation only

**Hypothesis:**
The stated strategy buys follow-through on a modest gap up. This pool suggests
the opposite: mornings gapping *down* 1-2% outperform.

**Origin:**
**Data-generated.** Noticed in the H002 bucket table on the same data that
produced H002. It has not been tested on anything else and must not be presented
as a result.

**Test:**
None yet. The observation: the -2% to -1% gap bucket shows +0.38% excess at +5d
with a 52.2% hit rate, against 46.5% pool-wide, and is the best-performing cell
in the table. H003 supplies a plausible mechanism — gaps mean-revert across the
opening window.

**Interpretation:**
A hypothesis, not a finding. It was generated by the same data that would
"confirm" it, and the pool contains many overlapping cells, so some cell was
always going to look best.

**Caveats:**
Multiple-comparisons risk is severe: this is the best of ~11 buckets, chosen
after seeing them. n=1,708. Entirely in-sample.

**Next step:**
Test on the 2020-04 → 2023-08 backfill as genuine out-of-sample data, with the
bucket definition fixed **before** looking. That is the first confirmatory test
this project would have run.

---

## H008 — The opening window carries behavioural structure beyond gap and volume

Status: **PROPOSED** → see H009–H014 for the individual tests

Date proposed: 2026-08-19

**Hypothesis:**
The discretionary strategy is not a threshold rule over `(gap, volume, t)`. It
recognises a *developing behavioural pattern*: contraction, favourable
sector/stock trend, constructive open, unusually strong and **sustained**
demand, sellers failing to push price materially below the open, and a path
that resembles accumulation rather than a spike. If so, second-level features
describing the **shape** of the opening — persistence, acceleration, path
orderliness, price response to volume, repeated recovery — should carry
information that `gap_pct` and `vol_5m_pct_of_median_daily` do not.

**Origin:**
The user's reframing (2026-08-19), following H001/H002's rejection of the
09:20 entry and the two stated filters. Explicitly an exploration mandate:
"explore this bounded strategy family freely… every resulting finding must be
logged as EXPLORATORY / DATA-GENERATED, never as confirmed."

**Standing constraints on everything under H008:**
- **Exploration set is 2023-08-21 → 2026-08-18 only.** The 2020-04 → 2023-08
  backfill is holdout and is fenced off in code (`explore.EXPLORE_START`), not
  by convention. Any tick file outside the window raises.
- Nothing discovered here may be promoted into the strategy. Findings are
  ranked and frozen; confirmation requires the untouched backfill.
- Prefer **broad stable regions** over optimal cut-points. A result that needs
  a specific decimal is treated as noise until proven otherwise.
- Every reported effect carries n, effect size, a subperiod split and a sector
  split. An effect that does not survive those is reported as unstable, not
  quietly dropped.

**Measurement constraints discovered while building this (2026-08-19):**
- Breeze's `1second` series is **not full tick data**. Median inter-bar gap is
  5s (p90 8s, p99 15s), ~54 bars per morning across the 300s window. Sub-30s
  temporal features are not supported by the data; 30s buckets are the floor.
- **~50% of bars carry `volume == 0`** and 94% have OHLC all equal — these are
  price snapshots, not trades. 27.8% of zero-volume bars are immediately
  followed by a bar at the *same price* with volume, i.e. **volume is smeared a
  few seconds relative to price**. Window totals are sound; 1-second volume
  timing is not. All volume-shape features are computed on 30s buckets.
- **Opening volume decays through the window by default** — pool-mean shares by
  30s bucket run 15.4%, 9.6%, 13.2%, 12.0%, 10.2%, 9.0%, 9.9%, 7.3%, 7.1%,
  6.4%. "Front-loaded" is the *norm*, so persistence must be measured against
  the pool's decay profile (cross-sectional rank within date), never against a
  flat prior — otherwise every morning scores as a fading spike.
- **Tick count is itself a liquidity variable** and is the mechanism behind the
  Phase 2.3 censoring of `om_low_vs_open_pct`. It is carried on every row so
  that any low-vs-open result can be conditioned on it rather than confounded
  by it.

---

## H009 — Sustained demand beats one-off volume

Status: **REJECTED as stated**; the reverse is **SUPPORTED (exploratory)**

Date proposed: 2026-08-19
Date last tested: 2026-08-19

**Hypothesis:** Conditional on the same total opening volume, mornings where
that volume arrives *persistently* across the window outperform mornings where
it arrives as a single early burst. Distinguishes "accumulation" from "a print".

**Measures:** volume Herfindahl across 30s buckets, active-bucket fraction,
late/early volume-rate ratio, all ranked cross-sectionally within date to
neutralise the pool's default decay shape.

**Test:** `src/behaviour.py` + `src/explore.py`. 63,698 mornings, 2023-08-21 →
2026-08-18, entry at `price_t`, outcome `excess_ret_5d_pct`, date-clustered
inference throughout. Exploratory.

**Result — the sign is the opposite of the hypothesis.** Quintile spreads
(top minus bottom) in +5d excess at t=300s:

| measure | spread | monotone |
| --- | --- | --- |
| total opening volume | **-0.54%** | 0.75 |
| trade frequency (`tick_rate_t`) | **-0.51%** | 0.75 |
| persistence (`active_bucket_frac`) | **-0.48%** | 0.75 |
| concentration (`vol_hhi`, bursty = high) | **+0.47%** | 1.00 |
| late/early volume ratio | +0.07% | 0.75 |

And it is a genuine interaction, not a restatement of total volume. Splitting
persistence *within* each total-volume quintile, the effect is confined to the
heavy end:

| total volume | persistence low | persistence high | spread | t |
| --- | --- | --- | --- | --- |
| q1 (lightest) | +0.447% | +0.157% | -0.29% | -1.90 |
| q3 | +0.180% | -0.044% | -0.22% | -0.94 |
| q5 (heaviest) | +0.179% | **-0.625%** | **-0.80%** | **-3.04** |

**Interpretation — downgraded 2026-08-19, read this before the table above.**
The measured pattern is that heavy volume arriving as *one burst* is roughly
neutral (+0.18%) while heavy volume that keeps arriving is the bad state. But
**the contraction screen can manufacture exactly this** (H015): a persistent-
demand morning that kept running all day fails the day-D contraction filter and
is excluded, while one that faded into a narrow range is kept. The pool retains
the failures and discards the successes.

So the honest statement is **not** "sustained buying is bearish". It is: *in a
pool selected on the entry day having been quiet, mornings with sustained heavy
opening activity did worse, and the selection alone could produce that.*

The part worth preserving rather than explaining away is the **contrast**:
concentrated/bursty volume did better than persistent volume. If the uncle's
"strong volume" means an explosive initial burst followed by price holding firm,
that is a different and independently testable claim.

**Also: the name was wrong.** Volume is not buying volume — every trade has a
buyer and a seller. What is measured is "unusually much trading kept occurring
and price did X", which is equally consistent with a crowded news event,
two-sided disagreement, breakout chasers, institutions unloading into eager
buyers, or an opening move already exhausting. Calling it `persistent_demand`
asserts a mechanism the data cannot see.

**Caveats — these matter more than the result:**
- **Most of it is not forward-looking.** Decomposed into the entry-day segment
  (09:20 → day-D close) and the genuinely forward segment (day-D close → D+5,
  net of benchmark), the -0.54% volume spread is -0.35% entry-day and -0.19%
  forward. See H015: the screener conditions on day-D's own close, so the
  entry-day segment is not a clean measurement.
- What survives into the forward segment is roughly -0.19% to -0.30% and is the
  strongest *surviving* behavioural family, but it is a third of the headline.
- The late/early ratio shows nothing, so "acceleration" is not the operative
  variable; spread-versus-concentrated is.
- Not confined to illiquid names: the heavy-and-persistent cell is negative in
  **all five** turnover quintiles, including the most liquid (-0.59%, t=-3.88,
  median turnover Rs 53 cr), though it is largest in the thinnest (-1.90%).

**Next step:** freeze the tercile definition and test on the backfill.

---

## H010 — Price refusing to trade below the open is the real "tight low" signal

Status: **INCONCLUSIVE** (measure is sound; predictive content is near zero)

Date proposed: 2026-08-19
Date last tested: 2026-08-19

**Hypothesis:** The uncle's "low not far below the open" is better captured as
*time spent above the open* and *repeated rejection of dips* than as the
distance `low/open - 1`, which Phase 2.3 showed is censored at zero and rewards
illiquidity. Time- and tick-based occupancy measures should be informative
where the distance measure is not, and should not carry the same liquidity tilt.

**Result — the measure works, the signal does not.**
`time_above_open_frac` is dwell-weighted and is **not** censored: it spreads
across [0, 1] with a median of 0.66, against `low_vs_open_pct`'s 36% pile-up on
zero. So the construction problem Phase 2.3 identified is solved.

But it predicts almost nothing. Quintile spread in +5d excess is **-0.02%** at
t=300s (and -0.01% at t=60s, -0.02% at t=120s) — flat at every entry time. On
the forward-only segment it turns weakly positive (+0.16%, monotone 0.75), which
is the smallest effect of any feature examined and is not separable from noise
after multiplicity.

`low_vs_open_pct` itself is equally flat (-0.05% spread), so this is not a case
of the new measure failing to beat the old one; **neither carries information**
in this pool at this horizon.

**A lookahead was found and fixed here, and it is worth recording.** The first
implementation summed each bar's dwell time using the gap to the *next* bar.
For the last bar at or before `t`, that next bar lies *after* `t`, so the
feature depended on when the market next traded — information from the future.
A morning that went quiet after 09:16:30 and one that kept trading got different
answers at t=90s for the identical first 90 seconds. `features_at` now replaces
the final bar's contribution with the time actually remaining to `t`, and
`test_features_at_t_ignore_everything_after_t` is the regression test. Correcting
it did not change the conclusion above.

**Next step:** none as a standalone signal. Retain the measure as a conditioning
variable, since it is the only uncensored form of "held above the open".

---

## H011 — Price response to volume separates absorption from supply

Status: **PARTIALLY SUPPORTED** (exploratory)

Date proposed: 2026-08-19
Date last tested: 2026-08-19

**Hypothesis:** Heavy volume with little price progress is a different, worse
state than heavy volume with price progress that *holds*. Measured by price
versus opening VWAP, uptick volume share (tick rule on the last price change),
return after the heaviest volume bucket, and move-per-unit-volume.

**Result:**
`move_per_vol` — price progress per unit of unusual volume — has a **+0.39%**
quintile spread with **monotone = 1.00**, one of only two perfectly monotone
features found. Low progress per unit volume is the bad state, as predicted, and
it holds on the forward-only segment too (+0.19%).

The archetype version says the same thing in words: `heavy_vol_no_progress`
returns **-0.27%** (t=-3.26), and it is the **only** archetype whose effect is
majority-forward (-0.17% forward, t=-2.31, against -0.11% entry-day). Every
other archetype's effect is dominated by the entry day.

The other three measures are weak. `px_vs_vwap_pct` spread is -0.05%,
`uptick_vol_share` -0.11%, `ret_after_peak_vol_pct` +0.09% — none monotone,
none separable from noise.

**Interpretation:** the distinction is real but it is carried almost entirely by
the crude progress-per-volume ratio, not by the microstructure-flavoured
measures. Since `move_per_vol` correlates -0.58 with total volume, most of what
it adds over H009 is unclear and the two should not be counted as separate
evidence.

**Caveat:** `heavy_vol_no_progress` surviving into the forward segment is the
single most interesting thing in this phase, and it is one cell out of a family
of ~500. It needs the holdout before it means anything.

---

## H012 — Orderly directional movement beats chaotic two-way movement

Status: **REJECTED** (as a standalone signal)

Date proposed: 2026-08-19
Date last tested: 2026-08-19

**Hypothesis:** Path efficiency — net move divided by total absolute movement —
separates an orderly opening from a churning one at the same net return, and
the orderly one is the tradeable state.

**Result:** `path_efficiency` quintile spread in +5d excess is **-0.11%** at
t=300s (-0.23% at t=60s) — the wrong sign and economically negligible. The
`chaotic` archetype returns +0.05% (t=0.58) and `orderly_breakout` +0.07%
(t=0.85); neither is distinguishable from the pool or from each other.

`churn_vs_atr` — total distance travelled scaled by the stock's own ATR — does
show a -0.37% spread, but it correlates 0.56 with total opening volume and 0.54
with trade frequency, so it is best read as another member of the H009 activity
family rather than as a statement about orderliness.

**Interpretation:** the shape of the path, holding activity constant, does not
predict. What predicts (weakly) is *how much* activity there was, not how tidy
it looked. This is worth telling the uncle: the visual quality of the opening
tape appears not to be the operative variable.

---

## H013 — Opening behaviour is a set of recurring archetypes, not a continuum

Status: **SUPPORTED** as a representation (exploratory); the outcomes it
separates are the same ones H009/H011 find

Date proposed: 2026-08-19
Date last tested: 2026-08-19

**Hypothesis:** Mornings fall into a small number of interpretable behavioural
archetypes (persistent demand, fading spike, orderly breakout, rejected
breakout, heavy volume no progress, absorbed and recovered, chaotic, inert),
these can be assigned causally at each `t` from broad cross-sectional bands,
and forward outcomes differ across them. Tested in parallel with the continuous
representation (H009–H012), not instead of it.

**Test:** `src/archetypes.py`. Every band is a tercile of a within-session
cross-sectional rank, so there is no tunable threshold in the scheme. Assignment
is a documented precedence ladder. t=300s, +5d excess, date-clustered.

**Result:**

| archetype | share | n | +5d excess | t | entry-day | forward |
| --- | --- | --- | --- | --- | --- | --- |
| persistent_demand | 5.3% | 3,346 | **-0.53%** | -4.38 | -0.39% | -0.15% |
| heavy_vol_no_progress | 8.6% | 5,388 | **-0.27%** | -3.26 | -0.11% | **-0.17%** |
| absorbed_recovered | 9.8% | 6,212 | -0.12% | -1.40 | -0.12% | +0.00% |
| chaotic | 5.5% | 3,460 | +0.05% | 0.58 | +0.12% | -0.06% |
| orderly_breakout | 7.2% | 4,505 | +0.07% | 0.85 | -0.01% | +0.09% |
| rejected_breakout | 10.9% | 6,843 | +0.09% | 1.14 | +0.14% | -0.05% |
| unremarkable | 49.5% | 31,183 | +0.12% | 2.97 | +0.13% | -0.01% |
| fading_spike | 2.7% | 1,683 | +0.15% | 1.12 | +0.06% | +0.10% |
| inert | 0.6% | 389 | +0.20% | 0.93 | +0.30% | -0.08% |

**The ordering inverts the brief — and is the thing most likely to be an
artefact.** The two states resembling aggressive sustained demand are at the
bottom; the two a discretionary eye would reject are at the top, though neither
is significant.

**Do not carry this forward as a finding.** Per H015, the day-D contraction
filter systematically excludes persistent-demand mornings that kept running and
retains those that faded, which can produce this ordering on its own. The
decomposition is consistent with that: `persistent_demand`'s -0.53% is -0.39% on
the entry day and only **-0.15% forward (t=-1.4)**.

`heavy_vol_no_progress` is the exception worth keeping: majority-forward
(-0.17%, t=-2.31) and mechanically intuitive — heavy turnover with price unable
to move is a plausible warning sign in a way "lots of trading happened" is not.

**The archetype names overclaim** and should be retired on the re-run.
`persistent_demand` asserts buying; the data sees only activity.

**Band sensitivity:** re-labelled at hi/lo = 0.60/0.40, 2/3-1/3 and 0.75/0.25,
`persistent_demand` runs -0.46% / -0.53% / -0.59% and `heavy_vol_no_progress`
-0.23% / -0.27% / -0.32% — sign-stable and *strengthening* as bands tighten, so
neither is an artefact of where the bands sit. `absorbed_recovered`, `chaotic`
and `orderly_breakout` flip sign across band settings and must be read as noise.

**The controlled comparison that matters.** `persistent_demand` requires price
above the open, so it is confounded with having already run up. Matched against
`orderly_breakout`, which shares that requirement but not the volume character,
and paired by session:

| price advance by 09:20 | persistent_demand minus orderly_breakout | t | sessions |
| --- | --- | --- | --- |
| +0.5% to +1.0% | **-0.96%** | -3.46 | 328 |
| +1.0% to +2.0% | **-0.87%** | -3.44 | 348 |

At the same price advance the difference is nearly a full percent. It is the
volume character, not the advance.

**Caveats:** designed after looking at the same panel it is scored on. Sign-
stable across all three subperiods for the two negative archetypes; unstable for
`fading_spike` and `rejected_breakout`, which is why those are not claimed.

---

## H014 — Setup quality is a continuous function of time, not a fixed evaluation second

Status: **INCONCLUSIVE** — the state does evolve, but the entry time does not
change the outcome

Date proposed: 2026-08-19
Date last tested: 2026-08-19

**Hypothesis:** `setup_quality(t)` — the probability of a favourable trade given
daily context, sector/trend context and opening behaviour observed through `t` —
is better behaved than any single-`t` rule, and the *best* `t` differs by
morning. A rule that picks `t` must be causal; choosing `t` per morning after
seeing the window is lookahead and is not a result.

**Result 1 — entry time on its own does nothing.** Unconditional mean excess
return by entry time, t ∈ {30…300}s, is flat at +0.02% to +0.05% at every
horizon, with date-clustered t between 0.2 and 1.7. Entering at 30 seconds is
not detectably different from entering at 09:20. Whatever the free variable `t`
is worth, it is not worth anything unconditionally.

**Result 2 — the state genuinely evolves.** Mean probability of a morning
holding its archetype across a 30-second step is **72.8%**. 7,057 mornings are
classified `persistent_demand` at *some* `t`, but only 3,387 (48%) still are at
t=300s. So a fixed evaluation second is a real modelling choice with real
consequences, and the user's framing is correct on that point.

**Result 3 — the behavioural effects strengthen with `t`.** For the heavy-volume
× persistence cell: -0.39% at t=60s, -0.38% at t=120s, -0.51% at t=180s, -0.63%
at t=300s. More of the window observed means a better-measured state, which is
the opposite of the entry-slippage story — entering *earlier* does not rescue
these mornings (H009 spread is -0.47% at t=30s against -0.54% at t=300s).

**Interpretation:** `t` matters for *measurement* and not for *execution*. No
`setup_quality(t)` model was fitted, deliberately: with the strongest surviving
forward effect at roughly -0.2% and the entry-day contamination of H015
unresolved, a fitted model would be fitting an artefact with more parameters.

**Next step:** resolve H015 first. A scoring model built on a contaminated
selection is not worth the fitting.

---

## H015 — The screener selects a morning using that morning's own closing price

Status: **SUPPORTED** — this is a pipeline defect, not a market hypothesis

Date proposed: 2026-08-19 (found while investigating H008)
Date last tested: 2026-08-19

**The claim:**
Every indicator on a candidate row for date D is computed from date D's **own
close**, and the screener gates on those indicators. The entry is at 09:20 on
date D. So the selection of a morning uses roughly six hours of information from
after the entry.

**Evidence:**
Recomputed on RELIANCE from `daily_bars_adj`: `px_vs_ema_mid`, `ret_20d` and
`ema_mid_slope` on the row for date D match `close_D / ema_D - 1` and
`close_D / close_{D-20} - 1` to 1e-5. `compute_indicators` is called per symbol
on a date-sorted frame with no lag, and `run_screen` filters that same frame.

**Which filters leak, at current defaults:**
- `require_above_ema_mid=True` — **every candidate morning is a session that
  closed above its own 50-day EMA.** This is the big one: it conditions
  directly on the outcome of the day being traded.
- the contraction family (`atr_ratio <= 0.70`, `bb_width_pctile <= 15`,
  `base_depth <= 7`, `contraction_mode="any"`) — all include day D's own range,
  so the entry day is required to have been a quiet day.
- `median_tv_20_cr >= 0.5` and the `min_price` bound — both include day D.
- `deliv_pct`, used as a context feature above, is day D's whole-session
  delivery percentage and is equally unavailable at 09:20.

**What it contaminates:** H001, H002, H003, H005, H006 and everything in H008–
H014 are all computed on this pool. Nothing is retracted — the measurements are
correct for the pool as constructed — but "the pool as constructed" is not a
pool anyone could have traded.

**How large is it?** Measured by splitting the +5d excess return at the entry
day's close:

| | total +5d excess | 09:20 → day-D close | day-D close → D+5 |
| --- | --- | --- | --- |
| volume q5 − q1 | -0.54% | **-0.35%** | -0.19% |
| `persistent_demand` | -0.53% | **-0.39%** (t=-8.2) | -0.15% (t=-1.4) |
| `heavy_vol_no_progress` | -0.27% | -0.11% (t=-3.2) | **-0.17%** (t=-2.3) |

Roughly two thirds of the headline behavioural effect sits in the entry-day
segment, which is the segment the screen conditions on.

**The contraction filters do not merely inflate the result — they can invert
it** (user, 2026-08-19; this supersedes the weighing in the paragraph that
followed here originally).

The screen requires date D itself to have been a quiet, contracted day. For a
morning with genuine persistent buying:

- if it keeps running all day, date D's range is wide, contraction fails, and
  the morning is **excluded from the pool**;
- if the opening demand fades back into a narrow range, contraction passes and
  the morning is **kept**.

The pool therefore retains the persistent-demand mornings that died and discards
the ones that worked. That is sufficient on its own to manufacture "sustained
opening demand predicts poor returns" from a strategy in which sustained demand
is good — which is exactly the H009/H013 result. This is now the **leading**
explanation for that inversion.

**What I originally argued here, and why it was too weak.** The first version of
this entry noted that the entry-day effect is flat in how tightly
`above_ema_mid` binds (-0.28% where the day-D close is within 0.5% of the 50-EMA
against -0.43% where it is more than 10% above), and concluded that a genuine
intraday fade was "at least as plausible as pure selection". That test
exonerates **one** filter and says nothing about the contraction family, which
is the one carrying the inverting mechanism. It was flagged as a live confound
and then not weighted accordingly. The intraday-fade reading is the secondary
explanation, not a co-equal one.

**What cannot be tested with data on hand:** a properly-lagged screen (indicators
through D-1, trade D) would select a *different* set of mornings, and 1-second
ticks exist only for the mornings the contaminated screen selected. The clean
experiment needs a new pull against a re-run screen.

**Next step:** decide whether to re-screen on lagged indicators and re-pull.
Until then, prefer the day-D-close-to-D+5 segment for any forward claim, and
treat the entry-day segment as descriptive.

---

## H016 — Phase 2's t-statistics were computed as though mornings were independent

Status: **SUPPORTED** — measurement defect, corrections below

Date proposed: 2026-08-19
Date last tested: 2026-08-19

**The claim:**
63,698 mornings are not 63,698 independent observations. They are ~650 sessions,
and within a session the whole cross-section moves with the market. Every
t-statistic reported in Phase 2.4 treats rows as independent and is therefore
overstated by roughly the square root of the average cluster size.

**Evidence:** the same unconditional excess returns, computed both ways:

| horizon | mean excess | naive t (as reported in H001) | date-clustered t |
| --- | --- | --- | --- |
| +1d | +0.05% | 4.05 | **1.41** |
| +3d | +0.04% | 2.16 | **0.99** |
| +5d | +0.02% | 0.84 | **0.45** |
| +10d | +0.04% | 1.35 | **0.83** |

The inflation factor is about 2.9x.

**What changes:** H001's "+1d excess, t=4.2" was the one number in Phase 2.4
that looked statistically solid. Clustered, it is t≈1.4 and not distinguishable
from zero. **This strengthens H001's rejection rather than weakening it** — the
pool is even more clearly a coin flip than reported. H002's cell t-statistics of
-3.3 to -7.0 become roughly -1.1 to -2.4, so the direction survives but the
confidence does not.

**Correction applied:** `explore.cluster_stats` reports both, always, so the size
of the difference stays visible. Nothing in `labelling.py` has been changed;
`labelling.horizon_summary` still emits the naive statistic and should be read
with this entry in hand.

**A second correction, to this session's own work.** The first version of
`explore.permutation_max` built its null by shuffling *date-level means* between
dates while leaving each row's within-date deviation attached to it. That
preserves the entire cross-sectional relationship being tested, so the null
contained the signal and could never reject anything. It produced "observed max
|t| 7.30 against a null p95 of 7.32", i.e. an apparent total failure to beat
chance. **That figure was meaningless and is retracted.** With a correct
within-date shuffle the same family gives null p95 = 3.43 against the same
observed 7.30, and on the forward-only outcome null p95 = 3.91 against observed
4.99 — real structure, marginal in the forward case.
`test_permutation_null_destroys_a_planted_cross_sectional_effect` is the
regression test.

---

## H017 — The fixed-horizon label and the traded payoff disagree about the same trades

Status: **SUPPORTED** — they disagree, and the traded payoff is the *worse* of
the two. Resolves H006.

Date proposed: 2026-08-19 (user, reviewing Phase 2.5)

**Hypothesis:**
Every negative result so far (H001, H002, H009, H013) measures *"if I buy here,
what is the excess return at D+5"*. The strategy's payoff is

    enter → stop losers quickly → a minority run +15-20% → sell half → trail

These are different functions of the same price path, and they can disagree in
sign on the same set of trades. Concretely: if 70% of setups end -3% by D+5 but
the stop exits them at -1%, and 10% reach +18%, fill the target, and are only
+2% by the D+5 close, the fixed-horizon label calls the strategy bad while the
traded rule is profitable. **If that disagreement is large, none of the existing
negative results is a verdict on the strategy as traded.**

**Origin:** the user's third objection to the Phase 2.5 write-up. Not
data-generated — it is a statement about the measurement, and it is testable
without any new data.

**Test:** `src/payoff.py`. Simulate the stated rule on daily bars from the
tick-derived entry and stop, and compare the resulting expectancy against the
D+5 excess return on the identical trades.

**Why this can only produce a bracket, not an answer.** A daily bar does not say
whether the high or the low came first. On the sessions where both the stop and
the target were touched, the outcome is genuinely undetermined by the data, so
the simulator is run twice — once resolving every ambiguity in the trade's
favour and once against — and the truth is somewhere between. H006 measured this
at 6.49% of mornings touching both within ten sessions. **If the bracket is
narrow the question is answered without the intraday pull; if it is wide, the
width is precisely what the pull would buy.**

**One ambiguity that is NOT ambiguous, and is resolved here for the first time.**
The entry day looks unusable — its daily high and low include the 09:15-09:20
window, before the position exists, which is the H004 pairing error. But the
1-second panel gives `running_low_t` and `running_high_t`, and that closes it
exactly:

- `low_D <= low_t` always, since the window is part of the day. If `low_D <
  low_t` the day's low came *after* entry and the post-entry low is `low_D`,
  certain. If `low_D == low_t` the low happened inside the window, so price
  never traded below `low_t` after entry — and since `stop < low_t` by
  construction, **the stop certainly was not hit on the entry day**.
- Symmetrically for the high and the target.

So the entry-day afternoon is fully usable for touch detection, rather than
being either discarded (understating stops badly) or included raw (the H004
error). This is a strict improvement over `labelling.py`'s `*_incl_d0` twins.

**Caveats fixed in advance:**
- Runs on the contaminated pool (H015), because tick-derived entries exist only
  for the mornings the old screen picked. The *methodological* result — whether
  the two labels disagree — does not depend on which pool it is measured on.
  The magnitudes do, and must be re-run when the re-pull lands.
- Gap-through must be modelled or the stop is fictitious: a session opening
  below the stop fills at the open, not at the stop.

**Result (2026-08-19) — the disagreement is real, and it runs the wrong way.**

Same 63,698 trades, both labels, date-clustered:

| label | mean excess | median | hit | t |
| --- | --- | --- | --- | --- |
| fixed horizon (+5d) | +0.021% | -0.67% | 43.3% | 0.52 |
| traded payoff, pessimistic | **-0.130%** | -2.01% | 25.0% | -2.80 |
| traded payoff, optimistic | **-0.128%** | -2.01% | 25.0% | -2.75 |

Exits: 78.7% stopped, 4.5% gapped through the stop, 14.2% filled the target,
median hold 4 sessions.

**The traded rule does worse than the fixed-horizon label, not better.** The
hypothesised rescue — losers cut at -1% instead of -3%, a minority running to
+18% — does not happen here. The stop removes trades that would have recovered
faster than it removes trades that would have kept falling.

Swept across stop widths, there is no setting where it turns positive:

| stop below running low | raw payoff | raw +5d | payoff **excess** | t |
| --- | --- | --- | --- | --- |
| 0.5% | -0.045% | +0.205% | -0.133% | -4.86 |
| 1.0% | +0.023% | +0.205% | -0.115% | -3.21 |
| 2.0% | +0.065% | +0.205% | -0.130% | -2.80 |
| 3.0% | +0.117% | +0.205% | -0.154% | -2.81 |
| 5.0% | +0.140% | +0.205% | -0.259% | -3.82 |
| 8.0% | +0.243% | +0.205% | -0.475% | -5.42 |

**Note the trap in that table.** The raw payoff improves steadily as the stop
widens and eventually beats the raw five-day return. The excess gets *worse* the
whole way. Widening the stop lengthens the holding period, and in a rising
market a longer hold collects more market return — the apparent improvement is
bought beta, not edge. Anything judged on raw returns here would reach the
opposite conclusion.

Restricting to the mornings where a real setup exists — price advanced 0.5%+
above the open by 09:20, H005's condition — makes it worse, not better: -0.284%
at a 1% buffer, -0.263% at 2%, -0.208% at 4% (n=15,389).

**What this settles:** the "we are measuring the wrong thing" defence for
H001/H002 does not hold. The negative results are not an artefact of the
fixed-horizon label. They survive being re-measured under the strategy's own
payoff function, and get slightly worse.

**What it does not settle:** it runs on the contaminated pool (H015) and must be
re-run when the corrected re-pull lands. And it tests the stated exits at the
stated entry; it says nothing about a better entry.

**Effect on the archetype ordering (H013):** largely preserved, which is
evidence the ordering is not a label artefact. `persistent_demand` stays worst
(-0.571%, t=-5.0 under the payoff label against -0.534%, t=-4.4 fixed-horizon);
`heavy_vol_no_progress` unchanged at -0.265%. `orderly_breakout` flips from
+0.071% to -0.236%, and `unremarkable` from +0.124% to -0.044%.

---

## H018 — Path-aware outcome states separate trades that a return label conflates

Status: **SUPPORTED**, and it changed one of its own definitions.

Date proposed: 2026-08-20 (user, opening the reverse-discovery phase)

**Hypothesis:**
"Winner" and "loser" are too coarse. A morning that reached +18% and gave it
back, one that was stopped and *then* ran, and one that never moved are three
different objects with three different implications, and a fixed-horizon return
scores all of them alike. Sorting outcomes by **path** — MFE, MAE, whether the
stop came before or after the favourable move, and how many sessions the move
took — should produce states that differ in what they are worth.

**Kind of work:** hypothesis generation plus exploratory testing, on the
exploration window only (2023-08-21 → 2026-08-18, 66,597 classifiable mornings
at t=180s, 661 sessions).

**Test:** `src/discovery.py`, `python -m src.cli discover`. Nine states on a
precedence ladder. Every bar is `max(k x R, absolute floor)` so a hair-trigger
stop cannot manufacture a large R-multiple out of a small move.

**One correction had to be made before the risk numbers meant anything.** The
stop implied by "slightly below the running low" at t=180s has a **median
distance of 0.41%** against a **median ATR of 3.37%** — one eighth of a normal
day's range. That is not a risk level, it is the spread with a name, and every
outcome defined against it would really be measuring whether the stock wiggled
in the next twenty minutes. Risk is floored at `0.5 x atr_pct`, which lifts
median R to 1.70% and lands near the 2.41% the Phase 2.4b entry-window work
measured for setups that had actually advanced. Widening a stop cannot break
`stop < running_low <= entry`; nothing here narrows one.

**Result — the states are real and they are priced very differently.** Each was
run through `payoff.simulate` under the stated exit rule (stop, half out at
+15%, trail the rest):

| state | n | share | payoff excess | target filled | winner? |
| --- | --- | --- | --- | --- | --- |
| `monster` | 3,750 | 5.6% | **+13.31%** | 100% | yes |
| `slow_winner` | 5,583 | 8.4% | **+2.86%** | 36.7% | yes |
| `clean_winner` | 1,410 | 2.1% | **+1.29%** | 21.2% | yes |
| `failed_breakout` | 13,857 | 20.8% | -1.36% | 0% | no |
| `shaken_out` | 18,464 | 27.7% | -1.65% | 0% | no |
| `immediate_failure` | 18,899 | 28.4% | -1.63% | 0% | no |
| `stopped_out` | 3,712 | 5.6% | -1.60% | 0% | no |
| `spike_and_fade` | 370 | 0.6% | -1.34% | 5.4% | no |
| `nothingburger` | 552 | 0.8% | -0.31% | 13.9% | no |

**The taxonomy corrected itself, which is the part worth keeping.** The first
version defined `clean_winner` as a large MFE reached quickly, with no
requirement that the move hold. Priced under the exit rule that state earned
**+0.05% excess** on 2,978 trades with a 10.2% target-fill rate — a failure
wearing a winner's shape. It was split into `spike_and_fade` (moved, gave it
all back) and a `clean_winner` that must still be positive at the horizon. The
lesson generalises: **name an outcome state, then price it, before using it as
a label.** A path taxonomy is as capable of being wrong as a return label.

**A large state nobody had named: `shaken_out`, 27.7% of all mornings.** Stopped
out, and *then* the stock made a move of 3%+ — median MFE +7.53%, median +2.80%
at D+10. More than one morning in four. That is a statement about the stop
rather than about the setup, and it is the largest single block in the pool.
Recorded here; not pursued in this phase.

**Where the winners are not:** `monster` takes a median **8 sessions** to reach
its peak and `slow_winner` 7. The fast-MFE states are the ones that do not pay.
Nothing in this pool rewards an immediate move.

---

## H019 — Winners and superficially identical failures differ in observable setup

Status: **REJECTED at any useful effect size.** The distinctions are real and
tiny.

Date proposed: 2026-08-20 (user, reverse-discovery brief)

**Hypothesis:**
Take the strong winners from H018 and match each against failures that looked
like it at the decision point — same session, same sector, same size class,
same liquidity, same volatility, and in the tight tier the same prior run-up,
base width, gap and opening volume. Whatever separates them is the thing the
strategy is actually selecting on.

**Kind of work:** exploratory. Generated and tested on the same window.

**Test:** `discovery.match` / `discovery.contrasts`. Nearest-neighbour matching
on within-session percentile ranks, exact on sector and size tier, calipered on
the mean and on every single dimension, controls drawn without replacement and
balanced above and below the winner. 68 features across six families. Inference
clustered by session. The bar is not 1.96 but the **95th percentile of the
maximum |t| under a within-set label permutation** — the null that keeps every
stratum intact and destroys only the link between winning and the features.

**Result — with the market held exactly fixed, almost nothing survives.**

Core tier, 2,446 matched sets, permutation bar |t| = 3.36:

| feature | family | std. diff | t |
| --- | --- | --- | --- |
| `px_vs_ema_fast` | stock trend | -0.107 | **-4.27** |
| `px_vs_ema_mid` | stock trend | -0.107 | **-4.10** |
| `deliv_pct` | price/volume | +0.081 | 3.16 |
| `high_vs_open_pct` | gap/open | -0.068 | -3.11 |
| `ret_60d` | stock trend | -0.067 | -3.00 |
| `open_base_pos_20` | breakout location | -0.074 | -2.89 |

Two features clear the bar, both saying the same thing: **the winners were
sitting slightly further below their own short-term moving averages.** The
effect is a tenth of a within-day standard deviation. In decision units that is
a win rate of 17.15% in the lowest quintile against 14.65% in the highest, on a
16.13% base — a lift of 1.06 to 0.91.

Tight tier (608 sets, bar 3.43): only `bb_width_pctile` clears, at t=3.52, and
it does not clear in the core tier. Nothing replicates across both.

**Stable in every direction that was checked, and still small.** Both survivors
keep their sign across calendar thirds, sectors, market regimes, and all nine
sensitivity variants (risk floor 0.25/0.5/0.75 x ATR, looser and tighter winner
bars, `fast_sessions` 2 or 3, one control instead of three, caliper halved),
and at t=60s and t=300s as well as t=180s.

**The direction is the opposite of the breakout premise.** Every surviving or
near-surviving contrast points the same way: winners were *further below* their
moving averages, *lower* in their base, *further below* their 20- and 50-day
highs, with *weaker* 60-day returns and relative strength. Whatever this pool
rewards, it is not proximity to a breakout level. See H021 for the direct test
that this is not merely "more room to travel".

**What this rejects:** not the existence of a distinction — two features clear a
properly corrected bar and are stable — but the idea that it is large enough to
build on. A 1.06x lift on a 16% base rate does not survive costs, and it does
not resemble a discretionary trader picking one name out of fifty.

---

## H020 — Matching controls across nearby sessions inflates every contrast

Status: **SUPPORTED**, and it invalidates the first reading of H019.

Date proposed: 2026-08-20 (found while tuning the matcher, not hypothesised)

**Origin:** the same-session cell in this pool is thin — a median of **82
candidates per session** across 20 sectors, so exact sector-plus-size matching
inside one day leaves a median of 3 rows and matches only 2,446 of 10,743
winners. Widening the band to +/-2 sessions lifted that to 4,105 with better
covariate balance, which looked like a clean improvement.

**It also tripled every headline contrast**, and that was the artefact rather
than the improvement:

| matching band | matched sets | `open_base_pos_20` std. diff | t |
| --- | --- | --- | --- |
| same session | 2,446 | -0.074 | -2.89 |
| +/-1 session | 3,811 | -0.302 | **-15.13** |
| +/-2 sessions | 4,105 | -0.332 | **-16.04** |
| +/-5 sessions | 4,430 | -0.317 | -13.03 |

**A real effect does not quadruple when one day of slack is added to a matching
rule.** The discontinuity between 0 and 1 is the tell.

**Mechanism, measured rather than argued.** Winners cluster on local market
troughs: the win rate is 20.2% in the top third of trailing market volatility
against 11.7% in the bottom third (H022). So a control taken from a neighbouring
session sits systematically further up the market's own swing. Directly: under a
+/-2 band the winner's own session sits **0.45% lower in the equal-weighted
market index** than its controls' sessions, on **71.2%** of matched sets. Under
same-session matching that offset is exactly 0.0000% by construction.

Every "the winner opened lower in its base, further below its moving average"
contrast was therefore partly restating "the winner's morning was 0.45% lower in
the market".

**Consequence:** `MatchConfig.date_window` defaults to 0. `discovery.market_offset`
computes and prints the offset on every run, so the day somebody widens the band
for a perfectly good reason, the inflated contrasts that follow are labelled
rather than believed.

**Generalisation worth carrying:** this is the third time in this project that a
seemingly innocuous convenience moved a result by more than the result itself —
after the screener lookahead (H015) and the naive t-statistics (H016). The
pattern in all three is the same: a step taken to get more usable rows quietly
imported information the comparison was supposed to exclude.

---

## H021 — The winner tilt is only "more room to travel"

Status: **REJECTED.** The tilt survives holding extension fixed.

Date proposed: 2026-08-20 (self-raised against H019)

**Hypothesis:** winners in H019 sit further below their moving averages, and a
stock further below its average has more distance to cover before it runs into
anything — so it clears an MFE bar more easily. If that is the whole mechanism,
the effect should vanish inside a narrow band of the extension variable.

**Test:** win rate by (quartile of `px_vs_ema_mid`, quartile of
`open_base_pos_20`), both ranked within session. Base rate 16.13%.

| `px_vs_ema_mid` band | base pos Q1 | Q2 | Q3 | Q4 |
| --- | --- | --- | --- | --- |
| 1 (least extended) | 17.59 | 16.32 | 17.20 | 14.60 |
| 2 | 16.69 | 16.80 | 15.80 | 15.51 |
| 3 | 17.10 | 16.28 | 16.22 | 14.98 |
| 4 (most extended) | 16.62 | 16.56 | 15.73 | 14.29 |

The decline across base position holds inside **every** extension band, at
roughly the same slope (about -2.5pp from Q1 to Q4). The two are not the same
variable. Volatility is separately controlled: `atr_pct` is a matching covariate
and balances to a standardised difference of 0.03.

**What this does not rescue:** the effect is still ~2.5 percentage points on a
16% base. Establishing that it is not an artefact does not make it large.

---

## H022 — Breakout-like setups work only in trending markets

Status: **REJECTED — the sign is backwards.** They work better in chop.

Date proposed: 2026-08-20 (user, reverse-discovery brief, point 5)

**Test:** win rate by market state, all regime variables computed from data
through D-1 (`src/context.py`, tested for lookahead in `tests/test_context.py`).
66,597 mornings, 661 sessions, clustered by session.

| market state (as of D-1) | n | sessions | win rate | vs pool |
| --- | --- | --- | --- | --- |
| trending up | 29,360 | 168 | 14.27% | 0.88 |
| trending down | 556 | 36 | 12.77% | 0.79 |
| chop / sideways | 36,681 | 447 | **17.67%** | 1.10 |

On the continuous trend measure — net move over total distance travelled, so a
monotone advance scores near 1 and a round trip near 0 — the ordering is
monotone and the wrong way round:

| `mkt_trend_eff` tercile | win rate | vs pool |
| --- | --- | --- |
| low (choppy) | **17.97%** | 1.11 |
| mid | 15.37% | 0.95 |
| high (trending) | 15.05% | 0.93 |

**The largest single effect found anywhere in this phase is market volatility,
not any stock-level feature:**

| trailing market volatility (D-1) | n | win rate | vs pool |
| --- | --- | --- | --- |
| low | 22,314 | **11.71%** | 0.73 |
| mid | 22,119 | 16.49% | 1.02 |
| high | 22,164 | **20.23%** | 1.25 |

A 1.7x spread, against 1.06x for the best stock-level feature. Identical at
t=60s and t=300s.

**The obvious mechanical caveat, stated plainly.** Winners are defined by
excursion bars, and in a high-volatility market everything moves more, so more
mornings clear any fixed bar. `R` is floored on each *stock's* own ATR but
market-wide volatility is not controlled. This is therefore not established as
an edge; it is established as a fact about when the outcome states occur, and
any rule conditioned on it must be measured against a benchmark that moves with
the regime.

**Interaction:** the base-position tilt from H019 has the same slope in both
regimes — trending up 15.18% → 13.06% across terciles, chop 18.76% → 16.59%. The
regime shifts the level, not the relationship. So there is no "this setup only
works in a trending market" structure here; there is a market state that raises
all the win rates at once.

---

## H023 — Winners come in several recognisable kinds rather than one

Status: **REJECTED.** Clustering adds nothing over a single feature.

Date proposed: 2026-08-20 (user, reverse-discovery brief, point 4)

**Hypothesis:** a single averaged contrast may describe none of the actual
winner types. If winning breakouts come in two or three kinds — a tight base
clearing an old high on a small gap, a high-relative-strength name gapping from
a shallow pullback — clustering the winners should find them, and mornings
resembling a cluster should win more often.

**Test:** k-means (k=4) on the strong winners' within-session percentile ranks
over 16 decision-time features. Then the honest form of the claim: assign
**every** morning to its nearest winner centroid, keep those inside the tightest
r% of distances, and measure the win rate there against the 16.13% base.

| radius | best cluster lift | others |
| --- | --- | --- |
| 2% | 1.22 (n=351) | 1.09, 0.95, 0.90 |
| 5% | 1.14 (n=838) | 1.09, 0.97, 0.91 |
| 10% | 1.07 (n=1,675) | 1.06, 0.98, 0.92 |

**Lift decays as the neighbourhood grows** — 1.22 → 1.14 → 1.07 — which is the
signature of fitting a small sample rather than finding a region. And even the
tightest neighbourhood, measured *in sample against centroids built from the
winners themselves*, reaches only 1.22x. The multivariate combination does not
beat the best single feature (1.06x) by enough to matter.

**Reading:** if there were a distinct winning setup archetype in this pool with
a materially higher hit rate, this procedure was constructed to find it and it
did not. That is informative about the pool, not about whether such a setup
exists somewhere — and see the standing caveat in `PLAN.md` §7 that this pool is
~98% material a discretionary trader would reject.

---

## H024 — Ranking inside the screen, not filtering across it, is where the edge is

Status: **SUPPORTED in sample, REJECTED out of sample (2026-08-20).** On the
2020-2023 holdout the same rule returns **-0.627% vs the market (t=-1.98)**, a
sign reversal, and fails every clause of the frozen bar. See H033. Everything
below stands as written — it is an accurate record of what the exploration
window said — and none of it survived the only test that counted.

Date proposed: 2026-08-20 (user: "give this strat one more go … shotgun
approach … don't worry about overfitting")

**Hypothesis:** every test so far asked *"do the mornings passing this filter
beat the market on average"*. That is not the strategy. A discretionary trader
looks at a morning's candidates and trades **one**. A pool with zero average
edge can still contain a usable *ranking*, and the two questions have different
answers. Also test both directions and a much wider exit space, since H018 found
27.7% of mornings are stopped out before a move that then happens.

**Kind of work:** exploratory, deliberately overfitting, by explicit
instruction. Exploration window only (2023-08-21 → 2026-08-18, 68,333 mornings,
660 sessions). The 2020-2023 holdout was not touched.

**Method:** `src/shotgun.py` — a vectorised exit simulator so a sweep is
seconds rather than hours. Validated against `payoff.simulate` at correlation
**0.981**, identical exit mix and identical median hold; it runs ~0.04pp
optimistic because it does not model the breakeven-stop or still-open states.

### What did not work, first

- **Exits alone.** 720 exit configurations across both directions on the whole
  pool. The best *long* excess is **-0.155%**; longs make money raw (+0.69% over
  20 sessions) and lose to the market. No exit rescues the unconditional pool.
- **Shorts.** Every config positive on both raw and excess is a short, best
  +0.29% excess at +0.13% raw. Untradeable in Indian mid-caps (no borrow, costs
  above the edge) and the raw number is inside the noise. Recorded, not pursued.

### What worked

Two daily, as-of features, ranked **within each session** and averaged:

- `dist_52w_high` — proximity to the 52-week high. Top decile is within ~3.7%.
- `deliv_pct` — delivery percentage, the one feature that also survived the
  H019 matched contrast (t=3.16 there).

Take the top N per session, enter at the open, **no stop**, hold 30 sessions.

**Per trade** (top 5/day, n=3,209): **+1.40% vs the equal-weighted market**
(t=5.69), **+1.32% vs the same-day pool average** (t=6.38), raw +3.19%.

**Portfolio, daily mark-to-market, 0.40% round-trip cost:**

| book | CAGR | max DD | Sharpe |
| --- | --- | --- | --- |
| all candidates, no selection | 7.96% | -24.6% | 0.54 |
| top 3 / day | 22.71% | -13.5% | 1.70 |
| **top 5 / day** | **26.83%** | **-12.2%** | **1.93** |
| top 10 / day | 25.20% | -14.3% | 1.76 |
| top 20 / day | 20.91% | -16.4% | 1.41 |
| top 50 / day | 17.03% | -20.4% | 1.11 |
| equal-weighted market | 18.33% | -24.3% | 1.02 |

**The decay in N is monotone and smooth**, which is what a real ranking looks
like: the edge concentrates at the top and dilutes into the market by top-50. A
fitted crevice does not degrade gracefully.

### Three checks that matter more than the headline

**1. It is selection, not beta.** Benchmarked against the *same-day mean of
every other screened candidate under the identical exit rule* — which removes
the pool's own beta, size and style exactly — all 60 tested cells stay positive,
best +1.25% at t=8.28.

**2. It beats its own permutation null.** Shuffling the score **within each
session**, holding the pool, dates, exit rule and pick count fixed, 400 times:
null p95 = +0.295%, null max = +0.654%, observed **+0.774%**. The observed value
beats **100%** of shuffles; observed |t| 4.57 against a null max of 3.58.

**3. The contraction screen is doing real work.** Running the identical ranking
over the full tradeable universe instead of inside the screen:

| where the ranking is applied | CAGR | Sharpe |
| --- | --- | --- |
| inside the contraction screen | 25.86% | 1.64 |
| full tradeable universe | 8.75% | 0.65 |
| only what the screen rejected | 9.40% | 0.69 |

Neither component works alone — the screened pool by itself returns 7.96%
against a 16-18% market, and the ranking on the open universe returns 8.75%.
**Together they return 25.9%.** That is an interaction, not a sum, and it is
close to the uncle's stated setup: volatility contraction, near the highs,
strong delivery.

### The finding that costs the most to accept

**The 1-second tick data contributes nothing.** Entering at the 09:15 opening
print instead of at the tick price at t=180s gives CAGR 26.39% against 26.83%,
and per-trade excess +1.37% against +1.40%. `score2` is built entirely from
daily as-of features. The whole opening-window pipeline — 180,000 API calls,
the daily-token blocker, four phases of behavioural features — is irrelevant to
the only thing that has worked.

That is a real result and it should not be softened. It also means this rule can
be tested on the full daily history and the full universe, and its holdout test
does not depend on tick coverage at all.

### What this is not

- **Not out of sample.** Everything above was searched on the window it is
  measured on, across roughly 1,500 configurations. The permutation null covers
  the *ranking* given the feature set; it does not cover the search that chose
  the features.
- **Not the uncle's strategy.** No stop (H018's `shaken_out` says the stop is
  what breaks it), a 30-session hold rather than a +15% target, and ~142
  concurrent positions rather than one name a day. The top-3 variant (87 open,
  22.71% CAGR) is closer but still a portfolio.
- **Not tested through the careful simulator at portfolio level**, only per
  trade.
- **One market.** 2023-2026 is a single bull regime. The strategy's best years
  relative to the market are 2025 (-1.1% against -8.3%) and 2026 (+20.2%
  against +5.9%), which is encouraging in the sense that matters — it held up
  when the market did not — but it is four years, one of them partial.

**Frozen for the holdout** in `data/metadata/shotgun_frozen.json`.

---

## H025 — Inside the screen, the most pulled-back candidate outperforms

Status: **REJECTED in sample**, and again out of sample.

Date proposed: 2026-08-20 (Phase 3, axis B)

**Hypothesis:** H019/H021 found that winners sat further *below* their
short-term moving averages than matched failures, and H022 rejected the
trending-market premise with the sign backwards. If that reading of the pool is
right, ranking each morning's candidates by weakness — furthest below the fast
and mid EMAs, worst 20- and 60-day return, furthest below the 20- and 50-session
high — and taking the top five should beat the pool.

**Kind of work:** exploratory. 15 feature pairs x 3 pick counts = 45
configurations, exploration window only, entry at date D's opening print, 30
sessions, no stop.

**Result: nothing in the axis cleared a clustered t of 2 with positive alpha.**
The best config by portfolio Sharpe (`px_vs_ema_fast` + `ret_20d`, top 5) is
+0.259% vs the market at t=0.92, CAGR 17.39% against the market's 18.24%.

**What this settles.** A matched-pair contrast of 0.107 standardised units
(H019) does not become a selection rule. The paired design detected a shift far
below anything tradeable, exactly as its own write-up warned, and this is the
direct test of that warning. Replayed on the holdout as information only:
-0.541% (t=-1.60).

---

## H026 — Relative strength against the market and the sector is a better ranking than price location

Status: **SUPPORTED in sample. The alpha replicates out of sample; the portfolio
does not clear the frozen bar.** See H033.

Date proposed: 2026-08-20 (Phase 3, axis C)

**Hypothesis:** H024 ranks on where a stock sits against its *own* past
(`dist_52w_high`). Where it sits against everything else is a different fact and
the one the breakout literature is actually about. Rank instead on relative
strength versus the market and the sector, plus the health of the sector itself.

**Kind of work:** exploratory to select (45 configurations), then confirmatory on
the 2020-2023 holdout as a frozen family member.

**Definition (frozen):** within each session, mean of the percentile ranks of
`rs_60d_vs_mkt` and `sector_breadth`, both ascending; take the top 5; enter at
date D's adjusted opening print; hold 30 sessions; no stop; 0.40% round trip.

| | exploration 2023-08 → 2026-08 | holdout 2020-12 → 2023-07 |
| --- | --- | --- |
| n | 3,226 | 2,761 |
| vs market | **+1.230%** (t=4.76) | **+1.366%** (t=3.31) |
| vs same-day pool | +1.166% (t=5.16) | **+1.730%** (t=4.98) |
| portfolio CAGR | 24.91% | 41.50% |
| market CAGR | 18.25% | 41.78% |
| portfolio Sharpe | 1.27 | 1.74 |
| market Sharpe | 1.02 | 2.25 |
| max DD | -17.7% | -28.3% |

**The selection claim replicated and the portfolio claim did not, and the two
are different claims.** Out of sample the rule beat the same-day pool by
**+1.73% a trade at t=4.98** — a larger effect than in the window it was found
in (retention 1.11x). It also matched the market's return while running a
drawdown half again as deep, so its Sharpe sits below buy-and-hold and it fails
clause 2 of the frozen criterion. Per H033 that is a fail, and the rule is not
promoted.

**Stress (exploration, 6 purged blocks with a 30-session purge):** positive in 5
of 6; leave-one-block-out positive in all 6; positive in both halves of the
market's own trend; beats 200/200 within-session shuffles of its own score.

---

## H027 — The screen's own contraction measures are a ranking, not just a gate

Status: **SUPPORTED in sample, killed by the stress test, negative out of sample.**

Date proposed: 2026-08-20 (Phase 3, axis D)

**Hypothesis:** H024 showed the volatility-contraction screen and a ranking
interact. If the screen is doing real work, its own quantities — base depth,
Bollinger width, ATR ratio, small bodies, base range — should rank inside it.

**Result, exploration:** `base_depth_pctile` + `base_range_20_pct`, top 5:
+0.715% vs market (t=3.28), CAGR 19.97% against 18.25%, Sharpe 1.51.

**Killed before freezing.** Leave-one-block-out turns negative when block 5
(2026-02 → 2026-07, alpha +4.75%) is removed: one four-month period carries the
whole result. Frozen as information-only rather than as a family member.

**Holdout: -0.645% (t=-2.19).** The stress test was right about this one.

---

## H028 — The screen is fine and it is being held at the wrong times

Status: **REJECTED as a strategy. The conditional alpha is real and does not
survive the comparison against buy-and-hold.**

Date proposed: 2026-08-20 (Phase 3, axis E)

**Hypothesis:** hold the *whole* screened pool, but only in a stated market
state. No cross-sectional selection at all — the claim is about timing. Nine
gates, all on round numbers rather than sample quantiles (a tercile of the
window being traded is a lookahead and silently redefines itself between
windows).

**Result:** one gate of nine cleared the search bar. Holding the pool only when
the equal-weighted market is below its own 50-EMA: +1.107% vs market (t=3.79) in
sample, **+2.438% (t=3.69) out of sample**. The conditional alpha is real in
both windows and points the same way as H020's mechanism — candidates bought
into market weakness do better.

**And it is not a strategy.** Deployed 30-40% of the time, the book compounds at
10.18% against buy-and-hold's 15.11% over the same span in sample and 26.78%
against 41.78% out of sample. Being out of the market costs more than the
conditional edge pays.

**Measurement note that changed the answer.** Under the earlier convention —
annualising over the sessions a book *holds* something — this rule reported
14.11% against the market's 18.24% and looked merely weak. Counting cash days at
zero over the calendar span, which is what a timing rule must be charged, drops
it to 10.18%. `family.span_stats` does this for every rule; for an
always-invested rule the two conventions agree exactly.

---

## H029 — The exit is where the pool's edge is

Status: **REJECTED**, in sample and out, on a second pool and a second entry.

Date proposed: 2026-08-20 (Phase 3, axis F)

**Hypothesis:** H018 found 27.7% of mornings are stopped out and *then* move 3%+
(median MFE +7.53%) — the largest identified block in the pool. If the selection
is fine and the stop is the problem, an exit rule applied to the whole pool
should beat the market without any selection at all.

**Method:** 72 exits — stop at none/1/2/3 x ATR, target none/+15%, trail
none/10-EMA/20-EMA, hold 10/20/30 sessions — on every screened morning.

**Result: none cleared the bar; every one has negative market-excess.** The best
by Sharpe (+15% target, 20-EMA trail from the target, 20-session stop) is
-0.421% vs market at t=-5.99. Out of sample, -0.155% (t=-1.82).

This re-tests H024's exit sweep on a different pool (screen-defined rather than
tick-joined), a different entry (the opening print) and a different window, and
gets the same answer. **The unconditional pool cannot be rescued by an exit.**
`shaken_out` remains a real description of what happens; it is not a tradeable
instruction.

---

## H030 — The screen's edge is an illiquidity premium in disguise

Status: **SUPPORTED in sample, killed by the stress test, and the strongest
result on the holdout.** Not tradeable at the size the others are.

Date proposed: 2026-08-20 (Phase 3, axis G)

**Hypothesis:** rank not on what a stock has done but on what kind of instrument
it is — less liquid, more volatile, lower-priced. If the screen's return is a
size-and-illiquidity premium, this axis finds it, and its success would be the
least interesting news about the strategy.

**A lookahead was found in this axis and removed before freezing.** The first
version ranked on `size_tier_rank` and won the axis with it (+1.312%, t=5.11,
Sharpe 1.46). Size tiers come from NSE's *current* index constituent lists, so a
2021 row carries 2026's membership — and membership is assigned on market cap,
which is to say on the returns being scored. `tests/test_family.py` caught it.
This is the fourth lookahead in this project hiding inside something that is not
a price (H015, the `median_vol_20` denominator, `time_above_open_frac`).

**Without it** — `median_tv_20_cr` + `close_raw`, ascending, top 5:

| | exploration | holdout |
| --- | --- | --- |
| vs market | +0.924% (t=3.28) | **+2.298% (t=6.16)** |
| vs same-day pool | +0.854% (t=3.24) | +2.662% (t=6.92) |
| CAGR / market | 22.67% / 18.25% | **54.89% / 41.78%** |
| Sharpe / market | 1.16 / 1.02 | 2.14 / 2.25 |

**It was frozen as information-only** because leave-one-block-out turned
negative in sample, and information-only rules cannot change the verdict. It
then produced the largest out-of-sample alpha of anything tested. See H032.

**What it buys.** In sample: median 20-day traded value **₹0.71 crore**, p10
₹0.52 crore, 93% outside the top 500, 74% of picks in one (unclassified) sector.
At 2.00% round-trip cost — a fairer number for names that trade ₹7 million a day
— the in-sample book returns 8.41% against a market at 18.25%. **This is not a
strategy that can be traded at any size; it is a measurement of where the pool's
return lives.**

---

## H031 — Capping the book at one name per sector keeps the edge and cuts the concentration

Status: **Marginal in sample, positive out of sample. Frozen information-only.**

Date proposed: 2026-08-20 (Phase 3, axis H)

**Hypothesis:** every top-N rule quietly concentrates — H024's picks are 38% in
a single sector on average. Applying the same scores with a one-name-per-sector
cap is distinct in portfolio construction rather than in information.

**Result:** of nine configurations only the relative-strength score at top 10
cleared the search bar (+0.548%, t=2.74) and its Sharpe (1.01) sits at the
market's (1.02), so it was frozen information-only. Out of sample **+1.016%
(t=3.02)**, CAGR 38.84% against 41.78%.

Reading it beside H026: the sector cap costs the C ranking about a third of its
alpha (+1.73% → +1.38% vs pool out of sample) and buys a lower single-sector
share. It does not change the verdict either way.

---

## H032 — A purged-block stress test predicts out-of-sample survival

Status: **REJECTED.** The filter killed the best out-of-sample rule and kept the
worst. This is the methodological result of Phase 3.

Date proposed: 2026-08-20, tested by construction on the holdout

**Hypothesis:** an in-sample rule that is positive in most of six purged
temporal blocks, positive with any one block removed, and positive in both
halves of the market's trend is more likely to replicate than one that is not.
The bar was fixed before any block was looked at.

**What it did, scored against the holdout it could not see:**

| rule | stress verdict | holdout alpha vs market |
| --- | --- | --- |
| A momentum location (H024) | **survives** | **-0.627%** (t=-1.98) |
| C relative strength (H026) | **survives** | +1.366% (t=3.31) |
| D base quality (H027) | killed (leave-one-out) | -0.645% (t=-2.19) |
| G instrument type (H030) | killed (leave-one-out) | **+2.298%** (t=6.16) |
| H sector capped (H031) | killed (3/6 blocks) | +1.016% (t=3.02) |
| B pullback (H025) | never cleared the search | -0.541% (t=-1.60) |

Two of the three rules the stress test killed were positive out of sample, one
of them the strongest result in the whole phase; one of the two it kept was
negative. **On this sample the filter is uninformative about replication.**

**Why this is worth keeping rather than explaining away.** Six blocks of ~110
sessions each contain one four-month regime apiece, so leave-one-out is a test
of *regime uniformity*, not of robustness — and a rule that only pays in some
regimes is exactly what a rule that pays should look like. The test is not
useless (it is a fair description of how concentrated a result is in time) but
it must not be used as a promotion gate again. n = 6 rules; this is a direction,
not a measurement.

---

## H033 — The frozen family replicates on the 2020-2023 holdout

Status: **REJECTED — verdict FAIL.** The 2020-2023 window is now spent.

Date proposed: 2026-08-20, before the window was opened. Criterion frozen in
`data/metadata/family_frozen.json` and `family.PASS_CRITERION`.

**Kind of work:** confirmatory. The first out-of-sample test this project has
run. Definitions, the holdout window, the cost, and the pass bar were all
written down and hashed before the frame was built.

**The bar, as frozen.** Per member: positive market-excess expectancy at
clustered t≥2; portfolio Sharpe above the market's over the same calendar span
at 0.40% round trip; at least a third of the exploration alpha retained. Family
PASS needs the union book to clear the first two *and* at least two members to
pass. PARTIAL if only the union book clears. FAIL otherwise — and a FAIL drops
the family rather than re-tuning it.

**The window.** 2020-12-29 → 2023-07-06, 59,844 screened mornings over 575
sessions. It starts at the 250th session of the archive so every rolling window
in the panel is full (before that, `dist_52w_high` is measured over a truncated
history that excludes the pre-COVID peak), and its last entry is purged by 30
sessions so no holdout trade is settled on exploration-window prices.

**The result.**

| | exploration alpha | holdout alpha | retention | Sharpe / market |
| --- | --- | --- | --- | --- |
| A momentum location (H024) | +1.172% | **-0.627%** (t=-1.98) | -0.53x | 2.18 / 2.25 |
| C relative strength (H026) | +1.230% | **+1.366%** (t=3.31) | 1.11x | 1.74 / 2.25 |
| union book | +1.106% | +0.359% (t=1.17) | 0.32x | 1.95 / 2.25 |

**Members passing: 0 of 2. VERDICT: FAIL.**

**Two things happened, and they should not be blurred together.**

1. **H024 does not replicate.** The project's first positive result is negative
   out of sample, at t=-1.98, with the sign of its alpha reversed. Proximity to
   the 52-week high plus delivery percentage is not a ranking that survives a
   change of period.
2. **The bar's second clause did the killing for everything else.** The
   equal-weighted market compounded at **41.78% with a Sharpe of 2.25** over the
   holdout — the post-COVID small-cap melt-up. C matched its return (41.50%) with
   a deeper drawdown (-28.3% vs -19.1%), so it fails on Sharpe while beating the
   same-day pool by +1.73% a trade at t=4.98.

**The second point is not a reason to reopen the verdict.** The clause was
chosen before the run precisely because "beats the index" is the question a
person with money faces, and a bar that is only applied when it is passed is not
a bar. What the split does establish is which claim survived: **selection inside
the screen carries real, out-of-sample information (C, and information-only G
and H all beat the same-day pool at t>3); converting that information into a
portfolio that beats buy-and-hold did not work in either window.**

**What is now spent, and what is not.** The 2020-2023 backfill has been read and
cannot be used again. The only untainted data left is the future: sessions after
2026-08-18. Any successor to this work is a forward test, not a backtest.

---

## H034 — Resilience during a broad-market decline predicts subsequent returns

Status: **REJECTED, and the sign is the other way.** The relationship is real
enough to be worth naming but it is *reversal*: inside a causally-identified
market decline, the **least** resilient decile outperforms over the next 1-20
sessions, and the most resilient underperforms.

Date proposed: 2026-08-20. **Kind of work: exploratory / data-generated.** Run
on the sanctioned exploration window 2023-08-21 → 2026-08-18 only. Nothing here
is confirmed, and per H033 there is no clean holdout left to confirm it on.

**The hypothesis as stated.** Identify broad-market down periods using only
information available as of each date; inside each sector, rank liquid stocks by
beta/sector-adjusted resilience over the decline; higher resilience should buy
higher subsequent 1/5/10/20-session returns, in market- and sector-excess terms.

**How "a decline" was made causal.** A decline is only ever a statement about
the **trailing** window. At date D the window is D-K .. D-1 (K = 10 and 20, both
carried), and whether that was a decline is answered from the market's return
over exactly those sessions. The trough is never located, and nothing dated D or
later enters the definition, the universe, or the score. Sessions are cut at
quintiles of the trailing market return over the sample rather than at a chosen
threshold, so the whole shape is visible instead of one side of a line.

**The score.** `resid = r_i(W) - beta_i * r_mkt(W)`, with `beta_i` fitted by OLS
over the 120 sessions ending **one session before W opens** — never on the
decline itself. Ranked into deciles across the day's liquid universe, deciles
after subtracting the sector median, and quintiles inside each sector. Liquid =
EQ, non-ETF, trailing 20-session median turnover ≥ ₹10 cr, prior close ≥ ₹20:
about 650 names a session. Entry at date D's opening print.

**The result (k = 10, broad equal-weighted market, decline stratum = 171
sessions).** Deciles 1→10 by market-excess return, decile 10 being the most
resilient:

| h | D1 … D10 (market-excess, %) | D10 − D1 | t (NW) | Spearman |
| --- | --- | --- | --- | --- |
| 1 | +0.01 +0.07 +0.03 −0.01 −0.01 +0.03 −0.00 −0.03 +0.02 −0.11 | −0.125% | −2.08 | −0.52 |
| 5 | +0.29 +0.20 +0.08 +0.03 −0.10 −0.09 −0.12 −0.14 −0.01 −0.13 | −0.422% | −2.45 | −0.84 |
| 10 | +0.50 +0.20 +0.06 −0.04 −0.25 −0.18 −0.13 −0.13 +0.04 −0.06 | −0.561% | −2.05 | −0.54 |
| 20 | +0.47 +0.14 −0.01 −0.21 −0.32 −0.29 −0.05 −0.13 +0.33 +0.08 | −0.398% | −0.83 | −0.14 |

**It is monotone in the depth of the decline, which is what makes it a finding
about declines rather than about anything else.**

| trailing 10-session market return | sessions | D10−D1 at h=5 | t | at h=10 | t |
| --- | --- | --- | --- | --- | --- |
| below −6% | 54 | −0.702% | −2.83 | −1.139% | −3.65 |
| −6% to −3% | 101 | −0.289% | −1.55 | −0.297% | −0.92 |
| −3% to −1% | 102 | −0.199% | −1.20 | −0.109% | −0.61 |
| −1% to +1% | 134 | +0.152% | +0.80 | +0.391% | +1.79 |
| above +1% | 352 | +0.270% | +1.69 | +0.366% | +1.27 |

**The literal form of the question — quintiles inside each sector, scored on
sector-excess returns — gives the same answer**, and its per-session rank
correlation is the cleanest single statistic in the study: at h = 5, quintiles
Q1→Q5 read +0.30 +0.03 −0.07 −0.13 −0.10, Q5−Q1 = −0.407% (t = −3.21,
Spearman −0.90), rank-IC = **−0.033 (t = −4.85)**, positive on only 32% of
sessions.

**What survives and what does not.**

- *Robust to the definitions.* Negative at every horizon, under both decline
  windows, under both market proxies (all-name equal-weighted and the top-100-
  by-trailing-turnover large-cap stand-in), in market-, sector- and
  beta-adjusted excess, and whether or not date D itself is skipped (skipping it
  keeps −0.382% of the −0.422% at k = 10, h = 5 — so it is not the opening
  bounce or the bid-ask spread).
- *Not one episode.* Leave-one-episode-out over the six decline episodes of ≥10
  sessions leaves the spread between −0.34% and −0.46% (t −1.91 … −2.54). Seven
  of nine episodes have a positive decile-1 excess.
- *Not the overlap.* On non-overlapping sessions (every 5th), all five offsets
  are negative, mean −0.26% to −0.58%; a sign test on 35 independent spreads
  gives 24 negative, exact two-sided **p = 0.041**.
- *Does not survive the multiplicity bar as a single cell.* Over the 20-cell
  grid of 5 market strata × 4 horizons, the permuted maximum |t| has a median of
  2.31 and a 95th percentile of 3.43 against an observed maximum of 2.45:
  **p = 0.42**. The evidence for this is the consistency of the sign and the
  depth gradient, not any one t-statistic, and it should never be quoted the
  other way round.
- *Dead after costs.* At the project's 0.40% round trip the decile long-short
  nets −0.38% a trade at h = 5; long-only decile 1 nets −0.11% at h = 5, +0.10%
  at h = 10 and +0.07% at h = 20. The whole gross spread is smaller than the
  cost of collecting it.

See [[H035]] for the rebound conditioning and [[H036]] for the confound that
explains most of it.

---

## H035 — The effect is stronger when the market subsequently rebounds

Status: **SUPPORTED, and NON_CAUSAL.** Conditions on the future by construction;
it is a statement about mechanism, never an expectancy.

Date proposed: 2026-08-20 (asked as part of the same brief as [[H034]]).
**Kind of work: exploratory, and not even implementable.**

Splitting the decline stratum by the market's *realised* forward return over the
same horizon:

| h | | sessions | D10−D1, market-excess | t | D10−D1, beta-adjusted | t |
| --- | --- | --- | --- | --- | --- |
| 5 | market rebounds | 107 | −0.587% | −2.77 | −1.060% | −4.57 |
| 5 | market keeps falling | 64 | −0.146% | −0.77 | **+0.493%** | +2.33 |
| 10 | market rebounds | 95 | −0.763% | −1.64 | −1.880% | −3.45 |
| 10 | market keeps falling | 76 | −0.308% | −1.47 | **+0.339%** | +2.18 |

**The mechanism, and it is not alpha.** The beta-adjusted column changes sign:
when the market keeps falling, the resilient names do hold up better, exactly as
the original hypothesis says. The bounce is therefore mostly a beta trade —
and specifically a trade on the fact that **estimated beta and realised beta are
different objects**. In the decline stratum, decile 1's pre-decline OLS beta is
0.93 against decile 10's 1.13, yet decile 1's beta *realised over the next five
sessions* is 1.14 against decile 10's 1.04. Sorting on how far a stock fell is
in large part sorting on how much market sensitivity it is about to have, which
no beta fitted before the decline can see.

Not all of it is beta: the per-decile forward regression leaves an intercept of
+0.18% for decile 1 and −0.16% for decile 10 over five sessions.

---

## H036 — Resilience is not separable from the plain drawdown, and it is not momentum, beta or illiquidity

Status: **PARTLY SUPPORTED.** The residual is *not* separable from the raw
window return. It *is* separable from pre-window momentum, beta, liquidity and
trailing volatility.

Date proposed: 2026-08-20, before [[H034]] was run, as its control.
**Kind of work: exploratory.**

**Ranking on the raw window return does the job at least as well as ranking on
the beta- and sector-adjusted residual** — at k = 10, h = 5, D10−D1 is −0.665%
(t = −3.09) on the raw return against −0.422% (t = −2.45) on the residual. A
double sort shows why the question cannot be settled: the two scores are nearly
collinear, so the off-diagonal cells hold 15-30 observations against 18,000 on
the diagonal. Fitting both in the same cross-sectional regression gives
resid +1.07 (t = 0.90) and raw −1.68 (t = −1.29) — a textbook collinearity
blow-up in which neither is estimable. **The honest statement is that this data
cannot separate "held up better than beta predicted" from "fell less", and the
beta/sector adjustment earns nothing observable.**

The other controls behave better. Fama-MacBeth over the decline stratum, all
regressors as centred cross-sectional percentile ranks, so a coefficient is the
top-to-bottom effect in percent:

| h | resid alone | + trailing vol | + vol, beta, turnover, pre-window momentum |
| --- | --- | --- | --- |
| 5 | −0.407 (t −2.88) | −0.501 (t −3.58) | −0.451 (t −3.06) |
| 10 | −0.445 (t −1.77) | −0.656 (t −2.71) | −0.680 (t −2.28) |

Trailing volatility carries its own positive coefficient (+0.94, t = 2.04 at
h = 5) and *strengthens* the resilience coefficient rather than absorbing it, so
"beaten-down names are just volatile names" is not the explanation. Pre-window
relative momentum, measured over the 60 sessions ending where the decline window
opens and therefore sharing no session with it, is flat (t = −0.12). Turnover is
flat (t = −0.23) — unlike H030, this is not an illiquidity premium in disguise;
decile 1's median trailing turnover is ₹31.8 cr against ₹42 cr in the middle
deciles, a mild tilt within a universe that is liquid by construction.

**A selection check that came out clean, for once.** Requiring a sector label
restricts the universe to NSE's *current* index membership — the same class of
lookahead `size_tier_rank` was caught on. Here it is not load-bearing: 84.4% of
decline-stratum rows carry one, and the market-excess spread is −0.422%
(t = −2.45) on all liquid names against −0.435% (t = −2.07) on the labelled
subset alone.

---

## H037 — The reversal-in-declines gradient replicates on 2020-2023

Status: **PASS on the bar as frozen — and the bar had a clause that was too
weak.** Read both halves of that sentence.

Date proposed: 2026-08-20, **before the window was opened**. Spec and criterion
frozen in `data/metadata/resilience_frozen.json`, hash `6738a48730b093ee`,
re-hashed and checked by `resilience.semi_stale()` before it reads anything.

**Kind of work: confirmatory, on a SEMI-STALE window.** 2020-2023 was opened once
already, against the opening-window family ([[H033]]). Nothing that test learned
bears on a cross-sectional reversal signal, so this is worth more than another
pass over 2023-2026 — but the window is not virgin and this result must never be
called out-of-sample. Run on the user's explicit instruction, once.

**Note the sign being tested.** [[H034]] — resilience predicts *higher* returns —
is already rejected. What is being confirmed here is the thing that replaced it:
inside a causally identified decline the **least** resilient decile outperforms,
monotone in the depth of the decline.

**The window.** 2020-04-16 → 2023-07-21, 814 sessions, 163 in the decline
stratum (bottom quintile of the trailing 10-session market return, boundary
−2.12%, recut inside this window so no boundary is imported from the
exploration). It starts where the panel first supports a full 120-session beta
fit and ends 20 sessions before the exploration window opens. **The COVID crash
itself is not in it** — there is no history in front of February 2020 to fit a
beta on — so this window contains the post-COVID recovery, the 2021 run and the
2022 correction, not the crash.

**The result, against exploration.**

| | exploration | semi-stale | |
| --- | --- | --- | --- |
| h=1 decile spread | −0.125% (t −2.08) | **−0.228% (t −2.58)** | replicates, stronger |
| h=5 decile spread | −0.422% (t −2.45) | **−0.484% (t −2.00)** | replicates, same size |
| h=10 decile spread | −0.561% (t −2.05) | −0.037% (t −0.10) | **gone** |
| h=20 decile spread | −0.398% (t −0.83) | +0.367% (t +0.72) | **gone, sign flipped** |
| deepest band (<−6%), h=5 | −0.702% (t −2.83) | **−1.220% (t −3.03)** | replicates, stronger |
| within-sector rank-IC, h=5 | −0.033 (t −4.85) | **−0.042 (t −4.99)** | replicates, stronger |
| k=20 variant, h=5 | −0.318% (t −1.28) | −0.082% (t −0.34) | **gone** |

Depth gradient at h=5, in a window that never saw the exploration: −1.220%
(<−6%), −0.314% (−6..−3), −0.149% (−3..−1), +0.008% (−1..1), −0.045% (>1).

**Why PASS, and why PASS overstates it.** The frozen bar asked for both h=5 and
h=10 negative, one of them at |t| ≥ 2, and the depth gradient preserved. All
three hold. But **h=10 passed its clause on −0.037%, a number indistinguishable
from zero**, and "negative" was too weak a way to write that clause — it should
have asked for a fraction of the exploration effect retained, the way
`family.PASS_CRITERION` does. That is a lesson about writing bars, not a reason
to revise the verdict: a bar applied only when it is passed is not a bar.

**What honestly replicated is the short-horizon effect and the depth gradient.**
h=1 and h=5, the deepest-decline band, and the within-sector rank correlation
all came back at full strength or better. h=10, h=20 and the whole k=20 window
did not. The finding is narrower than [[H034]] reported: it is a **one-to-five
session** reversal that gets stronger the harder the market has fallen.

**And it is still dead after costs, in both windows.** Long-only decile 1 earns
+0.339% market-excess at h=5 and nets **−0.061%** at a 0.40% round trip. Nothing
about the replication changes this.

---

## H038 — The resilience score is a drawdown bet and a beta bet with opposite signs

Status: **SUPPORTED, algebraically and in both windows.** This is the answer to
[[H036]], which could not separate the two by regression.

Date proposed: 2026-08-20. **Kind of work: exploratory (the decomposition and
its exploration-window numbers), then confirmatory on the semi-stale window as
a non-gating clause of [[H037]].**

**The algebra.** Within one session `resid_i = r_i − beta_i · r_mkt`, and
`r_mkt` is a constant across the cross-section. So projecting `resid` off the
raw window return `r_i` can leave only `−r_mkt` times the part of `beta_i` that
`r_i` does not explain. **Conditional on how far a stock fell, "held up better
than its beta predicted" is nothing but beta.** Checked rather than assumed:
per-session correlation between the orthogonalised score and
`−r_mkt · beta⊥drawdown` is **1.000000 on 100% of decline sessions**, and
`test_orthogonal_score_is_exactly_beta_in_disguise` fails if that ever stops
holding.

The score is therefore a blend of two bets pointing opposite ways, which is why
it is weaker than either of them:

| component | exploration h=5 | semi-stale h=5 | semi-stale h=20 |
| --- | --- | --- | --- |
| drawdown ⊥ residual (fell less) | −0.904% (t −1.92, ρ −0.95) | −0.250% (t −0.45, ρ −0.48) | −1.649% (t −2.10, ρ −0.84) |
| beta ⊥ drawdown (resilience proper) | +0.555% (t +1.27, ρ +0.90) | −0.018% (t −0.03, ρ −0.02) | +1.485% (t +1.92, ρ +0.79) |
| beta alone | +0.759% (t +1.64, ρ +0.96) | +0.260% (t +0.48, ρ +0.18) | +1.745% (t +2.20, ρ +0.81) |

The beta component is indistinguishable from ranking on beta itself, in both
windows, at every horizon — which is what the algebra says it must be. The
Spearman coefficients are high on both sides even where the spreads are not
significant, so both halves are genuine gradients rather than outlier buckets.

**What this settles.** The beta and sector adjustments in the original
formulation are not refinements of the drawdown score; they add a second,
opposing sort on beta. Anyone wanting "resilience" as a distinct idea should
rank on beta directly and stop calling it resilience — and should expect a
rebound bet ([[H035]]), not alpha.

---

> **Ledger note, 2026-08-22.** `H039` and `H040` exist in the research store
> (both `rejected`) but were never written up here. `H039` is cited in
> `PLAN.md` — mean IC −0.0227 at t = −5.02 over 729 sessions, classified
> `NO_SIGNAL` because its Q5–Q1 spread was 19.5 bps against a 40 bps round
> trip — and that number is load-bearing for the argument that this lab is
> short of magnitude rather than of significance. Recorded here as a known gap
> rather than backfilled from memory: `python -m src.cli hypotheses --id H039`
> reads the store, which is authoritative for both.

---

## H041 — AI discretionary selection adds value over the pool it is given

Status: **PROPOSED.** Registered 2026-08-22 with the pivot to `MISSION.md`. No
replay has been revealed against it yet.

Family: `ai_discretionary`. **Kind of work: none yet.** This entry is the
pre-registration, written before any case was judged.

**The claim.** Given a rich point-in-time case — chart structure, location in
the range, market and sector state, relative strength, volume and delivery
behaviour, and comparable prior situations — an AI reasoning as a discretionary
trader selects candidates whose forward excess return beats *both* the
unfiltered candidate pool *and* a simple quantitative ranking on the same cases.

**Why it is worth the sample.** Every negative result in this ledger that was
close came down to magnitude, not significance: [[H039]] scored t = −5.02 and
died on a 19.5 bps spread against a 40 bps round trip. A cross-sectional signal
must commit to one functional form across every regime and every name. A
discretionary judge can condition on context that no single column encodes,
which is a claim about *effect size* — the thing the lab is actually short of.

**The honest weak point, recorded rather than argued away.** The archived
operating plan's highest-leverage demand is that a proposal name who is on the
other side of the trade and why they keep taking it. For a judgement call the
answer is genuinely unclear. If nobody is persistently on the other side, a
measured edge is a data artefact — and it will not announce itself as one.

**What would falsify it.** TAKE mean excess at or below the mean over all
candidates, on a per-session paired basis. The frozen bar is +60 bps against the
pool and +30 bps against the best quantitative baseline at a matched take rate.
The first replay uses the broad `liquid_universe` generator precisely so that no
screen does any of the work and every point of lift belongs to the judge.

**What it must not be read as.** A replay spends `train` exactly as an
exploration does. It is counted by `runner.burden` under
`signal_id = "replay:<id>"`, and a re-run with a changed prompt or a changed
model is a *new test of the same sample*, not a refinement of this one.

---

## H042 — Revealed identity beats anonymised identity, i.e. the model remembers

Status: **PROPOSED.** Registered 2026-08-22. `conditions-on` [[H041]].

Family: `ai_discretionary`. **Kind of work: none yet.** This is a control, and
it is pre-registered as one.

**The claim.** The same replay run with the symbol and calendar date revealed
scores materially better than the anonymised arm, indicating the judgement is
drawing on memorised price history rather than on the case in front of it.

**Why this cannot be handled the way the other four lookaheads were.** Every
lookahead this project has caught lived in a *frame* — the entry day's own close
(H015), an unlagged denominator, a present-day snapshot attribute, an interval
only knowable after the next observation printed. Each was closable by fixing
the data. This one lives in the model's weights: a model asked about an Indian
equity in a named quarter may simply recall what happened next, and no amount of
frame hygiene touches that. A leak that cannot be closed has to be *measured*.

**The design.** Two replays over one case set differing in exactly one field —
`anonymise`. Cases are anonymised by default, so the revealed arm is the
deliberate one. `case_hash` covers the rendered text, so the two arms hash
apart and neither can serve the other's decisions from cache.

**How to read the two outcomes.** A null result licenses reading every
anonymised replay in this lab as judgement. A positive result voids every
revealed-identity result and puts a floor under how much of any anonymised
result is recall rather than reasoning — it does not, by itself, invalidate the
anonymised arm.

**Until this has been run, every discretionary finding in this lab carries an
asterisk,** and `PLAN.md` §6 lists it as the stage that gates belief in the
rest.


## H043 — Directional overnight bulk flow separates outcomes; the reported deal does not

Status: **REJECTED at pre-flight, 2026-08-23, without spending a case.** The
separation screen registered below was run on `train` under its own rules and
found that nothing describing the disclosed position separates outcomes, while
the two features that do separate outcomes do so at full strength on
round-trip days where no position was disclosed at all. The claim was never
"bulk-deal days are unusual" — it was that *directional* flow adds a findable
increment over round-trip flow, and that is the half that failed. FINDINGS.md,
2026-08-23. No dispatch was spent; `validation`, `test` and `forward` are
untouched and the family costs the sample budget nothing.

Registered 2026-08-22. Pre-registered before any directional test.
`conditions-on` nothing; it is a fresh family.

Family: `bulk_deals`. **Kind of work: label-free so far.** The event layer,
the point-in-time client classification and the dispersion gate have all been
run. No outcome mean has been read and no dispatch has been spent.

**The claim.** When a client who takes positions — as distinct from a market
maker who ends the session flat — accumulates or distributes a name through a
disclosed bulk deal, the ten-day outcomes of that name separate more than for
size-, volatility- and liquidity-matched names in the same session, **and more
than for names whose only bulk activity that session was round-trip flow.**

**Why the second clause is the hypothesis and the first is not.** The
dispersion gate found bulk deals fanning outcomes out at 1.217 over a matched
control at h=10 (FINDINGS.md, 2026-08-22). Splitting the file destroys most of
that story:

| subset | h=1 | h=10 | n | per session |
| --- | ---: | ---: | ---: | ---: |
| all bulk, as reported | 1.386 | 1.225 | 15,373 | 11.2 |
| round-trip only | 1.323 | **1.218** | 12,331 | 9.0 |
| directional | 1.431 | **1.384** | 3,042 | 2.9 |
| — accumulation | 1.489 | 1.364 | 1,666 | 2.1 |
| — distribution | 1.344 | 1.478 | 1,359 | 1.9 |

**Round-trip sessions carry almost the whole headline number.** A day on which
the only bulk activity was Graviton crossing its own book is followed by
outcomes 20% more dispersed than matched controls, and no positioning
information was disclosed at all. Most of "bulk deals predict dispersion" is an
attention or volume effect that survived matching on volatility and liquidity.

What is left is an increment: 1.384 against 1.218 at h=10. That increment is the
hypothesis, and the correct control is therefore **round-trip sessions**, not
the market and not the matched panel. A test run against the panel would clear
easily and would have proved nothing.

**Why it is worth the sample.** The counterparty question, which [[H041]]
records as genuinely unanswered for a discretionary judgement, has an actual
answer here. A promoter selling into a block, a fund forced out by redemptions,
an anchor exiting at lock-up — these are participants trading for reasons other
than believing the price is wrong, and they are disclosed by regulation with a
timestamp. That is the cleanest mechanism this project has had.

**What would falsify it.** Directional flow shows no dispersion increment over
round-trip sessions once matched, or the increment exists but the outcome
separation is not predictable from anything — coded or judged — at a magnitude
clearing the 40 bps round trip.

**The trap this family sets, recorded now.** The client classification is what
makes the event mean anything, and the obvious implementation of it reads the
future: labelling a 2021 deal by a client's 2025 behaviour. `client_profile` is
expanding and shifted, a client with fewer than ten prior sessions is `unknown`
rather than assumed, and `tests/test_bulk_deals.py` asserts both. This is the
H015 lookahead in a new costume and it would not have announced itself.

**The narrowing to distribution is WITHDRAWN, 2026-08-22, same day.** It was
registered on 1.331 against 1.021 at a 1-crore liquidity floor, and that floor
had never been varied. At 0.25 cr distribution reads 1.200 and at 0.10 cr it
reads 1.075 against a null of 1.061 — it meets the null. `directional`, either
sign, reads 1.240 / 1.233 / 1.238 across the same three floors. **The primary
claim reverts to directional flow of either sign**; accumulation and
distribution are descriptive splits, not the hypothesis. Recorded rather than
quietly rewritten, because a narrowing chosen on one parameter setting and
called a pre-registration is the H024 failure in miniature.

Also corrected: every dispersion figure below was read against a null of 1.00.
Against random events carrying the *real* per-session counts the modern null is
**1.061 (sd 0.063)**, so 1.240 is ~3 sd rather than the 4 the raw ratio implies.

**Superseded narrowing, kept for the record:** Head to head against
round-trip days on the same sessions, accumulation reads 1.021 at h=10 and
distribution 1.331. The whole increment is on the sell side, so the primary
claim is about **distribution only** and accumulation is a declared secondary.
Registering the narrowing here rather than discovering it after a result.

**Power, and why the test is not yet worth commissioning.** Simulated on the
real session structure at the measured event persistence (overlap share 0.19),
against the frozen bar:

| true edge | 50 | 75 | 100 | 150 | 200 |
| --- | ---: | ---: | ---: | ---: | ---: |
| distribution | 10% | 27% | **46%** | 86% | 99% |
| directional | 18% | 46% | 70% | 99% | 100% |

A realistic selection edge is 20-80 bps. **A null today would settle nothing
and would cost the sample doing it.** The 2004-2019 deals already on disk —
122,293 of them over 3,914 sessions — triple the session count once the legacy
price panel exists, which is the difference between a coin flip at 100 bps and
a decisive answer. That build is the precondition, and it spends no sample.

**Sample shape.** 8,664 directional symbol-sessions over 1,405 sessions, 6.8
per session before the liquidity filter and 2.9 after — above the two-per-session
floor `validate_sample_adequacy` requires, and roughly 120 independent blocks at
h=10, comfortably above `MIN_INDEPENDENT_BLOCKS`. Accumulation and distribution
are near-balanced at 4,378 and 4,191.

### H043 pre-flight — the separation screen, registered before it was run

Registered 2026-08-23, **before any first moment was read anywhere in this
family**. Everything H043 has produced so far is a second moment; this is the
first thing in the family that looks at the sign of an outcome, and it is
therefore the first thing capable of being fitted. So the whole design is
fixed here, in advance, and reported in full afterwards whatever it says.

**The question.** Within directional bulk-deal days — the one arm that
survived the withdrawal, 1.233-1.240 dispersion against a 1.061 null —
**does any simple coded feature separate the outcomes?** The family's only
surviving claim is that outcomes after these events fan out. Fanning out is
not tradeable by itself; something has to say *which* names went which way.

**Why this is the right thing to spend nothing on.** If a coded feature
separates them, the family has a mechanism to hand a judge and the replay is
worth commissioning. If nothing separates them at a magnitude the replay could
ever have detected, the replay cannot detect it either — 1,208 events beat 500
cases — and the family is finished without a case being dispatched.

**Partition: `train` only.** `validation`, `test` and `forward` are not read.
The dispersion work ran unpartitioned, which was defensible for a second
moment and is not defensible here.

**The eleven features, fixed now.** Flow: `net_flow_signed` (net directional
quantity over trailing median raw volume), `net_flow_abs`, `value_vs_turnover`
(deal value over a normal day's turnover). Price: `premium_pct` (deal VWAP
against the same session's raw close), `premium_signed` (the same, signed by
the direction of the flow, so that a buyer paying up and a seller taking a
discount are the same sign). Structure: `dir_clients`, `round_trip_share`,
`direction_sign`. Context: `volx` (the session's own volume against normal),
`vol20`, `mom20`. Nothing else is added afterwards; a twelfth feature invented
after seeing these eleven is a new test and is registered as one.

**The statistic.** Terciles of the feature over the directional set, top minus
bottom, in **basis points of ten-day excess return**, with a Driscoll-Kraay
standard error at `lags = horizon - 1`. Reported alongside it, because the
family's claim is a dispersion claim: the ratio of top-tercile to
bottom-tercile mean |excess|, which asks whether the feature finds *where* the
fan-out lives even if it cannot say which way.

**The null is built, not assumed.** For each of 200 draws, every event keeps
its features and is re-pointed at a random non-event name from the same
session matched on the volatility, liquidity and volume-surprise quintile —
the same matching `spread.check` uses. That yields the distribution of the
statistic when the features are attached to nothing, and in particular the
distribution of the **largest absolute spread across all eleven features**,
which is what an eleven-feature screen has to clear rather than the
single-feature band. This lab has already measured that a corrected |t|
over-rejects 13.3% of the time at this block count; a built null is the only
kind worth quoting here.

**Swept, not chosen: liquidity floor at 1.00 / 0.25 / 0.10 crore, horizon at
1 and 10.** Six configurations, sixty-six feature readings, every one of them
reported. The distribution narrowing died because a floor was never varied.

**The decision rule, fixed in advance.** A feature separates outcomes if it
(a) clears the 95th percentile of the null max-|spread| band, (b) carries the
same sign at all three liquidity floors, and (c) exceeds 40 bps at h=10, the
round-trip cost. All three, or the answer is no.

**What a null buys.** Not "there is nothing here" — "there is nothing here
larger than X", where X is the null band, and X is then the honest ceiling on
what the replay could have found. That number is the deliverable when the
answer is no.


### H043 pre-flight — the result

Run 2026-08-23 exactly as registered: eleven features, three floors, two
horizons, `train` only, sixty-six readings all reported in FINDINGS.md.

**Nine of eleven features sit inside the eleven-feature null band, including
every feature that describes the deal** — net flow against normal volume, deal
value against normal turnover, client count, round-trip share, and the
direction of the flow itself.

**The two that clear it are not about the deal.** Trailing volatility and the
deal's distance from the close both reproduce at full strength on round-trip
days, on five to eight times the sample:

| | h=1, directional | h=1, round-trip | h=10, directional | h=10, round-trip |
| --- | ---: | ---: | ---: | ---: |
| premium_pct | −107 to −184 | −68 to −130 | −162 to −419 | −216 to −399 |
| vol20 | −90 to −129 | −31 to −80 | −444 to −561 | −227 to −457 |

**The band, which is the power statement.** ±57 to ±72 bps at h=1 and ±172 to
±271 bps at h=10 on 1,179–1,801 events. A 500-case replay carries a third of
that and would see less. The null is therefore a ceiling on what the replay
could have found, not merely an absence of evidence — which was the point of
running the screen before commissioning one.

**A correction made after the first run and disclosed rather than folded in.**
The registration said the null band was the distribution of the statistic with
the features attached to nothing; the first implementation read the raw spread
against a band assumed to be centred on zero. Because a control is matched on
the volatility quintile, a volatility feature partly reproduces itself in its
own null, so the band is now centred on the null's own mean and the reported
number is the excess over it. The decision rule did not change. Uncentred,
`premium_pct` would have cleared at h=10 as well.

**Also fixed, and it invalidated a feature rather than blurring it:**
`deal_vs_close_pct` was comparing a raw deal price against a back-adjusted
close, and in a name that later split it returned the split factor. The median
premium fell from +1.82% to 0.00% once both legs were raw.


## H044 — A bulk print far from the close is followed by continuation

Status: **REJECTED AT THE TRAIN EXECUTION GATE; validation unopened,
2026-08-23.** The close-to-close diagnostic survived after its horizon was
corrected, but the feature requires the completed close and therefore cannot
trade at that close. From the first executable entry, the next session's open,
the event-minus-twin increment is +5.8 bps with t=0.35 — the registered
negative continuation is absent — and the 40-bps-cost portfolios lose money.
Registered 2026-08-23, from the wreckage of [[H043]] and explicitly *not*
inherited from it. `conditions-on` nothing.

**The claim.** On a session following a disclosed bulk deal, the distance
between the deal's print price and the session's raw close ranks the next
day's excess return: a name that has fallen below the print keeps falling, one
that has risen above it keeps rising. **The direction of the flow is not part
of the claim and neither is the identity of the client** — it holds on
round-trip days, which is precisely why it cannot be credited to H043.

**Why it is registered separately rather than as an H043 result.** PLAN.md §2.2
names this cell: a rule carrying an edge without reproducing the hypothesis it
was found under is a new quantitative idea found nearby, and crediting it to
the family that produced it is how a rejected family gets resurrected by its
own residue. H043 is rejected. This inherits none of its argument, none of its
mechanism and none of its priors.

**The evidence so far, all on `train`.** Top-minus-bottom tercile, h=1:
−68 to −130 bps on round-trip days (n=5,983–8,165), −107 to −184 on
directional days (n=1,179–1,801), against −12 to −23 bps for the
magnitude-matched deal-free twin on ~1,000,000 rows. Stable in sign across
all three liquidity floors. It is a **coded** rule with no judge in it, so it
belongs to the signal path and the case budget is not the resource it needs.

**Two contaminants to clean before it is scored anywhere.** NSE publishes bulk
deals after the close, so the first tradable session is D+1 in 100% of rows
and the feature spans a day and a half of realised return rather than an
execution concession — the comparison against a same-length deal-free window
is therefore mandatory, not optional. And a name going ex-split inside that
gap produces a spurious ±100% premium that lands in an extreme tercile.

**What would falsify it.** The effect disappears once the deal-free
magnitude-matched twin is subtracted at the same horizon and the same
thresholds, or it fails to clear 40 bps net of the round trip, or it does not
survive `validation`.

### H044 train cleanup — registered before the run

Registered 2026-08-23 before reading any additional H044 outcome. This is the
last exploration step. It either rejects H044 on `train`, or freezes a test
that may later be dispatched to `validation`; it does not read `validation`,
`test` or `forward`.

**Population and feature.** Pool every bulk-deal symbol-session; client type
and flow direction are not selection variables. At each liquidity floor
(1.00 / 0.25 / 0.10 crore), compute
`100 * (all_deal_vwap_D / close_raw_D+1 - 1)`, where D+1 is the first tradable
session after publication. The one-session excess outcome begins at that D+1
close. This makes the entry timing explicit: it is continuation after the
feature becomes observable, not a concession captured at the deal print.

**Corporate-action quarantine.** Drop an event if the tape's adjustment factor
changes between the deal date and the first-tradable close, or if the
reconciliation table places a corporate action in that interval. The primary
is also repeated after dropping `|premium| > 10%`; a result that needs those
extremes does not proceed.

**The twin.** On non-event names from the same sessions, use
`100 * (vwap_raw_D / close_raw_D+1 - 1)`: the same-length realised move with no
bulk print. Derive the lower and upper tercile cuts from the clean event set
once per floor, then apply those exact numeric thresholds to both populations.
Do not re-tercile the twin into an easier comparison.

**The statistic.** Within each session carrying both tails in both arms,
compute `(event top - event bottom) - (twin top - twin bottom)` in next-day
excess return. Sessions, not rows, receive equal weight. Report the component
spreads, the paired increment, its Driscoll-Kraay t-statistic at lag zero, the
number of paired sessions, and the frozen cuts.

**Decision.** The registered direction is negative. To remain alive, the
paired increment must be negative, exceed 40 bps in absolute value at all
three liquidity floors, and do the same after the 10% extreme-value exclusion.
Anything else rejects H044 on `train`. If it clears, freeze the 1-crore cuts
and the same 40-bps rule before anyone opens `validation`.

### H044 train cleanup — result and freeze

**SUPERSEDED 2026-08-23 by the execution check below.** Kept because this is
what the registered close-to-close diagnostic first reported; it is not an
executable result.

Run 2026-08-23 as registered, on `train` only. One implementation correction
preceded the final run: event VWAP had been a mean of client prices rather than
`sum(value) / sum(quantity)`. A one-share print therefore had the same weight
as a million-share print. The code and regression test now use the disclosed
quantity; every number below is from the corrected implementation.

| floor | cap | cuts, % | event | twin | paired increment | t | sessions |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1.00 cr | none | −1.751 / +2.147 | −93.4 | −19.6 | **−73.8 bps** | −3.22 | 526 |
| 1.00 cr | 10% | −1.505 / +2.063 | −85.5 | −14.9 | **−70.6 bps** | −3.12 | 516 |
| 0.25 cr | none | −1.889 / +2.187 | −104.7 | −25.9 | **−78.8 bps** | −4.58 | 604 |
| 0.25 cr | 10% | −1.636 / +2.060 | −94.7 | −21.4 | **−73.3 bps** | −4.65 | 587 |
| 0.10 cr | none | −1.937 / +2.238 | −107.2 | −31.8 | **−75.4 bps** | −4.61 | 628 |
| 0.10 cr | 10% | −1.666 / +2.089 | −120.7 | −26.4 | **−94.3 bps** | −3.31 | 617 |

The no-deal twin explains a real minority of the headline continuation, but
not most of it. The increment clears the registered 40-bps floor in the stated
direction in every cell, including after the extreme-value exclusion. Between
31 and 43 event symbol-sessions per floor were quarantined for a factor change,
an unresolved factor, or a reconciled corporate action in the print-to-entry
gap. **H044 survives exploration.** This is not a finding of alpha until an
unseen partition agrees.

**WITHDRAWN — do not run this validation test.** The intended frozen test used
the 1.00-crore population,
the identical action quarantine and same-session no-deal twin, h=1, and the
train cuts **−1.7510% / +2.1473%**. Do not compute validation terciles. The
primary statistic is the equal-weight session-paired increment. PASS requires
both `increment <= −40 bps` and Driscoll-Kraay `t <= −2.0`; otherwise REJECT.
The `|premium| <= 10%` row is reported as a sensitivity using the same frozen
primary cuts and does not replace the primary. As of this freeze,
`validation`, `test` and `forward` have not been read for H044.

### H044 execution check — rejection

Run 2026-08-23 on `train` only, before opening the frozen validation test.

**A horizon bug first.** `report.panel(liquid, 1)` shifted after the liquidity
floor was applied. When the next row fell below the floor it silently exited on
a later row and still called that h=1. Only 25 of 7,177 clean 1-crore events
were affected (0.35%), but their median extra gap was 18 calendar days and they
were extreme enough to move the paired increment from −73.8 to **−54.0 bps**
(t=−2.86). `h044_cleanup` now constructs the next row on the full tape before
filtering. The corrected close-to-close result still clears its registered
diagnostic bar at every floor; this correction alone does not reject it.

**The rejection is execution timing.** `premium_pct` contains the completed
D+1 close. A decision using it cannot also enter at that close. The earliest
honest entry is D+2 open, so the executable one-session question is D+2
open→close. On the frozen 1-crore tails:

| outcome | event top−bottom | twin top−bottom | event−twin | t | sessions |
| --- | ---: | ---: | ---: | ---: | ---: |
| corrected D+1 close→D+2 close | −72.4 | −18.4 | **−54.0** | −2.86 | 527 |
| executable D+2 open→close | +23.6 | +17.7 | **+5.8** | +0.35 | 527 |

The registered continuation not only falls inside noise after an executable
entry; its point estimate changes sign. The long tail earns −71.0 bps gross
open→close and the short tail +41.7 bps gross. At the project's 40-bps round
trip, neither supports the claimed two-sided signal, and the equal-weight
short-only train book is negative after costs. **H044 is rejected without
opening `validation`; the withdrawn cuts must not be dispatched.**


## H045 — Equity-futures cash-and-carry earns an attractive return on deployed capital

Status: **PROPOSED — DATA GAP.** Registered 2026-08-23 before any futures-basis
outcome was read. `conditions-on` nothing; this is a fresh family.

Family: `equity_futures_carry`. **Kind of work: hypothesis generation.** A
source probe and outcome-free structural pre-flight may proceed; no historical
entry rule, early-exit rule or leverage policy has been selected or scored.

**The claim.** At observable executable prices, selected NSE single-stock
futures sometimes trade sufficiently rich to cash that buying the shares and
shorting the corresponding future earns a positive annualised return after
financing, dividends, all entry/exit or physical-settlement charges, bid-ask
slippage, margin collateral drag and operational buffers. The primary estimand
is return on total capital encumbered, not the headline futures premium. It must
clear a pre-frozen hurdle above an investable low-risk INR alternative and
remain useful at the project's ₹5–10 lakh capital scale after whole-lot sizing.

**Mechanism and the participant on the other side.** Leveraged directional
demand, hedging constraints and limits on arbitrage capital can make futures
temporarily rich relative to deliverable cash. The proposed return is payment
for funding the cash leg, posting collateral, absorbing mark-to-market and
margin calls, managing dividends and corporate actions, and guaranteeing
physical delivery into expiry. This is an arbitrage/financing hypothesis, not
a forecast of the stock's direction.

**The advanced policy is a separate, nested question.** Enter only when the
PIT net annualised locked yield clears a frozen hurdle. Each session, recompute
the remaining net yield from executable unwind prices and exit early only when
the incremental return from continuing falls below the PIT alternative rate
plus a frozen switching buffer, or when the freed capital can enter a strictly
better carry after paying both trades' costs. Leverage is capped from a
cash-flow stress rule using observed exchange/broker margins and adverse daily
variation-margin scenarios; it may scale an already positive trade but may not
turn a sub-hurdle spread into one. Hold-to-expiry is the mandatory baseline;
an early-exit policy must beat it on the same opportunity set.

**Strongest simple baselines.** (1) Hold an INR Treasury-bill/liquid-fund proxy
over the same calendar span; (2) mechanically take every liquid positive-net-
carry contract and hold to expiry without timing; (3) rank only by net locked
yield and allocate greedily subject to whole lots, without a learned early-exit
rule. Complexity earns credit only for incremental return on encumbered capital
and lower drawdown/liquidity stress against these baselines.

**Required point-in-time observations.** Daily or intraday cash and futures
bid/ask or defensible executable-price proxies; contract expiry and historical
lot size; physical-settlement rules; futures and cash volumes/open interest;
historical SPAN/exposure/ELM and broker add-on margins; funding and collateral
interest actually available to this account; announced dividends with
ex-dates and PIT availability; corporate actions and symbol history; every
cash, futures and settlement tax/fee; and the calendar/auction mechanics of
delivery. All derivatives bytes must enter through `research_data`; an
experiment may not read downloaded bhavcopies directly.

**Structural pre-flight.** Before any strategy backtest, measure contract-day
coverage, cash/futures join rate, expiries and lot histories, executable depth,
whole-lot capital required, gross implied annualised carry, and sensitivity of
the net yield to conservative one-tick/two-tick slippage, funding and margin
assumptions. Quarantine dividend and corporate-action windows until their PIT
cash flows reconcile. A close-only probe can establish whether spreads are
large enough to justify building the data product; it cannot establish
tradeability or an early-exit edge.

**Natural falsifiers.** Reject further work if conservative net locked yields
rarely clear the alternative-rate hurdle; qualifying lots do not fit the
capital budget; apparent richness concentrates in illiquid contracts,
corporate-action/dividend mistakes or the expiry close; funding plus margin
cash-flow stress eliminates the advantage; or a dynamic exit cannot beat the
hold-to-expiry baseline after switching costs under a frozen rule.

**Leakage traps recorded now.** Use only information published by the decision
time. Do not backfill today's lot sizes or F&O universe into history; do not use
dividends before announcement; do not treat final settlement prices or closing
bhavcopy values as executable before the close; do not select a contract using
its later minimum margin; and do not annualise a spread without retaining its
actual days-to-expiry and calendar cash encumbrance. Corporate-action-adjusted
cash and raw futures are not comparable unless their cash flows are reconciled.

**Decision after the cheap probe.** Continue only if official historical data
is obtainable with stable PIT semantics and the untuned cross-section contains
a recurring, liquid gross cushion comfortably larger than plausible financing
and all-in execution costs. Otherwise keep H045 as a documented data-gap null
and spend the engineering budget on a more reusable source.

### H045 cheap source probe — 2026-08-23

**The source is feasible; the economic case is marginal enough to sequence
carefully.** NSE's historical contract report returned March 2024 stock-futures
settlement prices, volume, turnover and open interest. Ten sessions from
02–15 January for RELIANCE, HDFCBANK, ICICIBANK, INFY and TCS joined exactly to
the project's raw cash bhavcopy: 50/50 contract-days. The selected March
contract was one of the three listed maturities throughout the window.

Using the futures daily settlement and cash close only as a magnitude screen,
and ignoring dividends initially, gross simple annualised basis had median
**9.40%**, p10 **8.09%**, p90 **10.29%** (range 5.16–10.70%). The 91-day T-bill
auction cut-off on 03-Jan-2024 was **6.94%**. The gross cushion was therefore
roughly 2.5 percentage points annualised at the median before execution,
funding, margin drag, taxes and settlement costs — real enough to measure, not
large enough to assume.

The low TCS tail proved why dividends are mandatory rather than a refinement.
TCS announced ₹27 per share on 11-Jan with a 19-Jan record date. Adding that
PIT-known cash flow lifts the apparent annualised carry from 6.28% to 9.62% on
12-Jan and from 5.16% to 8.62% on 15-Jan. A basis study without announcement-
timed dividends would systematically mis-rank exactly the contracts that look
cheap.

Historical lots inferred from the report's contract count and turnover were
250 RELIANCE, 550 HDFCBANK, 700 ICICIBANK, 400 INFY and 175 TCS shares. The
median cash leg was **₹6.10–9.17 lakh per position** across these five names,
before futures margin and variation-margin liquidity. At the project's
₹5–10 lakh scale that is one concentrated lot, not a diversified carry book;
leverage increases cash-flow fragility rather than solving sizing.

The path has enough variation to keep the early-exit question alive but not to
answer it. From 02-Jan to 15-Jan the raw basis compressed by ₹0–30.10 per share
across the five names, equivalent to 0–22.34% annualised realised return on the
cash leg over those thirteen calendar days (median 14.72%). This is a
hindsight, settlement-price diagnostic; an honest policy must use executable
unwind quotes, PIT dividends and a switching-cost buffer, and must beat simply
holding the same entries.

**Source defect caught in the probe.** The report's `Underlying Value` is not
historical: for several symbols one present-day number was repeated down all
January 2024 rows, while other symbols showed `-`. It must be discarded. The
cash leg must come from the point-in-time bhavcopy. Settlement price is a
last-half-hour weighted price and is not an executable bid/ask, so none of the
figures above is a trade result.

**Go/no-go.** Worth a bounded data-contract and E0 pre-flight, because the
official archive is deep, joins cleanly and the gross spread clears the T-bill
reference in this deliberately small sample. Not worth building learned early
exits or a leverage optimiser yet. First acquire daily bhavcopies, historical
contract files/lot sizes, PIT dividends, historical charges and margin files;
then kill the family cheaply if conservative net hold-to-expiry carry does not
clear a frozen alternative-rate buffer. Status remains **PROPOSED — DATA GAP**;
no strategy outcome or partition was read.


## H046 — The disclosed bulk print versus the deal-day close predicts D+1 intraday continuation

Status: **REJECTED AT THE TRAIN ECONOMIC GATE; validation unopened,
2026-08-23.** The event-specific signal is real on train, but the registered
1-crore tradable arms are all negative in excess return after 40 bps.
`conditions-on` [[H044]] only as motivation; it changes the information clock
and is a new test, not a rescue of H044.

**The claim.** A bulk deal on D is disclosed after D closes. At that point both
the quantity-weighted bulk print and D's raw close are known. If the close is
above the print, go long at D+1 open; if it is below the print, go short. The
outcome is D+1 open-to-close adjusted return. No part of D+1 is used to choose
the trade.

**Population and feature.** Pool all bulk-deal symbol-sessions, without using
client identity, flow direction or round-trip status. At liquidity floors
1.00 / 0.25 / 0.10 crore compute
`premium_D = 100 * (all_deal_vwap_D / close_raw_D - 1)`. Freeze lower and upper
tercile cuts separately at each floor on `train`; lower is the long tail and
upper the short tail. Repeat after excluding `|premium_D| > 10%`. Quarantine
missing or changed adjustment factors and reconciled corporate actions between
D and the D+1 open.

**Exact twin and statistic.** On names with no bulk event on D, use
`100 * (vwap_raw_D / close_raw_D - 1)` and their next traded session's
open-to-close return. Apply the event cuts to this twin; do not re-tercile it.
Pair `(event top - event bottom) - (twin top - twin bottom)` within D+1 entry
sessions, equal-weight sessions, and report the lag-zero DK t-statistic. The
registered direction is negative. Also report standalone long, short and
50/50 long-short gross bps per trade and subtract the project's 40-bps round
trip from the tradable portfolios; the twin-subtracted increment itself is a
diagnostic, not a portfolio return.

**Decision.** H046 survives exploration only if the 1-crore primary has a
negative event-minus-twin increment with `t <= -2`, the sign remains negative
at every floor and with the 10% cap, and at least one frozen 1-crore tradable
portfolio is positive after 40 bps. Otherwise reject on `train`. Do not read
`validation`, `test` or `forward`; a survivor requires a separately frozen
validation dispatch.

### H046 train result — signal present, meaningful alpha rejected

Run 2026-08-23 as registered. The implementation forms the immediately next
traded row on the full tape before applying a liquidity floor, requires the
no-deal twin to traverse the identical D-to-D+1 market-session pair, and drops
31–41 action-contaminated event rows. `validation`, `test` and `forward` were
not read.

| floor | cap | cuts, % | event | twin | increment | t | events / paired sessions |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1.00 cr | none | −0.7295 / +0.7412 | −55.6 | −2.4 | **−53.2 bps** | −2.99 | 7,055 / 523 |
| 1.00 cr | 10% | −0.7283 / +0.7326 | −55.7 | −2.3 | **−53.4 bps** | −3.00 | 7,013 / 522 |
| 0.25 cr | none | −0.6952 / +0.7003 | −69.3 | −1.2 | **−68.1 bps** | −4.23 | 8,938 / 596 |
| 0.25 cr | 10% | −0.6900 / +0.6849 | −68.5 | −1.0 | **−67.5 bps** | −4.21 | 8,867 / 594 |
| 0.10 cr | none | −0.6830 / +0.6918 | −60.6 | −2.2 | **−58.4 bps** | −3.78 | 9,876 / 628 |
| 0.10 cr | 10% | −0.6826 / +0.6731 | −59.7 | −2.1 | **−57.6 bps** | −3.71 | 9,792 / 628 |

The ordinary VWAP-to-close twin carries essentially none of the effect, and
the sign is stable everywhere. But the 1-crore primary is not economic. Long,
short and 50/50 long-short earn respectively **−16.9, −5.4 and −12.2 bps of
excess return after the 40-bps round trip**. The short tail's raw +74.9 bps is
flattered by down-market entry sessions; its market-relative return is only
+34.6 bps before costs. The lower-liquidity short tails read +7.3 to +15.2 bps
net excess, but those registered robustness rows cannot replace the failed
primary after the outcome is known. H046 is rejected without validation.


## H047 — The bulk print versus a fixed D+1 pre-close price predicts an overnight move

Status: **DATA ACQUISITION REGISTERED — OUTCOME UNTESTED, 2026-08-23.** The
original coverage gate found the gap; a refreshed Breeze session now licenses
the bounded pull below. No 15:15 or D+2 outcome had been read when it was
frozen. `conditions-on` [[H044]] only as motivation.

**The claim.** At 15:15 IST on D+1, compare D's disclosed quantity-weighted
bulk print with the first executable market price at or after 15:15. Buy names
above the print and short names below it, then hold to D+2 open (primary) or
D+2 close (secondary). Because disclosure occurred after D's close, every
input is known before this entry. This is not the same test as H046: it asks
whether D+1's realised move persists overnight after sacrificing most of the
session to observe it.

**Coverage gate before outcomes.** The test requires point-in-time 15:15 prices
and executable entry observations for the broad `train` bulk-event universe,
available through `research_data`. First report symbol-event coverage without
joining a return. Do not score a convenient handful of large names, fetch a
post-hoc subset, or read intraday parquet directly. If broad historical minute
coverage is absent, stop as **DATA GAP** without testing an outcome.

**Frozen future test.** Once coverage exists, quarantine corporate actions,
use a same-session no-deal twin with the identical D-to-15:15 construction,
derive event terciles on `train`, pair by entry session, and report both the
event-minus-twin increment and standalone portfolios after 40 bps. The primary
direction is negative. Validation remains unopened until a train survivor has
a separate frozen dispatch.

### H047 coverage result — stopped before outcomes

The train event table contains **15,500 bulk symbol-events across 2,438
symbols**. `research_data.repository` exposes selected opening ticks but no
named broad full-session intraday dataset from which a 15:15 executable price
can be obtained. The normalized store contains only seven one-minute source
probe files, nowhere near an unbiased event-universe panel and not licensed as
a separate read path. Scorable coverage under the registered contract is
therefore zero. H047 remains untested rather than being estimated on a
convenient large-cap subset; no outcome partition was opened.

### H047 bounded acquisition and train test — registered before the pull

**Primary universe.** Reuse H046's clean 1-crore D-day liquidity population:
all bulk symbol-events whose disclosure is tradable at D+1 open, with the same
factor/reconciled-action quarantine. This is the liquid primary that H046 was
required to pass; the lower-liquidity rows are not substituted here. The 10%
premium cap is a reported sensitivity, not a replacement primary.

**One control per event, selected without D+1 information.** For every event,
choose one no-bulk-deal name from D, without replacement inside the session
where possible, matched on D-known quintiles of trailing 20-session volatility,
20-session median turnover and D volume surprise. Exact-stratum misses are
dropped, never filled from a neighbouring session. Selection is deterministic
with seed 47 and is frozen before any 15:15 bar or D+2 return is read. This is
the same-session matched-control logic already used by the bulk family, bounded
to roughly one API call per event rather than an impossible all-stock pull.

**Fetched observation and benchmark.** Request only 15:15:00–15:17:00 IST on
D+1 from Breeze v2 `1minute`; use the open of the earliest valid bar stamped at
or after 15:15 and no later than 15:16:59. Fetch NIFTY over the identical window
once per entry session for the market-relative economic result. Missing and
unmappable rows remain missing; do not replace them after seeing an outcome.
The call manifest, normalized bars and mapping failures are retained through
`research_data`.

**Price-space quarantine added from the first ten label-free calls.** Breeze's
historical minute series sometimes matches NSE raw prices and sometimes carries
later split/bonus adjustments, including ratios absent from the current tape's
factor column. Do not infer a conversion from a later return. A 15:15 bar is
usable only when its open lies inside the same session's raw NSE low/high
envelope with a 2% quote tolerance; otherwise mark it unit-inconsistent and
missing. The registered 70% coverage floor is applied after this quarantine.

**Frozen score.** Feature is
`100 * (all_deal_vwap_D / price_1515_D+1 - 1)`; the control analogue uses
`vwap_raw_D` in place of the deal print. Event train terciles are applied
unchanged to both arms. Primary outcome is 15:15 D+1→D+2 open; D+2 close is
secondary. Pair the top-minus-bottom increment by entry session and report the
lag-zero DK t. Economic arms are judged on NIFTY-excess return after 40 bps.
Survival requires the primary 1-crore increment to be negative with `t <= -2`,
the sign to survive the 10% cap, at least 70% event and control feature coverage
over at least 300 independent entry sessions, and at least one primary tradable
arm positive in excess return after cost. Otherwise reject on train. Validation,
test and forward remain closed.


## H048 — Diminishing price impact during high-delivery declines predicts a five-day reversal

Status: **WITHDRAWN BEFORE OUTCOME — INVALID E0/CONTRACT, 2026-08-24.**
`conditions-on` [[H039]] and is adjacent to [[H030]] and [[H019]]. No forward
return was constructed and no sample budget was spent.

**The claim.** Among point-in-time NSE EQ-series names with trailing median
turnover of INR 3–30 crore, a two-to-four-session sequence of high-delivery down
days with diminishing negative price impact, followed by a positive close,
predicts positive market-adjusted return from the next open through five
sessions later. The delivery field measures activity delivered into settlement;
it does not identify the seller or prove institutional liquidation.

**Frozen intended comparison.** Candidate cases must beat an executable,
outcome-blind short-horizon reversal baseline at the identical daily take rate.
The primary bar is at least 80 bps of candidate-minus-baseline gross lift with
overlap-corrected `t >= 2.5`, while the selected market-excess return must remain
positive after the registered round trip. Circuit/price-band cases and
unexecutable next opens are natural falsifiers, not rows to retain.

**Why the first contract was withdrawn unopened.** Qualification
`QUAL_20260824_001427_671408` and contract
`EC_20260824_001427_715928` froze a source that encoded non-candidates as zero.
The E0 structural gate therefore counted 1,513,342 panel rows as cases rather
than the actual 3,248 positive cases, reported 2,020 cases per session, and
approved a minimum detectable effect of 181.2 bps despite the 80-bps target.
The source also did not implement the dossier's stated ratio-based impact
measure, price-band falsifier, or residualized baseline. Finally, the contract
would have evaluated close-entry raw returns and a generic backtest instead of
the registered next-open market-excess, take-rate-matched comparison. Those are
design defects visible without outcomes, so the immutable contract is preserved
and permanently marked `withdrawn_unopened`.

**Next valid test.** Re-qualify H048 under the corrected selector contract:
non-candidates are `NaN`, the structural gate prices the actual active case set
against the 80-bps target, every material dissent has an explicit implemented
resolution, and both signal and baseline source are hashed into a version-3
contract. This remains H048 rather than a new hypothesis because no outcome was
opened and the economic claim has not changed.


## H049 — Among NSE cash equities with point-in-time 20-day median turnover of INR 3-25 crore, a 2-5 session delivered selloff is more likely to reverse over the next five sessions when the following gap-down morning fails to extend lower during the opening window despite active trading. The minimum bootstrap test enters only after this intraday rejection is observable and makes no claim that delivery percentage identifies the seller.

Status: **PROPOSED — OUTCOME UNTESTED, 2026-08-24.** Registered by the research director before outcome access.

**Population.** NSE cash equities in the regular EQ series, excluding ETFs, selected separately on every signal date using point-in-time median_tv_20_cr between INR 3 crore and INR 25 crore. Require median_vol_20 sufficient for an INR 1-2 lakh position to remain at or below 2% of median daily traded value, and exclude observations with missing delivery data, corporate-action adjustment discontinuities, or an indicated round-trip cost above 40 bps. Do not use current index membership, current market capitalization, sector, or size_tier for universe construction.

**Mechanism.** A provisional interpretation is that a multi-session urgency seller has reached the terminal part of an execution program. The gap-down invites or reflects residual supply, but the inability to push price materially below the open while meaningful volume trades indicates that available demand is absorbing it. The predictive claim is only that this joint state has a favorable conditional return distribution; the catalogue cannot establish seller identity, order parentage, or institutional participation. Counterparty: The proposed profitable side is a small patient buyer entering after the opening rejection is observable. The economically conceding side is an urgency-constrained holder completing a multi-session sale. Its identity and institutional status are not observable in the supplied catalogue and are not required for the minimum predictive test.

**Frozen economic bar.** 80.0 bps. Strongest baseline: A cross-sectional, date-clustered comparison against the same fixed-time opening-rejection rule without the preceding delivered-selloff condition. Estimate the incremental five-day return using matched or weighted controls on gap_pct, preceding 5-day return, atr_pct, median_tv_20_cr, opening vol_rel_daily_pct, range_pos, market regime, and entry-time return from the open. Also compare with a plain recent-loser reversal rule that ignores opening behavior. Use purged walk-forward evaluation, date-level resampling, and one observation per symbol per overlapping five-session holding window.

**Lineage.** Nearest prior hypotheses: H048, H010, H011, H039.


## H050 — Among NSE cash equities with point-in-time 20-day median turnover of INR 3-25 crore, a 2-5 session delivered selloff is more likely to reverse over the next five sessions when the following gap-down morning fails to extend lower during the opening window despite active trading. The minimum bootstrap test enters only after this intraday rejection is observable and makes no claim that delivery percentage identifies the seller.

Status: **SUPERSEDED — DUPLICATE OF H049, OUTCOME UNTESTED, 2026-08-24.** A retry race in provisional promotion allocated a second ID before outcome access. H049 is the canonical record; no evidence or sample exposure is attached to H050.

**Population.** NSE cash equities in the regular EQ series, excluding ETFs, selected separately on every signal date using point-in-time median_tv_20_cr between INR 3 crore and INR 25 crore. Require median_vol_20 sufficient for an INR 1-2 lakh position to remain at or below 2% of median daily traded value, and exclude observations with missing delivery data, corporate-action adjustment discontinuities, or an indicated round-trip cost above 40 bps. Do not use current index membership, current market capitalization, sector, or size_tier for universe construction.

**Mechanism.** A provisional interpretation is that a multi-session urgency seller has reached the terminal part of an execution program. The gap-down invites or reflects residual supply, but the inability to push price materially below the open while meaningful volume trades indicates that available demand is absorbing it. The predictive claim is only that this joint state has a favorable conditional return distribution; the catalogue cannot establish seller identity, order parentage, or institutional participation. Counterparty: The proposed profitable side is a small patient buyer entering after the opening rejection is observable. The economically conceding side is an urgency-constrained holder completing a multi-session sale. Its identity and institutional status are not observable in the supplied catalogue and are not required for the minimum predictive test.

**Frozen economic bar.** 80.0 bps. Strongest baseline: A cross-sectional, date-clustered comparison against the same fixed-time opening-rejection rule without the preceding delivered-selloff condition. Estimate the incremental five-day return using matched or weighted controls on gap_pct, preceding 5-day return, atr_pct, median_tv_20_cr, opening vol_rel_daily_pct, range_pos, market regime, and entry-time return from the open. Also compare with a plain recent-loser reversal rule that ignores opening behavior. Use purged walk-forward evaluation, date-level resampling, and one observation per symbol per overlapping five-session holding window.

**Lineage.** Subsumed by H049. Nearest prior hypotheses: H048, H010, H011, H039.


## H051 — Among NSE cash equities with point-in-time 20-day median turnover of INR 3-20 crore, stocks experiencing a stock-specific 2-5 day decline before a scheduled exchange closure of at least three calendar days will, on average, partially reverse over the first five trading days after reopening when the final pre-closure session shows elevated turnover but no new closing low relative to its intraday low. The predictive claim is limited to a conditional post-closure reversal and does not assert that the observed selling came from institutions, leveraged traders, or any identifiable trade class.

Status: **PROPOSED — OUTCOME UNTESTED, 2026-08-24.** Registered by the research director before outcome access.

**Population.** NSE cash equities in ordinary tradable series, excluding ETFs, selected each day using only point-in-time median_tv_20_cr between INR 3 crore and INR 20 crore. At entry, require the intended position to be no more than 2% of the stock's point-in-time 20-day median daily turnover and no more than 10% of the entry day's observed turnover. Candidate events occur immediately before a scheduled NSE closure spanning at least three calendar days. Require a negative 5-day stock return, negative 5-day excess return versus the market, final-session turnover above 1.25 times its 20-day median, and a close in the upper half of the final session's range. Exclude observations lacking valid adjusted prices or delivery data and avoid survivorship filters based on current index membership, market capitalization, sector, or listing status.

**Mechanism.** A plausible interpretation is that some holders reduce positions before a period in which they cannot react to news, margin changes, or financing needs. This precautionary supply can be disproportionately costly in moderately liquid stocks. A strong close after elevated pre-closure turnover is treated only as a candidate exhaustion footprint: urgent supply may have been absorbed before the market shut. The observable pattern does not identify the seller, leverage, institutional ownership, or a parent order. Counterparty: The economically conceding side is a heterogeneous set of holders who prefer lower unadjustable exposure over a scheduled closure, potentially including leveraged retail traders, broker-financed accounts, short-horizon proprietary traders, and inventory-constrained intermediaries. Their identities and trade classes are not observable and are not required for the predictive test. The proposed profitable side is a small, patient cash buyer entering near the final pre-closure close or the first liquid opportunity after reopening.

**Frozen economic bar.** 80.0 bps. Strongest baseline: Within the same point-in-time liquidity universe, rank stocks solely by five-day market-excess return and buy the worst decile for five trading days, with identical entry timing, position limits, cost assumptions, and calendar exclusions. The proposed mechanism must improve out-of-sample net return or cross-sectional rank information over this plain short-term-reversal baseline. A secondary calendar baseline is the same loser-reversal rule on matched non-closure sessions with the same weekday, month, market regime, volatility, turnover, and liquidity distributions.

**Lineage.** Nearest prior hypotheses: H039, H048, H049, H050.


## H052 — Among NSE EQ-series equities with point-in-time 20-day median turnover of INR 3-20 crore, after a scheduled market-wide closure of at least three calendar days, stocks that rise on the first reopening session but capture less than half of a broad-market gain of at least 1.5% will, on average, partially catch up over the next five sessions. The signal is fixed after the reopening close and entered at the following session's open; it is a modest predictive underreaction claim, not evidence that any particular investor class caused the lag.

Status: **PROPOSED — OUTCOME UNTESTED, 2026-08-24.** Registered by the research director before outcome access.

**Population.** NSE cash equities in the EQ series, selected independently on each signal date using median_tv_20_cr between 3 and 20, at least 60 prior valid daily observations, a non-missing reopening-session open and close, and no mechanically suspect unadjusted price discontinuity. Market closures are identified point-in-time from gaps in the common NSE trading-date sequence, not from a current index, market-cap, or constituent snapshot. The primary test is long-only and requires a positive reopening-session stock return between 0% and 50% of a broad-market reopening gain of at least 1.5%.

**Mechanism.** A broad positive repricing after a closure may reach moderately liquid, less-attended equities incompletely during the first reopening session. Conditional continuation would be consistent with delayed price discovery caused by limited investor attention, stale orders, and cautious liquidity provision. These mechanisms are interpretations only; the minimum test establishes neither investor identity nor order type. Counterparty: The economically conceding side is a mixture of reopening-session sellers, stale limit-order suppliers, attention-constrained holders, and inventory-cautious intermediaries in moderately liquid equities. Their identities are unobserved and are not required for the predictive test. The profitable side is a small cash buyer entering at the next session's open after the reopening lag has been measured.

**Frozen economic bar.** 80.0 bps. Strongest baseline: A cross-sectional residual-continuation baseline: rank the eligible universe by reopening-session stock return minus its rolling 60-session beta times the reopening market return, then test the lowest positive-residual-response bucket against the universe and against matched controls with similar median_tv_20_cr, rolling beta, prior 20-day return, ATR percentage, and reopening gap. The mechanism must add value beyond an otherwise identical residual-laggard rule run on every ordinary trading session with a market gain of at least 1.5%.

**Lineage.** Nearest prior hypotheses: H051, H040, H030.


## H053 — Among NSE cash equities with point-in-time 20-day median turnover of INR 3-20 crore, recent idiosyncratic losers experience a modest five-session rebound when they suffer additional weakness during the final three trading sessions of a calendar quarter, especially when quarter-end turnover is elevated but the final session closes materially above its low. The minimum test buys at the final quarter-end close, or at the next session's open in a timing-robustness variant, and does not claim that observable price and volume identify institutional window dressing.

Status: **PROPOSED — OUTCOME UNTESTED, 2026-08-24.** Registered by the research director before outcome access.

**Population.** NSE EQ-series, non-ETF cash equities selected independently on each signal date using point-in-time median_tv_20_cr between INR 3 crore and INR 20 crore. Require at least 20 prior sessions, a valid unadjusted tradable price, and no zero-volume signal session. Define recent losers using bottom-quintile 20-session market-relative return within the eligible point-in-time liquidity universe. Do not use present-day index membership, market capitalization, sector, size_tier, or survivorship-conditioned symbol lists.

**Mechanism.** A plausible interpretation is temporary quarter-end disposal of embarrassing or risk-intensive losing positions, followed by partial recovery after the reporting or risk deadline passes. This causal account is not identified by daily OHLCV or delivery percentage. The defensible bootstrap claim is only that the calendar-conditioned loser rebound is incrementally predictable after controlling for ordinary short-term reversal, liquidity, volatility, and market state. Counterparty: The economically conceding side is hypothesized to include benchmarked or reporting-sensitive asset managers, proprietary books facing quarter-end risk limits, broker-financed accounts reducing collateral usage, and other holders with quarter-end balance-sheet or presentation constraints. Their identities are unobserved and are not required for the predictive test. The profitable side is a small cash buyer able to absorb INR 0.5-2 lakh per name without demanding institutional capacity.

**Frozen economic bar.** 80.0 bps. Strongest baseline: A cross-sectional five-day loser-reversal model estimated on the same point-in-time liquidity universe: predict fwd_ret_5d_pct or excess_ret_5d_pct from continuous rs_20d_vs_mkt, the last three-session return reconstructed from PIT prices, atr_pct, median_tv_20_cr, signal-day turnover multiple, close location within the daily range, mkt_ret_20d, and mkt_vol_20d. The mechanism earns consideration only if a pre-specified quarter-end interaction adds out-of-sample return beyond this baseline. Also compare directly with matched non-quarter-end losers from the same calendar year, liquidity decile, volatility decile, market regime, and prior-return decile.

**Lineage.** Nearest prior hypotheses: H051, H030, H048.


## H054 — Among NSE cash equities with point-in-time 20-day median turnover of INR 3-20 crore, Friday-specific selling pressure is followed by a modest three-session reversal when the stock closes in the bottom 20% of Friday's range on turnover at least 1.5 times its trailing median, but Monday opens no more than 30 bps below Friday's close. The predictive claim is that Monday's absence of further markdown identifies exhausted weekend-risk supply; it does not identify the sellers or prove that their trades were forced.

Status: **PROPOSED — OUTCOME UNTESTED, 2026-08-24.** Registered by the research director before outcome access.

**Population.** NSE cash equities in ordinary equity series, excluding ETFs, selected each session using only point-in-time information: median 20-day traded value between INR 3 crore and INR 20 crore, at least 15 valid trading observations in the preceding 20 sessions, Friday turnover and OHLC observations available, and a valid following-session open. Present-day index membership, market capitalization, sector, and size-tier labels must not define the universe.

**Mechanism.** A weekend creates a recurring period during which cash-equity holders cannot adjust positions while company, macroeconomic, geopolitical, and margin-related news can arrive. Some short-horizon or financed holders therefore pay a small premium to reduce awkward exposure before Friday's close. In moderately liquid names, that supply can move the close. If Monday's opening auction does not require another material markdown, the weekend-risk concession was probably temporary and can partially unwind. This causal interpretation is provisional; the minimum test establishes only a conditional Friday-to-Monday relationship. Counterparty: The economically conceding side is a heterogeneous group of holders who value lower weekend exposure, potentially including leveraged retail accounts, broker-financed clients, short-horizon proprietary traders, and inventory-limited intermediaries. Seller identity is not observable and is not required. The proposed profitable side is a small cash buyer entering at Monday's observable open.

**Frozen economic bar.** 80.0 bps. Strongest baseline: The strongest simple baseline is the identical high-turnover, negative-return, bottom-20%-of-range selloff followed by a next-session open no more than 30 bps below the prior close, estimated on Monday-through-Thursday signal sessions. Compare Friday and non-Friday cases within turnover deciles, Friday-return bins, ATR-ratio bins, market-regime bins, and calendar blocks. Also compare against an unconditional Friday effect in the same point-in-time liquidity universe.

**Lineage.** Nearest prior hypotheses: H051, H039, H048, H049.

## H055 — Causal, contextual price action on NSE equities

Status: **PROPOSED — OUTCOME UNTESTED, 2026-08-24.** Registered by the research director before outcome access.

**Population.** NSE EQ cash equities, ETFs excluded; initial 20-session median traded-value band of ₹3–25 crore.

**Mechanism.** Traders may react to remembered price regions; causal representation of those regions may contain information; context may determine which interactions matter; and an AI may be better at that contextual selection than one fixed score.

**Frozen economic bar.** 80.0 bps gross per taken trade, positive after the 40 bp round-trip cost floor. Strongest baseline: the full coded zone score without the AI.

**Lineage.** Nearest prior hypotheses: H033, H037, H047.

**Implementation audit, 2026-08-24.** The first PA0–PA12 implementation pass
created simulated workers, constant features and cases, and hand-written JSON
files claiming that source, E0, E1, E2, validation, and forward stages had
passed. It made no real source requests, constructed no real cases, and opened
no outcomes. Those files are invalid scaffolding, not evidence, and have been
removed. H055 therefore remains **PROPOSED — OUTCOME UNTESTED**. Its first valid
stage must enter through the research-director lifecycle and earn each gate in
order.

**Current pre-outcome state, 2026-08-24.** The real source microprobe and
point-in-time identity preflight are recorded in FINDINGS.md. After the Breeze
session was refreshed, all 250 v3 bootstrap requests ran, but its collector
rejected 241 whole responses merely because Breeze included non-regular
pre-open, terminal-close, or special-session records. v3 is failed-ingestion
provenance, not a dataset. The corrected v4 contract preserves those records
separately, excludes them from decisions, and gates on explicit requested-
session coverage. v4 completed and verified 97.6667% requested-session
coverage with no hard source failures. The outcome-free E0 source, identity,
capacity and useful-effect-power gates pass. Its first annotation bundle was
invalidated before use because it exposed the coded zone; the replacement is
blind, frozen and unannotated, so representation remains blocked. The real dossier
`DOS_MARK_40127F9C04` has only deterministic criticism; it is explicitly
diagnostic and cannot qualify until an independent provider attack (or a
recorded owner waiver) exists. PA4 source admission is complete; representation,
shape, directional, validation and forward claims remain unpassed, and no
outcome has been opened.

**Representation update, 2026-08-25.** Both frozen blind model annotation
passes are complete on all 60 cases (`gpt-5.6-luna`: two recorded failed calls;
`gpt-5.6-terra`: none). A generic outcome-locked setup-review page now guides
the human observer, supports click-to-place ATR-normalised levels, checkpoints
drafts, freezes only a complete pass, and reveals model explanations only after
that freeze. Representation remains blocked pending the human pass; no outcome
has been opened and no alpha claim exists.

**PA7 representation result, 2026-08-25.** The frozen human pass completed all
60 cases, making the annotation design complete. The representation gate
failed materially: median composite kappa 0.0868 versus 0.40 required and
median centre disagreement 1.52 ATR versus 0.50 allowed. Human–model agreement
is near zero and model–model agreement also misses the composite bar. This
rejects the present claim that the coded cases, prompt and judges share one
support/resistance concept; it does not reject price action or measure alpha.
H055 remains outcome-untested and E1 is blocked pending an outcome-free
disagreement audit and a genuinely redesigned representation, not parameter
tuning on returns.


## H056 — Machine-discovered retest geometry transfers across markets and time

Status: **PROPOSED — OUTCOME UNTESTED, 2026-08-25.** Registered before any
H056 directional outcome access. H055's failed human-representation gate is
preserved and is not reinterpreted as evidence for or against this hypothesis.

**Question.** Can a machine learn a selective, causal representation of
support/resistance *role-reversal retests* whose entries and exits transfer
across markets and chronological blocks, without requiring its levels to agree
with a human's drawings?

**Population and development data.** The first executable population remains
point-in-time NSE EQ cash equities with ETFs excluded and the declared lagged
liquidity/capacity rules. Old NSE partitions and separately contracted foreign
cash-equity markets may be used repeatedly for development. Every partition or
market consulted during representation, feature, threshold, model, entry,
stop, target, abstention or exit refinement is thereafter labelled
**development**, never validation. Development uses nested walk-forward folds
and leave-one-market-out evaluation. The final estimate is one frozen read of
an NSE test/forward interval untouched by H056 and all descendants. Bearish
setups may be studied on cash prices, but are not an executable short strategy
without a PIT futures/borrow contract.

**Manual priors, frozen before outcomes.** Candidate trades are only completed
role reversals: resistance broken and later retested from above for a long, or
support broken and later retested from below for a short. The breakout bar is
never the retest. The first development configuration requires at least three
completed five-minute bar intervals from the break close to the retest close,
at least twelve completed bars from zone confirmation to break, and a completed
retest close back on the
new-role side. Trend must agree on completed higher-timeframe bars: the initial
context is a 60-minute 20/50 EMA stack with the fast EMA sloping in the trade
direction. A completed close through the far edge of the flipped zone
invalidates it; repeated penetration and cumulative bleed remain continuous
features, and the selector may abstain rather than rationalise them.

The entry is the next genuinely available five-minute open after the completed
retest decision. The structural stop is beyond the far edge of the retested
zone plus a frozen volatility buffer. The preferred target is the nearest
already-known significant opposing zone; no future-created level may supply a
target. The initial candidate is rejected when that target offers less than
1.5 units of structural reward per unit of risk or less than 80 bps gross
distance. Time exits are an explicit development dimension, initially 6, 12
and 24 completed five-minute bars without minimum favourable progress; no
retrospective manual cut is permitted. Costs, gap-through-stop execution and
unavailable entries are retained.

**Learning claim.** AI may aggressively propose geometry, features and models
inside the development corpus. Each proposal and outcome read is logged in one
lineage/multiplicity batch. The search objective rewards after-cost excess bps,
calibration, abstention stability and worst-market/worst-era performance, not
training fit or trade count. A setup family is eligible to freeze only if it
adds value over retest-only, EMA-only, fixed pivot-zone and same-take-rate
walk-forward baselines and does not depend on one market.

**Frozen economic bar.** Before the final NSE read, the surviving system must
declare its take rule, position sizing, entry, structural stop, target, time
cut, cost model and maximum concurrency. The final bar is positive after the
40-bp round-trip floor, at least 80 bps gross excess per taken trade, positive
lift over the strongest eligible baseline at the same take rate, and no hidden
leverage from overlapping cohorts. The exact retention and minimum-trade bars
will be compiled from development estimates before the final partition opens.

**What would falsify it.** Failure includes: no stable retest population after
the manual priors; apparent lift that disappears against pseudo-levels or
trend-only controls; dependence on one exchange/era; targets too close to pay
costs; excessive abstention that leaves no independent blocks; or failure of
the once-only untouched NSE estimate.

**Lineage.** `adjacent-to` H055 (same price-action programme, different
representation claim); `specialises` the role-reversal portion of H055. H055's
PA7 failure remains final for its frozen human/coded representation.

**Outcome-free kickoff, 2026-08-25.** The first causal implementation and
bootstrap density report are recorded in FINDINGS.md. The selective prior finds
16 eligible retests in the small H055 bootstrap, too few to open outcomes. A
full old-NSE development manifest is frozen over train plus the former
validation partition; test and forward remain excluded. It is staged on
`hp-ts` but awaits the ordinary daily Breeze session refresh before its
resumable pull can start. No H056 outcome has been opened.


## H057 — Levels interrupt the path more than matched fake levels do

Status: **REJECTED at the frozen bar, 2026-08-25.** Registered before any
H057 reaction statistic was computed on real data; the registration is
timestamped in git at `d421f6c`, before the read. The frozen bar below was fixed
before the study ran and is preserved verbatim.

**Result.** On 13,860,800 five-minute bars across 302 symbols and 1,081 sessions
of the point-in-time stock-futures universe, no detector clears the bar at the
primary cell. Largest primary contrast is `fractal` at +0.0034 (t=+6.23) against
a required +0.02; the most positive cell anywhere in the 72-cell grid is
`volume_profile` at +0.0120 with t=1.95. `anchor` — the canonical
prior-session/prior-week/opening-range/round-number levels, the ones a trader
actually draws — is **negative in all 18 of its cells**, reaching -0.0201 at
t=-16.97: price penetrates the most-watched prices more readily than a matched
fake price at the same distance. Median session ATR is 283 bps, so the observed
effects are worth roughly 1-3 bps per resolved race against a 6-10 bps futures
round trip; even the bar itself implied only 5.66 bps, as the registration
stated. Full report and limits in FINDINGS.md; machine-readable at
`data/metadata/research_store/price_action/h057_reaction_study.json`.

This is not an underpowered null — with 1,081 independent sessions a +0.02 effect
would have been unmissable. The failure is located in the representation, not in
coverage, power or costs. H056 does not resume on this representation. The
inverted `anchor` effect is a direction read off a registered statistic whose
falsification clause contemplated it, so reporting it is in bounds; **trading it
is a new hypothesis with its own multiplicity burden and is not opened here.**

**Why this supersedes the H056 configuration.** H056 asked whether machine-
discovered role-reversal geometry predicts executable outcomes. Two facts
retired its configuration without retiring the idea:

1. *The universe was not tradable by this account.* The manifest screened NSE
   cash equities in a ₹3-25 crore lagged-turnover band. The owner is an NRI and
   therefore cannot square off intraday in the cash segment and cannot short
   cash equities at all, so an intraday or bearish claim is executable only in
   F&O. NSE's stock-futures eligibility floor sits far above ₹25 crore, so the
   two universes barely intersect. The H056 pull was stopped at 9,526 of 53,303
   requests and is retained as cash-delivery research data, not as H057
   provenance.
2. *The detector was measuring its own density.* `causal_zones` seeded levels
   from 2-left/2-right five-minute fractals. That fires every few bars, which
   explains both the PA7 annotation failure (composite kappa 0.087, centre
   disagreement 1.52 ATR — the owner drew distant, older levels; the machine
   drew micro-pivots) and the 3,222 → 16 structural funnel, whose dominant
   rejections were `target_room` (2,943) and `reward_risk` (2,890). With a level
   every few bars the nearest opposing level is a fraction of an ATR away, so a
   structural target can never clear 80 bps. Neither number was a fact about the
   market.

**Population.** Point-in-time NSE stock-futures membership, reconstructed from
each session's own derivatives bhavcopy: a symbol was in the universe on a
session if and only if a `stock_future` row for it appears in that session's
file. 305 distinct symbols over 2020-2026, 140-216 live per session, of which
only 102 are present throughout — the churn is real and a present-day F&O list
cannot reconstruct it. Lagged liquidity floors are declared in
`fo_universe.UniverseConfig`. Levels are drawn on the continuous cash series;
execution, costs and capacity come from the futures series.

**Question.** When price arrives at a level, does it turn back before it
carries on *more often than it does at a matched fake level*? Nothing about
direction, payoff or profitability is asked. This is the necessary condition
that every later claim in this programme depends on, and it is the cheapest
thing that can falsify the whole mechanism.

**Why this question and not a directional one.** Price reacts everywhere, so a
procedure that draws a line and looks for reactions at it cannot fail and
therefore carries no information. The only informative measurement is against
lines that are not levels. Two controls are used, both paired inside the same
symbol-session:

- `random_price` — centres drawn uniformly within the ATR band the real levels
  of that symbol-session occupy. Answers "is a level better than any price?"
- `permuted_geometry` — the real level *offsets* from a different randomly
  chosen symbol-session, replayed here. Distance-from-reference, width and
  volatility scaling are preserved; only the link to this symbol's own history
  is broken. This is the pseudo-zone PLAN.md §9 requires and it is the control
  that can kill the hypothesis.

A global effect is absorbed by both controls by construction. That is
deliberate: a claim that survives here has to be local to a price.

**Statistic, frozen.** For each first-touch of a knowable level on a completed
hourly bar, race two symmetric barriers on the five-minute path from the touch
bar's close: `rejection` at `barrier × lagged session ATR` back the way price
came, `penetration` at the same distance onward. First barrier touched wins;
unresolved races are reported but excluded from the rate. The primary cell is
**barrier 0.50 ATR, horizon 24 five-minute bars, control `permuted_geometry`**.
The declared grid is 4 detectors × 2 controls × barriers {0.35, 0.50, 0.75} ×
horizons {12, 24, 48}; the reported result is the maximum over that grid judged
against a session-level sign-flip permutation maximum. The independent unit is
the session.

**Detectors, declared before the read.** `fractal` (the incumbent, expected to
lose and retained only as a baseline), `anchor` (prior-session high/low/close,
prior-week high/low, opening range, round numbers), `volume_profile` (high- and
low-volume nodes from a trailing causal volume-at-price histogram), and
`multi_touch` (prices that several distinct completed sessions turned at). The
last three are timeframe-portable by construction and the first is not; that
difference is asserted as a test, not as an opinion.

**Frozen bar.** The mechanism survives to E2 only if the primary cell shows a
mean paired contrast of **at least +0.02** in rejection rate with a
session-clustered **t ≥ 3.0**, and the grid maximum clears a permutation
**p ≤ 0.05**. Anything less retires level geometry as this programme's
representation.

**What passing does and does not mean.** Passing is necessary, not sufficient,
and it is explicitly *not* evidence of tradability. At a 0.50 ATR barrier and a
session ATR near 2% of price, a contrast of +0.02 implies roughly 4 bps of
expected edge per resolved race against a futures round trip near 8-10 bps. A
result at the bar therefore says information exists but is too diffuse to trade
as an average, and the open question becomes whether selection concentrates it.
A result far above the bar is what a tradable version would look like. Reporting
the implied economics beside the contrast is required so that a statistically
clean 2-point effect is never mistaken for money.

**What would falsify it.** Contrast at or below zero against `permuted_geometry`;
an effect that exists only against `random_price` and vanishes against the
matched control; an effect carried by one detector that no other detector
reproduces; an effect that does not survive the permutation maximum; or too few
resolved races to estimate anything.

**Exposure.** This reads the future five-minute path on development partitions
(train and validation) and is logged sample exposure, not an outcome-free
preflight. It reads no sign, no directional hit rate and no payoff. Test and
forward are excluded from the manifest and remain untouched.

**Lineage.** `specialises` H056's representation question; `adjacent-to` H055.
H055's PA7 representation failure stands. H056 remains outcome-untested and its
manual retest priors are unchanged — H057 tests the layer beneath them.

**Blind representation audit, registered 2026-08-26, COMPLETE — the rejection stands.** A null result on
a representation is worth what the representation is worth, so the objects H057
scored are being audited against the reviewer's own eye before the rejection is
treated as settled. `h057-level-audit` is a balanced 60-case deck — 30 real
detector levels, 30 of the exact `permuted_geometry` controls — shown blind on
anonymised, rebased, 140-bar hourly charts ending at the decision bar. The
reviewer marks each line real or control, and separately whether they would
trade it. Chance is exactly 50% by construction and ground truth is withheld
until a complete pass is frozen.

The audit's own bar, fixed before it is scored: a discrimination rate whose
95% interval excludes 0.5 means the controls are matched on the wrong things or
the detectors miss what a human uses, and **H057's rejection is then about the
wrong object and is withdrawn pending a redesigned representation**. A rate whose
interval covers 0.5 means the machine's levels and the reviewer's are the same
object on exactly the scored cases, and the rejection stands as an answer to the
intended question. The take rate is read alongside it: a reviewer who skips
nearly every case is reporting that the candidate population is not the setup
population, which is a separate defect. This spends no new sample — H057's path
exposure is already logged and its cases are re-rendered from that read.

**Audit result, 2026-08-26.** The owner completed and froze all 60 cases.
Discrimination is **0.533 (SE 0.064, z = 0.52)** — a 95% interval of
[0.41, 0.66] that covers chance. Accuracy was 0.567 on real levels and 0.500 on
controls, mean stated confidence 0.47 with a maximum of 0.80. **The controls are
not distinguishable from the real levels, so H057's rejection stands as an
answer to the intended question** at the unconditional level.

The take rate is the sharper number: **10 of 60 taken (16.7%), split exactly
5 real and 5 control**, giving an identical 16.7% take rate on each deck.
Whatever made those ten charts tradable to the owner, it was not the drawn line.
Free-text notes say the same thing directly — "line is just drawn through stuff,
nothing to trade", "not clear enough levels". So the audit simultaneously
upholds the null *and* confirms that H057's candidate population is not the
owner's setup population: the study answered a question about charts he would
never trade. H057's scope narrows accordingly and its limitation 4 — no
selection — is now the live question rather than a caveat.

One non-result worth recording so it is not rediscovered as a finding: on real
cases only, recognition ran `anchor` 0.714 and `multi_touch` 0.714 against
`fractal` 0.444 and `volume_profile` 0.429. That ordering is consistent with the
owner's notion of a level being prior-session and multi-day structure rather
than bar patterns or volume nodes, but each cell holds 7-9 cases (SE ≈ 0.17,
z ≈ 1.25). It is a direction for a redesigned representation, not evidence.


## H058 — The owner's own selection carries information the machine's does not

Status: **REGISTERED, Stage 0 open, no outcome touched.** The Stage 0
acceptance bar and the Stage 2 execution rules below were both fixed before the
reviewer saw a single chart; they are timestamped in git and frozen inside
`data/metadata/research_store/price_action/h058_stage0/manifest.json`.

**Where this came from.** H057's blind audit settled one thing and opened
another. The reviewer could not separate real levels from matched controls
(0.533, 95% interval [0.41, 0.66]), so H057's null answers the question it
asked. But he would have traded 10 of 60 charts, split exactly 5 real and 5
control — an identical 16.7% on each deck. The study therefore measured a
population he would never touch, and H057's fourth limitation, that it averages
over every approach and cannot see a selected subset, stopped being a caveat.
This hypothesis lets the reviewer define the population instead of slicing it.

**Question.** On charts he chose himself, from a deck he did not construct, does
what he takes outperform what he passes over on the same sessions — and does it
beat costs at the geometry he specified?

**Two contrasts, one grind.** *Selection*: mean outcome on takes minus skips,
paired inside the same sessions and the same universe. The skips are a perfectly
matched control that costs nothing to collect, which is exactly what H057 had to
synthesise. *Tradability*: mean R on takes against a 10 bps futures round trip.
The first can pass while the second fails, and that difference is informative
rather than awkward.

**Why the deck is served and not scrolled.** Free chart-scrubbing cannot produce
evidence here, for three reasons and any one is fatal. The right-hand side of
the chart is read before the reviewer knows he has read it. There is no
denominator, so the take rate and the skip control — the most informative number
the audit produced — are unrecoverable. And nobody, including the reviewer next
month, can rerun it.

**Population.** Point-in-time NSE stock-futures membership on session D, daily
bars, decision at D's close. 140 daily bars per chart, anonymised and rebased so
the last close is 100. Stage 0 draws from `validation`; `test` is untouched and
reserved for the single Stage 2 read.

**Stage 2 execution rules, frozen now so they cannot be authored after the
marks are in.** Entry is the clicked level, live for 3 sessions from D+1: above
the last close it triggers on `high >= entry` (breakout), below it on
`low <= entry` (pullback). No trigger in 3 sessions is a recorded no-fill, not a
silent drop. Exit is the first of stop, target, or the close of the 15th session
after fill; when one session touches both barriers the stop is taken. Outcome is
the R multiple net of 10 bps, where 1R is entry minus stop. Total horizon is 18
sessions, inside split_v1's `max_horizon` of 20 — a longer hold would cross a
purge boundary the split was never purged for.

**Direction is not asked.** The reviewer clicks entry, stop and target; a stop
below the entry is a long and above it a short. That removes a field from every
take and turns the pairing invariant into something checked rather than trusted,
in both the browser and the server. This lab has met a stop on the wrong side of
an entry before.

### Stage 0 — the cheapest thing that can end the programme

Two questions, no outcome, one evening. 170 charts: 120 distinct decisions, 50
of them shown a second time at least 60 charts later and drawn at 128 bars
rather than 140, so the second showing is the same decision on a differently
framed image.

1. **Does the reviewer agree with himself?** If test-retest agreement on
   take/skip is near chance, no downstream contrast can carry information and no
   deck size fixes it. PA7 recorded a composite kappa of 0.087 between his level
   markup and the machine's, so this is a live risk and not a formality.
2. **What does a data point cost?** The measured take rate and seconds per chart
   replace the assumed ones in the Stage 2 sizing table.

**Frozen bar.** Test-retest kappa **below 0.20 ends the programme**. **At or
above 0.40, Stage 2 opens at the full five-hour, 0.20R size.** Between them,
Stage 2 opens only at the two-hour, 0.30R size, because a noisy selector needs a
larger effect before the grind is worth it. Independently, a take rate under
0.05 makes the full grind unaffordable and one over 0.60 means the reviewer is
labelling rather than selecting; either sends the deck back to be redrawn rather
than opening outcomes.

Simulated at the deck's own size, 50 pairs and a 17% take rate: a reviewer who
is genuinely random is stopped 91% of the time and reads as full-proceed 1% of
the time, while one at a true kappa of 0.60 proceeds 87% of the time and is
wrongly stopped 1%. The gate separates "cannot reproduce at all" from
"reproduces well"; it cannot resolve the middle, which is why the middle has its
own verdict rather than a coin flip.

**Not gates, reported anyway.** Seconds per chart, used only for sizing. Geometry
agreement on charts taken twice — too few pairs to gate, but it is the sharper
question and worth seeing.

**What Stage 0 cannot tell us.** Whether the selection is any *good*. A perfectly
reproducible reviewer with no edge scores kappa 1.0 here. Consistency is
necessary and nowhere near sufficient, and passing Stage 0 is permission to
spend the grind, not evidence of anything about the market.

**Recall inflates the retest.** Different bar counts defeat pixel recognition,
not memory of a distinctive chart. The reported agreement is an upper bound and
is labelled as one everywhere it appears.

**Exposure.** Stage 0 reads no outcome and spends no sample. It draws from
`validation` so that `test` — 306 sessions across 2020Q2, 2022Q2, 2023Q4,
2025Q3 and 2026Q1 — stays whole for Stage 2, and so that any Stage 2 deck
enrichment is fitted on one partition and applied to another. Note that those
five quarters are five blocks: session-clustered significance is well supported,
"does it hold across regimes" is not.

**Lineage.** `specialises` the selection limitation of H057; `adjacent-to` H055
and H056. Neither H057's null nor H055's representation failure is disturbed by
this — both stand, and this tests the layer above them.
