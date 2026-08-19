# HYPOTHESES.md — research ledger

Persistent record of every meaningful hypothesis this project has proposed,
tested, rejected or stumbled into. **Nothing is deleted.** A hypothesis that
failed is a result; a hypothesis invalidated by a modelling bug is marked
`SUPERSEDED` and kept, with the bug described, because the next person to have
the same idea needs to know it was already tried and why the answer did not
count.

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
