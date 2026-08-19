# brickbreak — agent notes

NSE swing-trading research. Phase-gated: **no strategy, backtest, or execution
code until the current phase's findings are settled.** See `PLAN.md` for state,
`FINDINGS.md` for evidence.

## Data sources — which to use when

| need | source | depth |
| --- | --- | --- |
| daily OHLCV + universe | NSE bhavcopy (`sec_bhavdata_full`) | **2020-01-01 onward** |
| daily OHLCV (fallback) | Breeze `1day` | ~2002 onward |
| 1-second opening ticks | Breeze `1second` | 2018-04-02 onward |
| symbol renames | NSE `equities/symbolchange.csv` | full history, 1999 onward |
| sector / size tiers | NSE `ind_nifty*list.csv` | current snapshot |
| market regime, breakout levels, RS | `src/context.py` (derived, as-of) | 2020-01-01 onward |
| ETF exclusion | NSE `eq_etfseclist.csv` | current snapshot |

**Prefer bhavcopy for daily.** It is free, unauthenticated, carries turnover and
delivery %, and is **point-in-time** — each file lists exactly what traded that
day, which is what removes survivorship bias.

### The 2020 floor is a tradeoff, not a hard limit

Bhavcopy 404s before 2020 and the legacy `cmDDMMMYYYYbhav.csv.zip` format is
retired. But **Breeze daily reaches ~2002**, and 2018-2020 fits under the
1,000-row cap: ~1 call per symbol, ~2,900 calls, ~12 min.

The cost of using it: Breeze needs the symbol list up front, so that window
would be screened against **today's** master (~57 inactive stubs vs hundreds of
real delistings) — reintroducing survivorship bias for those years only, while
2020+ stays point-in-time. Mixing the two silently biases cross-period
comparison. Also loses `turnover` (fall back to price x volume, already the code
path) and delivery %.

Decision left open. If backfilled, tag those years as survivor-biased.

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
- Use **v2** for everything; v1 cannot serve 1-second data.

## NSE gotchas

- **Holiday URLs serve the previous session's file** instead of 404ing. Trust
  the file's own `DATE1`, reject mismatches. Regression-tested.
- **Muhurat (Diwali) dates have no 09:15 session** — evening session only, but
  they do appear in bhavcopy. Detect via dates where all symbols return empty.
- **bhavcopy OPEN != the first 1-second tick.** NSE's opening print comes from
  the pre-open call auction at 09:15:00; Breeze's 1-second series starts at the
  first continuous trade, often seconds later. They disagree on the *sign* of
  the morning gap on 10.6% of candidate days. Compute gaps from bhavcopy OPEN.
- **ETFs trade in the EQ series** and pass volatility-contraction screens
  trivially (near-zero vol by design). Exclude them.
- No free market-cap file exists; `size_tier_rank` is index-membership
  (50/100/200/500/750/9999), i.e. buckets, not a true cap rank.
- **Renamed tickers split a company's history in two.** NSE publishes the list
  (`symbolchange.csv`) but the tape decides: a link is merged only on a clean
  handover with continuous **raw** prices. Test continuity on `close_raw`, never
  the adjusted close — factors accumulate per ticker, so the adjusted series has
  a bookkeeping step at every handover.
- **`change_date` is the filing date, not the handover.** QUALITY printed on its
  own stated change date. Split on the tape.
- **The entry time inside the opening window is a free variable.** The strategy
  enters at some `t` as the setup develops, not at a fixed clock time. For any
  `t`, `stop_price < running_low_t <= entry_price` must hold, where
  `running_low_t` is the minimum low from 09:15:00 through `t`. A stop above an
  entry is a bug — it means the low and the price were read at different moments.
  Phase 2.4 shipped exactly that bug (see H004). Never use information after `t`
  to build the entry, the running low or the initial stop.
- **"Running low near the open" is a setup measure, not a stop-distance
  measure.** They are independent: open 100, running low 99.80, entry 103 gives
  a low 0.2% below the open and a stop 3.2% below the entry. Do not infer one
  from the other.

## Two defects that contaminate existing results — read before trusting a number

- **The screener used to select a morning using that morning's own close
  (H015). FIXED 2026-08-19** — `src/asof.py`, and `build_screen.load()` now
  defaults to the lagged `screen_metrics_asof.parquet`. Everything built before
  that date sits on the contaminated pool and must be re-run, not adjusted: the
  corrected screen overlaps the old one on only **61%** of candidate mornings.
  **Why it inverts rather than inflates:** the contraction filters read date D's
  own high and low, so a morning whose opening demand kept running all day has a
  wide range, fails contraction, and is excluded — while one that faded into a
  narrow range is kept. The pool retains the failures and discards the
  successes, which alone can manufacture "sustained opening demand is bearish".
  Standing practice regardless: split every forward outcome at the entry-day
  close and quote the **day-D close → D+h** segment.
- **The +5d excess return is the wrong outcome for this strategy.** The payoff
  is enter → stop losers quickly → a minority run +15-20% → sell half → trail. A
  setup that ends -3% by D+5 but exits at -1% on the stop, or reaches +18% and
  gives it back by D+5, is scored backwards by a fixed-horizon label. Every
  negative result in H001/H002/H009/H013 is subject to this. H006 is the real
  question and needs a stop/target payoff simulator.
- **Do not name a feature after a mechanism the data cannot see.** Volume is not
  buying volume; every trade has both sides. `persistent_demand` should have
  been `sustained_high_activity` — unusually much trading is equally consistent
  with a news event, two-sided disagreement, chasers, or institutions unloading.
