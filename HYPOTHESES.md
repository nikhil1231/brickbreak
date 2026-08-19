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

Status: **INCONCLUSIVE** (not answerable with current data)

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

**Interpretation:**
Cannot be resolved. On the mornings that touched both, the outcome depends
entirely on **which came first**, and a daily bar does not record intraday
ordering. The bounds are wide enough that both a profitable and an unprofitable
answer sit inside them.

**Caveats:**
The stop touch rates are computed at the H001 entry and inherit its problems;
H005 shows a real entry would face a wider stop, which would lower them. Daily
MFE/MAE also cannot see intraday paths within a single session.

**Next step:**
This is now the **only** remaining justification for the full-session intraday
pull: resolving the ordering on the 6.49% of mornings where both levels were
touched. Everything else about the entry rules has been answered without it.
Decide whether that single question justifies the pull before committing.

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
