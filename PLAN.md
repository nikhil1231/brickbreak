# brickbreak — next steps (Phase 2)

Seed context for a fresh session. Repo: `/path/to/brickbreak`

## Where things stand

**Phase 0 (done)** — Breeze feasibility. Verdict GO. See `FINDINGS.md`.
**Phase 1 (done)** — point-in-time daily universe + screener + interactive UI.
**Phase 2.1 (done)** — corporate-action adjustment + ten missing trading
sessions recovered. See the 2026-08-19 addendum in `FINDINGS.md`.
**Phase 2.2 (done)** — symbol renames merged. 258 links applied, 3,606 → 3,348
symbols; renames now run *before* CA adjustment. See the Phase 2.2 addendum.
**Phase 2.3 (done)** — opening features joined to candidates (91.6% coverage)
and the pool characterised. Two results change what comes next: the gap must
come from bhavcopy's OPEN, not the tick open, and `om_low_vs_open_pct` is
censored at zero and cannot gate anything as computed.
**Phase 2.4 (done)** — forward returns labelled. **Both stated entry filters
have negative excess returns, and tightening either one makes it worse.** See
the Phase 2.4 addendum in `FINDINGS.md`. This is the first result that
contradicts the brief rather than refining it.
**Data pull (in progress)** — opening 1-second ticks for screened candidates.

No strategy logic, no backtest, no execution exists yet. That is deliberate.

## Data on hand

| dataset | path | scope |
| --- | --- | --- |
| daily bars (NSE bhavcopy) | `data/normalized/daily_bars.parquet` | 2020-01-01 → 2026-08-18, 3.35M rows, 1,647 sessions, point-in-time |
| **adjusted daily bars** | `data/normalized/daily_bars_adj.parquet` | same + `adj_factor` and `*_raw` twins; **use this one** |
| corporate actions | `data/metadata/corporate_actions.parquet` | 15,439 NSE records, ratios parsed |
| symbol changes | `data/metadata/symbol_changes.parquet` | 1,056 published NSE renames, 1999→ |
| rename map | `data/metadata/rename_map.parquet` | 609 touching the panel, 258 applied, per-link status |
| CA reconciliation | `data/metadata/ca_reconciliation.parquet` | 847 ex-date events, per-event match status |
| screening metrics panel | `data/normalized/screen_metrics.parquet` | 3.35M rows, ~50 indicator cols, built on adjusted prices |
| opening 1s ticks | `data/normalized/opening_1s/*.parquet` | 2023-08-21 → 2026-08-18 complete (3.34M rows) |
| opening features | `data/normalized/opening_features.parquet` | 64,799 clean symbol-days |
| **candidate panel** | `data/normalized/candidate_panel.parquet` | 63,698 candidate symbol-days with opening data joined |
| characterisation | `data/metadata/characterization.json` | distributions, censoring check, cut-point grid |
| **labelled candidates** | `data/normalized/candidate_labels.parquet` | 63,698 mornings + forward returns, MFE/MAE, excess vs market |
| labelling report | `data/metadata/labelling.json` | per-horizon outcomes, bucket profiles, stop diagnostics |

**A second pull is running on the server** (`user@server`, tmux session
`pull`) covering **2020-04-27 → 2023-08-18**, 74,777 pairs, ETA ~5.3h from
06:50 BST 2026-08-19. When it finishes:

```bash
bash scripts/sync_from_server.sh          # safe to re-run
.venv/bin/python -m src.cli opening-report
```

Check progress without disturbing it:
```bash
ssh user@server 'cat ~/brickbreak/data/metadata/pull_status.json; tail -3 ~/brickbreak/logs/pull.log'
```

## Hard limits worth not rediscovering

- **Daily history floor is 2020-01-01.** `sec_bhavdata_full` 404s before it and
  the older `cmDDMMMYYYYbhav.csv.zip` format is retired. Breeze has 1-second data
  back to 2018-04-02, but candidates cannot be screened without daily bars, so
  2020 is the effective floor for the whole pipeline.
- **Breeze rate limit is real**: ~4-5 req/s safe, 429s from ~7.5 req/s. Client
  throttle is lock-guarded; 429s auto-retry.
- **Breeze session tokens expire daily** (~midnight IST). No headless auth. Any
  run longer than a day must be resumed manually after refreshing `.env`.
- **Corporate actions**: handled as of 2026-08-19. Bhavcopy `PREV_CLOSE` is
  *not* a usable adjustment source — NSE leaves it raw on TATASTEEL's split and
  pre-adjusts it on DRCSYSTEMS'. Ratios come from NSE's corporate-actions API
  and are applied only where the tape confirms them; 739 of 847 events matched.
- **NSE trades on some weekends** (budget Saturdays, Muhurat, DR drills). Never
  restrict a bhavcopy sync to Mon-Fri, and always file a response under the
  date *inside* the file — 2021-11-04's session is served at the 05112021 URL.