- **Row-level t-statistics are inflated ~2.9x (H016).** 63,698 mornings are ~650
  sessions and the cross-section moves together within a session. Use
  `explore.cluster_stats`, which reports the clustered and naive statistic side
  by side. `labelling.horizon_summary` still emits the naive one.
- **Matched controls must come from the same session (H020).** Drawing them from
  +/-2 sessions to fill thin cells tripled every contrast in Phase 2.8. Winners
  cluster on local market troughs, so a control two days away sits 0.45% higher
  in the market index on 71.2% of sets, and "the winner opened lower in its base"
  partly restates that. `discovery.market_offset` prints the diagnostic every
  run; it must read 0.0000%. The tell was a discontinuity — |t| went from 4.3 at
  a 0-session band to 16.8 at 1 session, and real effects do not do that.
- **Normalisers are lookaheads too.** `behaviour.py` divided opening volume by
  `median_vol_20` off the *unlagged* panel — a 20-session median containing date
  D's own full-day volume. Every ratio needs its denominator checked, not just
  its numerator. Fixed 2026-08-20; read `screen_metrics_asof`, never
  `screen_metrics`, for anything that scales a date-D quantity.
- **Price an outcome label before using it (H018).** A path-aware state called
  `clean_winner` — large MFE, reached fast — simulated at **+0.05% excess** under
  the stated exit rule. Naming a state does not make it a winner; run it through
  `payoff.simulate` and look at what it earned. A path taxonomy is as capable of
  being wrong as a return label.
- **A significant contrast is not a large one.** Phase 2.8's top feature has
  |t| = 4.3 over 2,446 matched sets and a win-rate lift of **1.06x**. A paired
  design detects shifts far below anything tradeable. Always report the effect
  in decision units — win rate by band — beside the t-statistic.
- **The stated stop is not a stop as measured.** At t=180s the running-low stop
  has a median distance of 0.41% against a median ATR of 3.37%. `discovery`
  floors risk at 0.5 x ATR. Widening a stop cannot break
  `stop < running_low <= entry`; narrowing one can.

## Anything computed at a time `t` inside the window must be tested for lookahead

Cumulative statistics sampled at `t` are safe by construction; anything using a
*gap between* observations is not, because the gap to the next observation is
only known once it has printed. `behaviour.py` shipped exactly that bug in
`time_above_open_frac` — the final bar's dwell time ran to the next trade, which
lies after `t`, so two identical first-90-seconds gave different answers.
`test_features_at_t_ignore_everything_after_t` appends later bars and requires
every feature at `t` to be unchanged. Write that test before trusting a feature.

## Hypotheses — `HYPOTHESES.md` is research state, not documentation

Every meaningful strategy hypothesis — proposed, tested, supported, rejected, or
noticed in passing — is recorded in root-level `HYPOTHESES.md` with a stable ID
(`H001`, `H002`, …). It is the project's research ledger and outlives any single
phase write-up.

- **Record before moving substantially beyond it**, wherever practical. Writing
  the entry down after the fact loses what the experiment actually tested, which
  is often not what it was later described as testing.
- **Never discard a negative result.** A rejected hypothesis is a result. A
  hypothesis invalidated by a modelling bug is marked `SUPERSEDED`, kept, and
  annotated with what the bug was and what claim is retracted — the next person
  with the same idea needs to know it was tried and why the answer did not count.
- **Never silently retest the same hypothesis under a new name.** Link the prior
  ID and say what changed.
- **Distinguish the three kinds of work** in every entry: hypothesis generation
  (noticing something in data already seen), exploratory testing (testing it on
  that same data), and confirmatory / out-of-sample testing (testing on data not
  used to form it). Most of this project is still in the first two.
- **A hypothesis generated from a dataset is not confirmed by that dataset.**
  Mark it data-generated/exploratory and say so plainly. The 2020-04 → 2023-08
  backfill is the first genuinely unseen data this project has.
- **Reference the hypothesis ID** when strategy logic changes because of a
  result — in code comments, PLAN/FINDINGS updates, or commit notes.

## Conventions

- Thresholds live on `ScreenConfig` — never hardcode a belief.
- Daily panel order is **renames → corporate actions → indicators**, and it
  matters: adjusting before merging bakes in a fake step at every handover.
  Anything keyed on symbol folds through `renames.canonical_map()`.
- All Breeze traffic goes through `src/breeze_client.py` (throttle, 429 retry,
  call logging to `data/metadata/api_calls.jsonl`).
- Verify empirically rather than trusting docs; that has repeatedly paid off.
- Long pulls run on the server (`user@server`) under tmux via
  `scripts/run_pull.sh`; resumable from the manifest.
- `.venv/bin/python -m pytest tests/ -q` — keep green (168 tests). Tests marked
  `network` hit live NSE and are deselected by default; run with `-m network`.
- **Exploration is fenced.** `explore.EXPLORE_START` is 2023-08-21; the
  2020-2023 backfill is holdout and `explore.fence()` *raises* rather than
  filtering, because a silently-dropped holdout row is an invisible breach.
  `python -m src.cli behaviour` builds the exploration window only.
- **A search reports a maximum, so the bar is the permuted maximum.** Over 68
  features the 95th percentile of max |t| under the null is ~3.4, not 1.96.
  `discovery.permutation_null` shuffles the winner label *inside each matched
  set*, which keeps every stratum intact and destroys only what is being
  claimed.
- A permutation null over a scan must shuffle the outcome **within date**.
  Shuffling date-level means while leaving within-date deviations attached
  preserves the cross-sectional signal being tested and cannot reject anything.