- Breeze needs ISEC codes, not NSE symbols; ~5% of symbols fail to map (renames).
- Muhurat dates (2024-11-01, 2025-10-21) have no 09:15 session.
- 9 symbol-days carry negative volume (archive defect) and are excluded.

## Phase 2 — proposed, in order

### 1. Corporate-action adjustment — DONE (2026-08-19)
`src/corporate_actions.py`, `python -m src.cli sync-corp-actions`.
739 of 847 ex-date events adjusted; demergers (74) and unpriceable rights (26)
are flagged and left raw by design. `build_screen` now consumes the adjusted
bars automatically and the screener's price bounds use `close_raw`, since a
minimum-price filter is a statement about what actually traded that day.
Full write-up in `FINDINGS.md`.

### 1b. Symbol renames — DONE (2026-08-19)
`src/renames.py`, folded into `python -m src.cli sync-corp-actions`.

NSE publishes the rename list at `content/equities/symbolchange.csv`; the tape
decides whether each link is one continuous series. 258 of 263 candidate links
applied, 3,606 → 3,348 symbols, median merged history 660 → 1,636 sessions.
Four long suspensions left unmerged by design.

Two things this settled that are easy to get wrong:
- **Continuity must be tested on `close_raw`.** Adjustment factors accumulate
  per ticker, so the adjusted series has a fake step at every handover
  (MOTHERSUMI→MOTHERSON: 1.003 raw, 0.446 adjusted).
- **Renames merge before CA adjustment.** Adjusting first bakes that fake step
  in. Reordering also lifted CA matches from 739 to 752 for free.

`find_renamed_symbol` stays as a backstop — it answers a different question
(which ticker did *this* action trade under) and is still tested.

### 2. Join opening features to daily candidates — DONE (2026-08-19)
`src/opening_join.py`, `python -m src.cli candidate-panel`.
63,698 of 69,528 in-window candidate symbol-days joined (91.6%); the shortfall
is attributed, not assumed. Both sides fold through `renames.canonical_map()`.

**The gap does not come from the tick open.** bhavcopy's OPEN and Breeze's
first 1-second bar disagree on the *sign* of the gap on 10.6% of mornings —
NSE's opening print comes from the pre-open call auction and Breeze's series
starts at the first continuous-session trade, typically a few seconds later.
MINDACORP 2024-05-21: -6.0% gap by the opening print, +0.8% by the first tick.
`gap_pct` therefore comes from the daily panel; `open_drift_pct` keeps the
difference as an execution feature.

### 3. Characterise, do not yet filter — DONE (2026-08-19)
`src/characterize.py`, `python -m src.cli characterize`.

- **Gaps are small.** Median +0.24%, p90 +1.03%; only 2.1% exceed 2%. The
  screener selects for volatility contraction, so the pool is quiet by
  construction. A "modest gap" floor above ~1.5% trades a few hundred days out
  of 64,000 — defensible, but it should be a knowing choice.
- **Opening volume** is a median 2.98% of the symbol's median daily volume,
  p90 10.2%. Use `vol_5m_pct_of_median_daily`: a trailing average of `vol_5m`
  is selection-biased, since ticks exist only for days already screened in.
- **`om_low_vs_open_pct` is censored at zero** and 36.2% of days sit exactly on
  the boundary — 55% in the thinnest turnover quintile against 25% in the most
  liquid. As computed it rewards illiquidity. It must be conditioned on trade
  frequency or replaced before it gates anything.
- Cut-point grid is in `characterization.json`; even the strictest cell keeps
  916 mornings across 577 symbols, so sample size will not decide the
  thresholds. Forward returns have to.

### 4. Forward-return labelling — DONE (2026-08-19)
`src/labelling.py`, `python -m src.cli label`. Entry at `close_5m`, the last tick
of the opening window.

**This tests one narrow hypothesis (H001): "wait until 09:20 and enter at the
five-minute close".** It is not the discretionary strategy, which enters at an
unknown point inside the window as the setup develops. The results below are a
verdict on the 09:20 entry only.

The pool is a coin flip: hit rate 46-47% at every horizon, median return
negative, mean excess over an equal-weighted same-session benchmark of
0.02-0.05%. Then the part that matters:

- **Every cell of the Phase 2.3 cut-point grid has a negative +5d excess
  return**, from -0.17% to -1.04%, t-stats -3.3 to -7.0, and it worsens
  monotonically as either filter tightens. Raising the gap floor or the volume
  floor destroys value rather than concentrating it.
- **The mechanism is the opening window itself.** The five minutes between the
  selecting print and the actionable price reverse the gap (+1.16% mean on
  mornings gapping below -2%, -1.13% above +5%) and run with volume (+0.73% in
  the heaviest bucket). On exactly the mornings the rules select, you pay more
  than the forward edge is worth. Re-running against the untradeable opening
  print recovers roughly half of it — locating the effect, not rescuing it.
- **A stop finding from this phase was wrong and has been retracted** (H004).
  It paired the first-minute low with a 09:20 entry — different times — and so
  produced "stops above entries" on 32% of mornings. Read at the same `t`, the
  invariant `stop < running_low_t <= entry` holds on 100% of rows. Corrected
  measurement is H005 / `python -m src.cli entry-window`.

This does not kill the strategy — it rejects the 09:20 entry and moves the
burden onto the exits (H006): mean MFE at +10d is +6.82% against mean MAE
-5.25%, 10.84% of mornings touch +15% within ten sessions, 88.25% touch the
stop, **6.49% touch both**, and daily bars cannot say which came first.

### 4b. Entry-time correction — DONE (2026-08-19)
`src/entry_window.py`, `python -m src.cli entry-window`. The opening window
evaluated at t ∈ {30,60,90,120,180,240,300}s, using nothing after `t`. Enforces
`stop < running_low_t <= entry` (clean on 464,318 rows) and separates the setup
measure (`low_vs_open_pct`) from the risk measure (`stop_dist_pct`), which the
retracted H004 conflated. Conditioned on the entry having advanced 2%+ above the
open, the running low sits at the open while the stop is 2.41% below the entry —
a tight setup with normal risk.

**`t` is still a free variable and picking one is not yet on the table.** The
grid is a primitive for discovering an entry rule, not a rule.

### 5. Only then: strategy rules
Stop below opening-candle low, +15-20% target, half off, breakeven stop, 10-EMA
trail. Needs intraday data beyond the first 5 minutes to simulate honestly —
currently NOT downloaded, and that is a much larger pull.

Phase 2.4 narrowed why that pull would be run. It is no longer "to simulate the
strategy" but to answer one question: **on the mornings where both the +15%
target and the stated stop were touched within ten sessions (7.1% of the pool),
which came first?** Everything else about the entry rules has already been
answered without it, and answered against them. Worth deciding whether that
single question justifies the pull before committing to it.

### 6. Worth testing before the big pull
The first five minutes reverse the gap, and the -2% to -1% gap bucket is the
best-performing cell in the table (+0.38% excess at +5d, 52.2% hit rate against
46.5% pool-wide). That is the opposite of the stated entry — a fade rather than
a follow-through — and it costs nothing to label properly with data already on
disk. It is a hypothesis this data generated, not one it confirmed, so it needs
the 2020-2023 backfill as an out-of-sample check before it means anything.

## Research ledger

`HYPOTHESES.md` (root) records every hypothesis with a stable ID — H001–H007 as
of 2026-08-19, including the retracted H004. Per `AGENTS.md` it is updated
before moving substantially past a result, negative results are never deleted,
and data-generated ideas are marked exploratory until tested on unseen data.

## Open questions for the uncle
- "Below the largest ~250" — by market cap rank? We only have index-membership
  tiers (50/100/200/500/750), no true cap rank; NSE publishes no free cap file.
- What counts as a "modest gap" and "strong volume" numerically? **The question
  has changed shape.** It is no longer where to cut but why to cut at all: both
  filters have negative excess returns at every threshold tested, and the pool's
  median gap is +0.24% against a p90 of +1.03%, so "modest gap" as commonly
  meant (1-3%) already describes the top ~10% of mornings — the worst-performing
  ones. Worth showing him the grid and asking what he thinks it is measuring
  that this does not.
- **At what point in the window does he actually enter?** This is now the
  central open question, and it matters more than either filter — the first five
  minutes move against the selected mornings by 0.3-0.7% (H003). Does he watch
  for a specific trigger (a break of the first-minute high? a hold above the
  open?), and roughly how far into the window does that usually happen?
- How far below the running low does the stop go, and is it a fixed buffer, a
  tick, or a fraction of the opening range?
- "The low not far below the open" — as computed this is censored at zero and
  36% of days sit exactly on the boundary, mostly thin ones. Ask whether he
  means the first *minute* or the first five, and whether he is really
  describing the candle's shape (body vs wick) rather than a distance.
- Does he avoid earnings dates? Nothing currently models that.

## Conventions
- Never hardcode thresholds; they belong on `ScreenConfig`.
- Prefer `daily_bars_adj.parquet` over `daily_bars.parquet`. Indicators go on
  adjusted prices; anything asserting what was tradeable goes on `*_raw`.
- Pipeline order is **renames → corporate actions → indicators**. Anything
  keyed on symbol must be folded through `renames.canonical_map()`.
- Everything that touches Breeze goes through `src/breeze_client.py` (throttle +
  retry + call logging to `data/metadata/api_calls.jsonl`).
- Verify empirically rather than trusting docs — that has paid off repeatedly.
- `.venv/bin/python -m pytest tests/ -q` — 84 tests, keep them passing.
  Live-NSE tests are marked `network` and deselected by default; run them
  deliberately with `-m network`.
