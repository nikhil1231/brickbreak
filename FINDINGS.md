# FINDINGS — Breeze historical data feasibility (Phase 0)

**Status: COMPLETE.** Run date 2026-08-18/19. `breeze_connect==1.0.69`, Python 3.11.8.
Evidence: ~200 live API calls, all logged in `data/metadata/api_calls.jsonl`,
full matrix in `data/metadata/feasibility_report.json`.

Everything below was measured. Where the SDK docs and observed behaviour differ,
the observation wins.

---

## Answers to the ten questions

### 1. Does Breeze historical equity access work?

**Yes.** NSE cash daily, 1-minute and 1-second all return data. Response shape is
consistent: `{"Success": [...], "Status": 200, "Error": null}` with fields

```text
close, datetime, exchange_code, high, low, open, stock_code, volume
```

v1 additionally returns `count`, `open_interest`, `product_type`, `right`,
`strike_price`, `expiry_date` — all irrelevant for cash equities, and v1 cannot
serve 1-second data at all. **Use v2 for everything.** (v1 and v2 disagreed
slightly on the same window: 21 vs 20 daily rows for June 2026.)

### 2. Does 1-second data work?

**Yes, and it is genuinely second-level.** A 09:15:00–09:20:00 request returns
~250–300 distinct one-second bars, each with its own OHLC and volume. Not
interpolated, not cumulative, not a repackaged 1-minute series.

Bars are **sparse**: only seconds with activity appear, so a 5-minute window
yields ~294/301 for RELIANCE, 158 for ICICIBANK, 36 for a thin small cap. Gap
counting is therefore the wrong quality metric — see question 5.

### 3. How far back does it actually go?

| Dataset | Depth | Evidence |
| --- | --- | --- |
| **1-second** | **from 2018-04-02** | Jan/Feb/Mar 2018 → 0 rows on every trading day tested; 2018-04-02 onward → 250–300 rows. Sharp cutover, not a taper. |
| 1-minute | at least 2019 (tested), likely same era | 1-min returned for 2019-05-20 |
| **Daily** | **~2002** for RELIANCE/INFY; Jan 2000 → 0 rows | Jan-of-year walk-back, 2025→2000 |
| Daily (TCS) | from listing (2004); Jan 2002 → 0 rows | correctly reflects listing date |

2018-04-02 is the start of Indian FY2018-19, which suggests an archive cutover
rather than a gradual backfill. **~8.4 years of 1-second history** — comfortably
more than the 3 years the strategy needs.

### 4. Is usable per-second volume present?

**Yes.** Volume is per-bar, not cumulative (`looks_cumulative=False` on every
sample; values oscillate, e.g. 15865 → 0 → 55350).

Zero-volume bars do occur — 6.5% (RELIANCE) to 16.5% (ICICIBANK) of bars in the
opening window, 75% for a thin small cap. They carry a price but no traded
quantity. They are **harmless**: they do not break the volume totals (next).

### 5. Can we reconstruct the first five minutes?

**Yes — exactly.** The decisive test summed 1-second volume per minute and
compared against the 1-minute bars for the same window (2026-08-05, 09:15–09:20):

| Symbol | Σ 1-second volume | 1-minute total | Match |
| --- | --- | --- | --- |
| RELIANCE | 703,075 | 703,075 | ✅ |
| INFY | 623,613 | 623,613 | ✅ |
| TCS | 151,851 | 151,851 | ✅ |
| HDFCBANK | 4,653,657 | 4,653,657 | ✅ |
| ICICIBANK | 666,555 | 666,555 | ✅ |
| NELCAST | 3,001 | 3,001 | ✅ |

**Zero discrepancy on every security.** Sparse bars lose no volume; the missing
seconds genuinely had no trades. Opening-volume behaviour — the core of the
entry rule — is reconstructable.

Caveat: the thinnest name tested (KAKATCEM) returned **no 1-second bars at all**
in the opening window and only 91 minute-bars for the whole day. Illiquid stocks
may simply not trade at the open, which is a strategy constraint, not a data bug.

### 6. What API limits did we observe?

**A hard 1,000-row cap per call, and it silently returns the **tail**.** This is
the most dangerous behaviour found:

| Request | Rows | Returned span |
| --- | --- | --- |
| 1s, 5 min | 294 | 09:15:00 – 09:20:00 ✅ |
| 1s, 30 min | 754 | 09:15:00 – 09:45:00 ✅ |
| 1s, 2 h | **1000** | 10:50:25 – 11:14:59 ❌ start dropped |
| 1s, full day | **1000** | 14:58:21 – 15:15:00 ❌ |
| 1s, 7 days | **1000** | 14:58:21 – 15:15:00 ❌ |
| daily, 3 y | 743 | 2023-08-18 – 2026-08-17 ✅ |
| daily, 25 y | **1000** | 2022-08-03 – 2026-08-17 ❌ |

No error, no pagination cursor, `Status: 200`. **Any code that requests a wide
range and trusts the result is silently working with recent data only.** Always
chunk to stay under 1,000 rows and verify the returned span.

Other measurements over ~200 calls at ~85 req/min:

- mean call 0.63 s, median 0.60 s, p90 0.93 s, max 1.95 s
- **no throttling, no 429s, no rate-limit errors observed** at that pace
- repeated identical calls returned **byte-identical** payloads (3×294 rows)

### 7. Can inactive/delisted securities be queried?

**Yes — but only by ISEC code, and only for names ICICI still lists.**

| Security | ISEC code | Window | Rows via ISEC code | Rows via NSE symbol |
| --- | --- | --- | --- | --- |
| Andhra Bank (merged 2020) | `ANDBAN` | Jun 2019 | **19** ✅ | 0 ❌ |
| Centurion BoP (merged 2008) | `CENBN` | Jun 2007 | **20** ✅ | 0 ❌ |
| Bharat Financial (merged 2019) | `BHAFIN` | Jun 2018 | **20** ✅ | 0 ❌ |

History survives the delisting — 2007 data for a bank that stopped existing in
2008. The limitation is **discovery, not retrieval**: the scrip master carries
only ~57 inactive EQ stubs, versus the high hundreds of real NSE delistings, and
its `DateOfDeListing` / `DeleteFlag` columns are empty in all 5,729 rows.

### 8. How expensive is a full historical download?

Universe: **2,901 active EQ names** (from the public scrip master). Storage
measured on a consolidated Parquet file at **19.3 B/row** (small per-call files
run ~42 B/row due to footer overhead — consolidate before judging).

| Dataset | Rows | Storage | API calls | Serial time |
| --- | --- | --- | --- | --- |
| **First 5 min, 1-second, 3 y** | 653 M | **11.8 GB** | **2,175,750** | **~423 h (17.6 days)** |
| Daily, 20 y | 14.5 M | 268 MB | 14,505 | ~2.8 h |

The 1-second call count is driven by the 1,000-row cap: a multi-day request
returns the tail, so it is **one call per security per trading day**, with no way
to batch.

**But the full-universe download is the wrong thing to buy.** The strategy
screens on daily data first (sector trend → volatility contraction), and only
then needs opening-tick data for the handful of survivors. Two-stage fetch:

- bulk daily history for all 2,901 names: **~2.8 hours, 268 MB** — trivial
- 1-second only for screened candidates on candidate dates — a rounding error

A NIFTY-500-sized 1-second universe for 3 years is ~375k calls ≈ 73 h serial,
which is a weekend, not a month.

### 9. How do corporate actions appear?

**Inconsistently — and this is the most serious problem found.**

| Event | Ex-date | Largest 1-day move | Verdict |
| --- | --- | --- | --- |
| ITC 1:2 bonus | 2016-07-12 | +1.42% | adjusted |
| RELIANCE 1:1 bonus | 2017-09-07 | +3.07% | adjusted |
| INFOSYS 1:1 bonus | 2018-09-12 | +2.79% | adjusted |
| HDFCBANK 1:2 split | 2019-09-19 | +8.95% | adjusted |
| TATASTEEL 1:10 split | 2022-07-29 | +7.58% | adjusted |
| **NESTLEIND 1:10 split** | 2024-01-05 | **−90.18%** | **UNADJUSTED** |
| **RELIANCE 1:1 bonus** | 2024-10-28 | **−49.76%** | **UNADJUSTED** |
| **BAJFINANCE split+bonus** | 2025-06-16 | **−89.95%** | **UNADJUSTED** |

The archive is back-adjusted up to a cutover somewhere **between Jul 2022 and
Jan 2024**, and raw after it. So a single symbol's daily series can contain an
artificial −50% or −90% step. Untreated, this destroys EMA trend filters and
makes a "+15–20% target" meaningless.

**Mandatory pre-processing**: detect large single-day gaps, source the actual
ratios (NSE publishes corporate actions), and re-adjust. Do not skip this.

### 10. Fields, timestamps, missing data, errors, inconsistencies

- **Timestamps** are `YYYY-MM-DD HH:MM:SS` with **no timezone suffix** and are
  **IST wall-clock**. Intraday stamps land in 09:15–15:31; daily bars are dated
  `00:00:00`. No duplicates in any sample. (The v1 endpoint's *request* format
  wants a `.000Z` suffix that it then treats as IST — mislabelled, but the
  *responses* carry no suffix at all.)
- **OHLC integrity is clean**: zero rows with `high < low`, zero with open or
  close outside the high/low range, across every sample.
- **`stock_code` must be the ISEC short code.** `RELIANCE` returns **0 rows with
  no error**; `RELIND` returns 20. Silent, and a trap because `TCS` maps to
  itself. `src/security_master.resolve()` handles this.
- **Silent archive gaps exist.** On 2026-08-05, both RELIANCE and INFY are
  missing every bar from 15:16 to 15:30, with a single aggregate bar at 15:31.
  Other dates and symbols are complete through 15:29–15:31. `Status: 200`, no
  error — the data is just absent. **Gap detection is not optional.**
- **1-minute data is a complete gridded series** (360–375 contiguous bars/day,
  zero internal gaps) — unlike the sparse 1-second series.
- **Index history is available**, which the sector-trend filter needs. Of 17
  candidate codes, 5 returned data: `NIFTY`, `CNXBAN` (Bank), `NIFSEL`,
  `NIFFIN` (Financial Services), `CNXIT` (IT). Codes for auto/pharma/metal/FMCG
  were **not** found — broader sector coverage still needs work.
- **Authentication has no headless path.** The session token requires an
  interactive browser login and expires daily.

---

## RECOMMENDATION: **GO** — with four mandatory conditions

The three questions that could have killed the project all resolved favourably:
1-second data is real, its volume reconciles **exactly** with 1-minute totals,
depth (8.4 y) exceeds the requirement, and delisted history is retrievable.

Breeze is sufficient for the next prototype, provided:

1. **Fetch in two stages.** Bulk-download daily history for all 2,901 names
   (~2.8 h, 268 MB), screen on that, then pull 1-second data only for screened
   candidates. Do not attempt the 653M-row full-universe 1-second download.
2. **Re-adjust for corporate actions yourself.** The archive is unadjusted after
   ~2023. This is the single largest correctness risk.
3. **Chunk every request under 1,000 rows and assert the returned span.** The
   tail-truncation is silent and will otherwise corrupt research quietly.
4. **Validate every fetch for gaps.** Silent holes exist (2026-08-05 confirmed).
   `src/validate_data.py` already does this; keep it in the pipeline.

Not blockers, but plan for them: the daily manual login makes unattended nightly
downloads impossible without stored-TOTP browser automation; and sector-index
coverage beyond Bank/IT/Financials is unresolved.

**If** the project later genuinely needs the entire NSE universe at 1-second
resolution, that specific ambition — 2.18M calls, 17.6 days serial, once per
refresh — would justify a different source. The prototype does not need it.

---

## Addendum — bulk opening-data pull (2026-08-19)

65,563 candidate symbol-days (3 years, 2023-08-21 → 2026-08-18) pulled on the
user's own server in **4.77 hours at 3.9 calls/s, 0 errors, no restarts**.
Result: **3,340,940 rows / 59 MB** across 656 date files, 1,629 symbols.

Four things this run established that Phase 0 could not:

### A real rate limit exists (Phase 0 missed it by never testing concurrency)

Breeze returns **HTTP 429 "Rate Limit Exceeded"**. Phase 0 concluded "no
throttling observed" because it only ever ran one request at a time. A first
concurrent batch lost 71 of 1,099 calls to 429s.

Root cause was ours: `_throttle()` read and wrote `_last_call_at` without a
lock, so each worker thread saw a stale timestamp and the effective rate
overshot to ~7.5 calls/s. With a lock-guarded slot reservation, measured
behaviour is:

| pace | 429s |
| --- | --- |
| ~7.5 calls/s (unsynchronised) | 71 / 1,099 |
| 4.9 calls/s | 0 / 160 |
| 3.9 calls/s (production run) | **0 / 65,563** |

429s are now retried with exponential backoff, so a blip cannot silently punch
holes in the dataset. All 71 originally-lost pairs were recovered on retry.

### ETFs pass a contraction screen trivially

ETFs trade in the EQ series, so nothing structural excluded them — and a liquid
or debt ETF has near-zero volatility *by construction*, which reads as a
permanent tight base. The thinnest "candidates" were LIQUIDBETF, SBILIQETF,
HDFCLIQUID. Excluding NSE's authoritative ETF list (342 symbols, from
`eq_etfseclist.csv`) cut candidates **31%** (105 → 73/day).

### Two dates have no opening session at all

2024-11-01 and 2025-10-21 returned zero rows for **100%** of attempted symbols
(4/4 and 158/158) while neighbouring dates were fully populated. Both are Diwali
**Muhurat** sessions — a ~1-hour *evening* session. They appear in daily
bhavcopy (so the screener generates candidates for them) but have no 09:15-09:20
window. `find_no_session_dates()` detects this from the data rather than
hardcoding Diwali, so future special sessions are caught the same way.

### Negative volume is an archive-wide defect, not a 1-second artifact

9 bars out of 3.34M (0.0003%) carry negative volume, clustered on 2024-01-09.
Checking each against the 1-minute endpoint: **Breeze's 1-minute bars report the
same negative values**, so this is not a tick-level glitch and cannot be fixed
by re-fetching.

Volume cannot be negative, so `flag_bad_volume()` marks the 9 affected
symbol-days and `opening_features()` **excludes** them rather than clipping to
zero — clipping would produce a wrong-but-plausible opening volume, which is
worse than a known hole.

### Volume reconciliation holds for thin names too

Phase 0 proved 1s-sums-to-1m only on liquid large caps. Re-checked on 60
candidate symbol-days sampled across the liquidity range: **60/60 exact**,
including days with only 4 bars.

### What the opening window actually looks like for these names

These are much thinner than Phase 0's large caps, which matters for the entry rule:

| measure | value |
| --- | --- |
| median bars per symbol-day | **45** (of 301 possible) |
| p10 / p90 bars | 34 / 64 |
| zero-volume bars | **45.2%** |
| symbol-days with <10 bars | 299 (0.5%) |
| symbol-days with zero opening volume | 208 |

`opening_features()` reduces each symbol-day to the rule's inputs: 5-minute
volume, first-minute OHLCV, `om_low_vs_open_pct` (how far the opening candle's
low sat below its open), and `om_body_pct`.

---

## PLACEHOLDER: point-in-time universe (future work)

**Not solved in this phase, by design.**

What Phase 0 established: retrieval of delisted history **works** (`ANDBAN`,
`CENBN`, `BHAFIN` all returned data for their trading years), so survivorship
bias here is a **discovery** problem, not an access problem. Breeze's master is a
today-snapshot with ~57 inactive EQ stubs and no delisting dates.

Intended shape of the fix:

- Source point-in-time membership from **NSE's daily bhavcopy archive**, which
  lists every security that traded on each historical date.
- Build `data/metadata/universe_by_date/`, date → set of traded symbols.
- Map bhavcopy symbols to ISEC codes via **ISIN**, which survives renames;
  the scrip master already carries `ISINCode`.
- For names bhavcopy shows but the master omits, expect retrieval gaps — measure
  the hit rate before trusting any long-horizon backtest.

Deliberately not started; Phase 0's verdict is now in.

---

## Addendum — Phase 2.1: corporate actions and missing sessions (2026-08-19)

Phase 0 question 9 flagged corporate actions as "the most serious problem
found" and prescribed detecting large single-day gaps and sourcing the true
ratios. Doing that turned up a second, unrelated defect in the daily panel
first, and changed the prescription itself.

### The daily panel was missing ten trading sessions

`nse_archive.sync()` only requested Mon–Fri. NSE trades on some weekends, and
those sessions were never downloaded:

| missing session | why it exists |
| --- | --- |
| 2020-02-01 Sat, 2025-02-01 Sat, 2026-02-01 Sun | Union Budget special session |
| 2020-11-14 Sat, 2023-11-12 Sun | Diwali Muhurat trading |
| 2024-01-20 Sat, 2024-03-02 Sat, 2024-05-18 Sat | disaster-recovery-site live drills |
| 2021-11-04 Thu | Muhurat — the file is served at the **05112021** URL |
| 2022-08-08 Mon | the `.csv` URL returns an **XLSX workbook** (PK zip header) |

The last two are not weekend problems. The 2021-11-04 session was rejected by
the holiday guard, which discarded any file whose internal date differed from
the URL's; the fix is to file each response under the date *inside* it, which
also subsumes the holiday-stale case it was written for. The 2022-08-08 file is
a one-day NSE publishing mistake and needs an XLSX fallback.

**How they were found.** Comparing bhavcopy's `PREV_CLOSE` against the previous
session's close in our own panel produced 15,337 mismatches. They were not
scattered: 15,331 of them fell on just ten dates, market-wide, at 64–87% of all
symbols. A corporate action hits one symbol; only a missing session moves the
whole market at once. After backfilling, 6 mismatches remain and no date shows
a market-wide effect.

### PREV_CLOSE cannot be used to derive adjustments

The tempting shortcut — read the ratio out of `PREV_CLOSE` — does not work.
NSE does not adjust that column for corporate actions: TATASTEEL's 2022-07-28
split shows `PREV_CLOSE=959.40` against `OPEN=98.10`. But it is not reliably
*un*adjusted either — SETFGOLD (2022-01-06) and DRCSYSTEMS (2022-03-16) both
carry an already-adjusted `PREV_CLOSE`. The column is inconsistent, so two step
measures are computed and either may confirm an event: `open/PREV_CLOSE`, and
`open/(previous session's close)`.

### The adjustment is reconciled, not asserted

NSE's corporate-actions API (`/api/corporates-corporateActions`, cookie-primed,
walked in quarterly chunks) gives exact stated ratios. The tape gives exact
step locations. Neither is trustworthy alone — the feed's `exDate` is sometimes
a session out and says nothing about whether the action was executed, while the
tape cannot tell a 1:2 split from a stock that genuinely halved. So a ratio is
applied **only where both agree**, and every disagreement is recorded in
`data/metadata/ca_reconciliation.parquet` rather than silently resolved.

Of 847 ex-date events across 2020–2026:

| status | n | meaning |
| --- | --- | --- |
| matched | 739 | stated ratio confirmed by the tape; adjusted |
| unadjustable | 74 | demerger — no recoverable ratio, deliberately left raw |
| unparsed | 26 | rights terms without a usable issue price |
| no_step | 5 | ratio stated, tape never stepped |
| ratio_mismatch | 3 | tape stepped by something else entirely |

Three findings came out of getting this to reconcile:

1. **Actions sharing an ex-date must be combined.** BAJFINANCE's 2025-06-16 is
   a 1:2 split *and* a 4:1 bonus: 0.5 × 0.2 = 0.10 against an observed 0.1024.
   Matched separately, both look like gross mismatches. 30 ex-dates carry more
   than one action.
2. **`Bonus Ncrps 4:1` is not an equity bonus.** Preference-share and debenture
   bonuses leave the share count untouched; treating TVSMOTOR's as a 5-for-1
   would have rescaled its entire history by 0.2 for nothing.
3. **The corporate-actions feed keys on today's symbol, the tape on the old
   one.** 14 events were filed under a ticker that did not exist on its own
   ex-date — UNOMINDA's bonus is on the tape as MINDAIND, ACUTAAS as AMIORG,
   VEEDOL as TIDEWATER. Left unresolved, the *pre-rename* history keeps an
   unadjusted split in it. Resolution requires two independent conditions: the
   candidate stepped by the stated ratio, and it stopped trading exactly where
   the current symbol began. The second is what makes it safe — TORNTPHARM also
   halved within a day of UNOMINDA's bonus, but it is still trading.

### The 20% tolerance is measured, not assumed

Across 731 events carrying both a stated ratio and an observed step, 99.5%
agree to within 20% and only four fall outside — a clean gap between the two
populations. The residual spread is real rather than error: a stated ratio is
exact, but the ex-date open still contains that morning's genuine move, and the
errors skew slightly positive (median +1.5%) because split and bonus ex-dates
tend to open firm. An 8% tolerance rejected 122 perfectly good ratios.

### What it changed

Among symbols with no corporate action, the session backfill alone shifts
`ret_60d` by more than 20pp on 0.07% of rows. Among the 562 symbols carrying
one, that figure is **4.19%** — 58× higher — and `above_ema_mid`, a hard
screener gate, flips on **3.15%** of their rows against 0.13% elsewhere.
Residual >35% single-session steps among adjusted symbols fall from 470 to 16,
and of those 16, six are demergers left raw by design.

### Still unhandled, deliberately

- **Demergers (74).** The step is genuine value leaving the company; adjusting
  it would be fiction. Flagged for exclusion, never rescaled.
- **Rights with no stated premium (26).** No issue price, so no theoretical
  ex-rights price. Flagged.
- **Dividends.** Not adjusted at all. The strategy is a multi-day swing on
  percentage moves, and total-return adjustment would misstate the prices a
  stop or target would actually have been hit at.
- **Symbol renames as a general problem.** Resolved here only where a corporate
  action forced the issue. Given its own pass below.

## Addendum — Phase 2.2: symbol renames (2026-08-19)

Phase 2.1 closed with renames flagged as unfinished: they were resolved only
where a corporate action happened to force the issue, leaving every other
renamed company's history split across two tickers. This is that pass.

### NSE publishes the rename list; it just isn't where the corporate actions are

`https://nsearchives.nseindia.com/content/equities/symbolchange.csv` — no auth,
no header row, four fields (company, old symbol, new symbol, effective date),
1,056 rows going back to 1999. It contains every rename the previous phase
found by inference, including the three that were hand-resolved
(MINDAIND→UNOMINDA, AMIORG→ACUTAAS, TIDEWATER→VEEDOL).

This does not make the inference in `find_renamed_symbol` redundant — that
function answers a different question (which ticker did *this* corporate action
trade under) and stays as a backstop. But for the general problem, a published
list beats a heuristic.

Of the 1,056 changes, 609 touch a ticker present in the 2020+ panel and 263 have
both halves in it. The remainder are pre-2020 or mutual-fund tickers that never
trade in the equity panel.

### The published list says what, the tape says whether

Same posture as the corporate actions: NSE's file is authoritative about which
renames were filed, and silent about whether the two tickers form one continuous
tradeable series in our window. Both cut-points sit in empty space rather than
on top of a population, so neither is a judgement call:

| test | accepted population | nearest reject |
| --- | --- | --- |
| handover gap | 1–7 calendar days (258 links) | 23, 55, 463, 1,977 days |
| raw price step across handover | max deviation **11.7%** | 31%, 110%, 1,094% |

258 links applied, collapsing 3,606 symbols to 3,348. Median history for a
merged listing goes from 660 sessions to 1,636, against 1,647 possible.

### Continuity must be measured on raw prices, and this sets the pipeline order

The obvious continuity test — does the adjusted close carry across the handover
— is wrong, and wrong in a way that would have rejected most of the real
renames. Adjustment factors accumulate *per ticker*, so the two halves of one
listing carry different factors and the adjusted series has a step at the
handover that is pure bookkeeping. MOTHERSUMI→MOTHERSON is 1.003 raw and 0.446
adjusted. Across the 258 links the raw step never deviates more than 11.7%
while the adjusted step reaches 94%.

The same fact fixes the order of operations: **renames are merged before
corporate-action adjustment, not after.** Adjusting first computes two
independent factor chains for one listing and bakes the fake step in
permanently. After merging first, MOTHERSON carries a single factor of 0.4444
across its handover, and there are **zero** >25% adjusted-series steps at any
of the 258 merged handovers.

This ordering also improved the previous phase's result for free: corporate
actions matched to the tape rose from **739 to 752** of 847, because 13 events
filed under a company's current ticker now find their own history instead of
needing the rename fallback.

### Renames chain, and a broken link must stop the chain

Renames compose, up to four deep in six years: CLNINDIA→HEUBACHIND→SUDARCOLOR,
LTI→LTIM→LTM, and Indiabulls going IBULISL→YAARII→YAARI→IBULLSLTD. Resolution
follows *applied* links only, so a chain broken by a rejected link stops there
rather than leaping the gap it was rejected for — WEIZFOREX→EBIXFOREX is a
55-day suspension and is refused, but EBIXFOREX→DELPHIFX still applies and
WEIZFOREX stays separate.

Merging is to the **newest** ticker. NSE's index-membership and sector files are
a current snapshot, so the canonical name is the one those joins already match.

### The stated date is not the handover date

`change_date` is the effective date and is occasionally a session ahead of the
tape. QUALITY's stated change is 2025-07-18, but QUALITY printed that day and
QUALITY30 only began on the 21st. Scoping the map by the filing would have put a
day of real trading under the wrong ticker. The observed handover is what is
used — the same "trust the tape" lesson as PREV_CLOSE and the holiday URLs.

### Four renames left unmerged, deliberately

All four are long suspensions where the ticker changed while the stock was not
trading. They are the same company, but splicing the halves into one series
would manufacture an overnight return that never happened and let rolling
windows blend prices years apart.

| link | gap | step | reading |
| --- | --- | --- | --- |
| SPENTEX → CLCIND | 1,977d | 11.95× | halted 2020-09, resumed 2026-01 |
| NTL → NEUEON | 463d | 2.10× | halted 2024-09, resumed 2025-12 |
| WEIZFOREX → EBIXFOREX | 55d | 1.31× | suspension across the rename |
| SCAPDVR → GATECHDVR | 23d | 0.91× | DVR line, 23-day gap |

### Ticker reuse does not currently happen, and the code assumes it might anyway

A symbol→symbol map is only safe if a retired ticker is never reissued to a
different company. Across the whole panel exactly one published change has the
old ticker printing on or after its stated change date, and that is the
QUALITY off-by-one above, not a reuse. But the assumption is load-bearing, so
`apply_renames` asserts it: if the merge ever produces a duplicate
(symbol, date) row it raises instead of silently welding two companies into one
series. Regression-tested.

### What is still open

`opening_features.parquet` carries two pre-rename tickers (AMIORG, ITDCEM).
Joining opening features to the daily panel must fold both sides through
`renames.canonical_map()` or those symbol-days drop out silently.

## Addendum — Phase 2.2/2.3: opening join and candidate characterisation (2026-08-19)

Steps 2 and 3 of the Phase 2 plan, run against the tick window we hold locally
(2023-08-21 → 2026-08-18). The 2020-2023 pull is still in flight and changes
none of the mechanics below, only the sample size.

### The gap is not the tick open — bhavcopy's OPEN is

PLAN asked to verify that the daily `gap_pct` agrees with the tick-level open.
It does not, and the disagreement is large enough to change the sign of the
gap on **10.6% of candidate mornings**. Correlation between the two gap
measures is only 0.874.

The tick open sits inside bhavcopy's daily [low, high] on 99.98% of days, so
the ticks are real trades — just not the opening one. Four measurements place
the fault on the tick side:

| measurement | result |
| --- | --- |
| bhavcopy OPEN outside the first 5 min tick range | 26% of days (14.0% below, 11.9% above — symmetric) |
| exact agreement when Breeze's first bar is 09:15:00 | 45.8%, median deviation 0.008% |
| exact agreement when it is 09:15:05 | 30.7%, median deviation 0.091% |
| exact agreement, thinnest vs most liquid turnover quintile | 59% vs 17% |

Monotonic decay with how late the first bar lands, symmetric dispersion, and
best agreement on names that barely trade: that is a missing first print, not
bad data. NSE opens with a call auction — orders from 09:00 are matched and the
equilibrium price is disseminated at 09:15:00 — and Breeze's 1-second series
begins at the first *continuous-session* trade it captured, typically a few
seconds later.

MINDACORP on 2024-05-21 is the clearest case. Bhavcopy opened it at 405.05
against a 430.75 previous close, a **-6.0% gap down**. Breeze's first bar is
09:15:03 at 434.00, which reads as a **+0.8% gap up**. The 1-second series has
no bar at all before 09:15:03.

So `gap_pct` is computed from bhavcopy's OPEN. The tick open is kept as
`open_drift_pct` — the move from the opening print to the first price actually
transactable — which is a useful execution feature in its own right: median
0.00%, p95 0.60%, p99 1.29%.

### Join coverage

63,698 of 69,528 candidate symbol-days inside the tick window carry opening
data (**91.6%**). The shortfall is accounted for rather than assumed: 5,081
were never requested (the candidate set grew when the rename merge lengthened
histories, so these are days that did not exist as candidates when the pull
list was drawn), 741 returned empty, 8 fetched OK but were dropped as
negative-volume symbol-days.

The join folds both sides through `renames.canonical_map()`. Without it 63 rows
silently fail to match.

### The gaps are an order of magnitude smaller than the language suggests

| measure | p05 | p25 | p50 | p75 | p90 | p95 | p99 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `gap_pct` | -0.83 | 0.00 | **0.24** | 0.62 | 1.03 | 1.45 | 2.71 |
| `vol_5m` as % of median daily | 0.40 | 1.53 | **2.98** | 5.45 | 10.22 | 16.04 | 44.77 |
| `range_5m_pct` | 0.37 | 0.64 | **0.91** | 1.31 | 1.83 | 2.26 | 3.36 |
| `open_drift_pct` | -0.49 | -0.02 | **0.00** | 0.10 | 0.38 | 0.60 | 1.29 |

Only **2.1%** of candidate mornings gap more than 2%, and 0.15% gap more than
5%. This follows from the screener rather than contradicting it: stage 6
selects for volatility *contraction*, so the pool is quiet by construction. Any
"modest gap" threshold above ~1.5% is a decision to trade a few hundred days
out of 64,000. That may well be right, but it should be chosen knowingly.

Gap and opening volume are positively related and both track range, so the two
rules are not independent — the highest-volume bucket (>40% of median daily
volume) has a median gap of 1.40% against 0.16% in the lowest.

### `om_low_vs_open_pct` cannot be used as stated

The rule "the low is not far below the open" reads as a strength test. As
currently computed it is not one. `om_low` is the minimum low across the first
minute and `om_open` is that minute's opening price, so **the measure is
censored at zero by construction** — it can never be positive, and 36.2% of
candidate days sit exactly at the boundary.

That atom is a liquidity artifact:

| turnover quintile | days at exactly zero | median bars in the first minute |
| --- | --- | --- |
| Q1 (thinnest) | 55.2% | 8 |
| Q2 | 41.0% | 9 |
| Q3 | 32.3% | 9 |
| Q4 | 27.3% | 10 |
| Q5 (most liquid) | 24.9% | 10 |

A stock that prints eight times in its first minute has few chances to trade
below its opening price. The rule is nearly free for a thin name and genuinely
binding for an active one, which means applying one threshold across the pool
silently favours illiquidity — the opposite of the intent. It needs to be
conditioned on trade frequency, or replaced by a measure that is not
one-sided, before it gates anything. `om_body_pct` saturates at 100% from p75
upward for the same reason.

### What each pair of cut-points costs

Reported as a grid, not a recommendation:

| gap band | vol ≥ 5% | vol ≥ 10% | vol ≥ 20% |
| --- | --- | --- | --- |
| [0, 1] | 10,765 (16.9%) | 3,425 (5.4%) | 916 (1.4%) |
| [0, 2] | 13,114 (20.6%) | 4,709 (7.4%) | 1,480 (2.3%) |
| [0, 3] | 13,636 (21.4%) | 5,071 (8.0%) | 1,699 (2.7%) |
| [-1, 2] | 16,045 (25.2%) | 5,508 (8.7%) | 1,678 (2.6%) |

Even the strictest cell keeps 916 mornings across 577 symbols and 351 sessions,
so sample size does not force the choice — which means the choice has to come
from forward returns, and that is the next step.

### Volume needs a denominator that exists every day

"Opening volume vs its own 20-day average" cannot be computed honestly here:
opening ticks were only ever fetched for days a symbol was *already* a
candidate, so a per-symbol trailing average of `vol_5m` averages over an
irregular, selection-biased subset. `vol_5m_pct_of_median_daily` uses the
median 20-day full-day volume, which is defined on every session, and is the
primary measure. `vol_5m_rel_own` is kept beside it with `n_prior_open_obs` so
its shakiness is visible rather than implied.

## Addendum — Phase 2.4: forward-return labelling (2026-08-19)

`src/labelling.py`, `python -m src.cli label`, artifacts
`data/normalized/candidate_labels.parquet` and `data/metadata/labelling.json`.

This is the first module whose output can be wrong rather than merely
incomplete. Each of the 63,698 candidate mornings now carries what happened
over the following 1, 3, 5 and 10 sessions: the return from the entry, the
maximum favourable and adverse excursions, and the same net of the market.

Still not a backtest. No position sizing, no sequencing, no capital constraint,
and — the limit that matters most below — no ability to say whether a stop was
hit before a target.

### Four ways a label goes quietly wrong

**The entry price is raw, the forward prices are adjusted.** Tick prices come
off Breeze unadjusted; `daily_bars_adj` carries an adjusted series. Dividing an
adjusted forward close by a raw entry is correct only while `adj_factor` holds
still, and 5.67% of 10-session windows here cross a factor change. On a 1:10
split that produces a -90% label on a morning nothing happened. The entry is
multiplied onto the adjusted basis before any division. Verified by hand on
IGL's 2024-08-20 1:2 split: raw entry 548.65, `adj_factor` 0.5, adjusted entry
274.3250, +5d label -2.64%, which matches the adjusted tape exactly.

**Forward sessions must be counted on the full daily panel.** A symbol is a
candidate on scattered days, so a `shift(-1)` over candidate rows can reach
across months and call it "+1d". Every forward array is built on
`daily_bars_adj` and joined back afterwards.

**The entry-day high is not reachable from the entry.** Entry is at the end of
the opening window; bhavcopy's daily high may have printed inside it. On 13.7%
of these mornings the day's high was already set by 09:20, and the low on
11.0%. `mfe_*`/`mae_*` therefore start the session *after* entry; the
`*_incl_d0` twins include the entry day and carry that contamination. Both are
kept — discarding the entry-day afternoon is its own distortion.

**A positive mean proves nothing in a rising market.** Every horizon carries
`bench_fwd_ret_*`, the equal-weighted forward return of every symbol trading
that same session, and the `excess_*` difference. Sessions with fewer than 50
priced names get no benchmark rather than one quoted off a handful of stocks.

### The pool is a coin flip, and slightly worse than the market

**What this tests (H001).** Entry at `close_5m`, the last tick of the opening
window. This is *not* the discretionary strategy, which enters at an unknown
point inside the window as the setup develops (H004/H005). It is the narrower,
fully-specified hypothesis "wait until 09:20 and enter at the five-minute
close", adopted so that one unambiguous entry price existed to label against.
Read every number below as a verdict on that hypothesis only:

| horizon | n | mean | median | hit rate | mean MFE | mean MAE | mean excess | t |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| +1d | 63,562 | +0.11% | -0.14% | 47.1% | +2.01% | -1.39% | +0.05% | 4.2 |
| +3d | 63,297 | +0.16% | -0.26% | 46.7% | +3.57% | -2.68% | +0.04% | 2.2 |
| +5d | 63,009 | +0.20% | -0.34% | 46.5% | +4.67% | -3.61% | +0.02% | 1.0 |
| +10d | 62,069 | +0.47% | -0.48% | 46.8% | +6.82% | -5.25% | +0.05% | 1.5 |

The mean is positive while the median is negative at every horizon: a
right-skewed distribution in which fewer than half the mornings work. The
excess is indistinguishable from zero economically — 0.02–0.05%, well inside
any realistic cost — and at +5d it is not distinguishable statistically either.

### Both stated entry filters point the wrong way

This is the finding that changes what comes next. Every cell of the Phase 2.3
cut-point grid has a **negative** excess return at +5d, and tightening either
filter makes it monotonically worse:

| gap band | vol ≥ 5% | vol ≥ 10% | vol ≥ 20% |
| --- | --- | --- | --- |
| [0, 1] | -0.22% (n=10,765) | -0.46% (n=3,425) | -0.95% (n=916) |
| [0, 2] | -0.24% (n=13,114) | -0.51% (n=4,709) | -1.02% (n=1,480) |
| [0, 3] | -0.25% (n=13,636) | -0.52% (n=5,071) | -1.04% (n=1,699) |
| [-1, 2] | -0.17% (n=16,045) | -0.48% (n=5,508) | -0.98% (n=1,678) |

t-statistics run from -3.3 to -7.0, so this is not noise at these sample sizes.
A plain gap floor behaves the same way: excess at +5d is -0.02% above a 0% gap,
-0.13% above 1%, -0.46% above 2%, -0.99% above 3%. The Phase 2.3 question —
"where should the cut-points go?" — has an answer, and the answer is that
raising either one destroys value rather than concentrating it.

### The mechanism: the opening window moves while you measure it

The five minutes between the print that selects a morning and the price you can
act on systematically reverse the gap and run with volume:

| opening volume (% of median daily) | n | mean move to 09:20 | % up |
| --- | --- | --- | --- |
| 0–1% | 9,285 | -0.06% | 43.8% |
| 2.5–5% | 18,820 | -0.01% | 48.8% |
| 10–20% | 4,307 | +0.25% | 59.0% |
| 20–40% | 1,511 | +0.52% | 63.2% |
| > 40% | 770 | +0.73% | 62.9% |

By gap bucket the same measure runs from +1.16% (mornings gapping below -2%
recover) to -1.13% (mornings gapping above +5% give back). Both push the same
way: on exactly the mornings the stated rules select, the entry is worse than
the print that selected it, by more than the forward edge is worth.

That this is a large part of the story is confirmed by re-running the labels
against the untradeable opening print — the heaviest volume bucket's +5d excess
improves from -1.80% to -1.11%, and the 5–10% bucket flips from -0.01% to
+0.07%. It does not rescue the result; it locates it.

### RETRACTED — "the stop as stated is not a stop"

This section originally reported that the stop implied by "below the
opening-candle low" sat a median 0.22% from the entry, was *above* the entry
above p75, and was therefore "already breached before the position exists". **All
of that is withdrawn.** It was a measurement artifact. The claim is restated here
so the retraction is findable by anyone who read the original, rather than the
section being deleted. Full record in `HYPOTHESES.md` under H004.

The error: it paired `om_low`, the low of the **first minute** (09:15–09:16),
with an entry at **close_5m, 09:20** — five minutes later. Nothing ties those two
times together, so the low was never constrained to lie below the entry, and on
mornings where price fell between 09:16 and 09:20 it did not. That produced
"stops above entries" on 31.96% of the panel, up to +6.53% above, which was
reported as a property of the strategy. It is a property of the pairing.

The correct formulation, for any entry time `t`:

    stop_price < running_low_t <= entry_price

`running_low_t` is the minimum low from 09:15:00 through `t`. It includes the
moment being entered on, so it cannot exceed the entry price. Read at the same
`t`, the invariant holds on **0.00%** of the same 63,698 mornings — and on 0 of
464,318 rows across a seven-point grid of entry times. It is now asserted in
code (`entry_window.check_invariant`, and a raise in `labelling.attach_labels`)
rather than assumed.

A second thing the pairing conflated: **the running low being near the day's open
says nothing about the stop being near the entry.** They are separate
measurements, because the entry can sit well above both. Open 100, running low
99.80, entry 103: the low is 0.2% below the open — a textbook tight setup — and
the stop is 3.2% below the entry.

### The stop, measured correctly (H005)

`src/entry_window.py`, `python -m src.cli entry-window`. The window is evaluated
at t ∈ {30, 60, 90, 120, 180, 240, 300}s after 09:15:00, using no information
past `t`, with the stop 0.10% below the running low:

| t | median low vs open | median stop distance | stop wider than 1% |
| --- | --- | --- | --- |
| 30s | -0.04% | -0.16% | 4.2% |
| 60s | -0.14% | -0.29% | 7.0% |
| 120s | -0.26% | -0.36% | 11.5% |
| 300s | -0.38% | -0.47% | 17.2% |

The pool-wide numbers are still small, but they are an average dominated by
mornings that never advanced from the open. Conditioning at t=300s on how far the
entry has moved above the open shows what a real entry would face:

| entry vs open | n | median stop distance | median low vs open |
| --- | --- | --- | --- |
| below -0.5% | 15,719 | -0.27% | -1.09% |
| 0 to +0.5% | 16,606 | -0.49% | -0.13% |
| +0.5 to +1% | 9,443 | -0.83% | 0.00% |
| +1 to +2% | 5,505 | -1.36% | 0.00% |
| above +2% | 1,256 | -2.41% | +0.03% |

On mornings where price is 2%+ above the open, the running low sits *at* the open
(median +0.03%) — exactly the tight setup the rule describes — while the stop is
a perfectly normal 2.41% below the entry. The setup is tight and the risk is not,
which is the case the original pairing made impossible to see.

`t` is still a free variable. This grid is a measurement primitive for
discovering an entry rule, not an entry rule; picking one of these offsets and
calling it the strategy would be the same class of mistake.

### What this does and does not establish

It does not say the strategy fails. It says three narrower things:

1. **Unconditional holding of these candidates has no edge**, and the two
   stated entry filters have a negative one at this entry price.
2. **The burden has shifted entirely onto the exit rules** (H006). Mean MFE at
   +10d is +6.82% against mean MAE of -5.25%; 10.84% of mornings touch +15%
   within ten sessions, 88.25% touch the correctly-paired stop, and **6.49%
   (4,030 mornings) touch both**. Whether a stop-and-target sequence extracts a
   positive expectancy depends on which came first, and **daily bars cannot
   resolve ordering**. That is the single question the full intraday pull would
   answer, and it is now the only reason to run it.
3. **The window is 2023-08 → 2026-08.** The backfill to 2020-04 roughly doubles
   it and spans a different regime. These numbers should be re-read when it
   lands; the command is idempotent.

The obvious untested alternative, given that the first five minutes reverse the
gap: the pool's gap-down mornings are the ones that recover, and the -2% to -1%
gap bucket is the best-performing cell in the table (+0.38% excess at +5d,
52.2% hit rate). That is a different strategy from the one being tested, and it
is a hypothesis generated by this data rather than confirmed by it — logged as
**H007**, `PROPOSED`, to be tested on the backfill with the bucket fixed before
looking. It is the best of ~11 cells chosen after seeing them, so the
multiple-comparisons risk is severe.

### Where the hypotheses live

As of 2026-08-19 every claim in this addendum is also recorded in root-level
`HYPOTHESES.md` with a stable ID (H001–H007), including the retracted one. That
file is the durable ledger; these addenda are the narrative.

---

# Phase 2.5 addendum — exploratory search over opening behaviour (2026-08-19)

`src/behaviour.py`, `src/archetypes.py`, `src/explore.py`.
`python -m src.cli behaviour` then `python -m src.cli explore`.

**Everything in this section is EXPLORATORY / DATA-GENERATED.** It was produced
by the same 2023-08-21 → 2026-08-18 data that would confirm it, so it confirms
nothing. The 2020-04 → 2023-08 backfill is holdout and was not touched;
`explore.fence()` raises on any row outside the exploration window rather than
filtering, so a breach is loud. Ledger entries H008–H016.

## What was asked, and what was built

The brief was to stop treating the strategy as `enter at t=120s if volume > X
and gap > Y` and start treating it as recognition of a developing behaviour:
contraction, favourable trend, constructive open, unusually strong demand that
*keeps arriving*, sellers failing to push price below the open, a path that
looks like accumulation. Two representations were built in parallel:

- **continuous** — 30 features computed causally at ten entry times from the
  1-second tape: activity intensity, persistence, acceleration, path
  orderliness, occupancy above the open, VWAP position, uptick volume share,
  progress-per-unit-volume, higher-lows slope;
- **behavioural** — nine named archetypes assigned from terciles of
  within-session cross-sectional ranks, with a documented precedence ladder.

No threshold in either representation is a free decimal. "High volume" means
"top third of mornings that session". There is nothing to tune, which is the
structural defence against the crevice-fitting the brief warned about.

## Three things the data itself constrains, discovered while building

- **Breeze's `1second` series is not the tape.** Median inter-bar gap 5s (p90
  8s, p99 15s), ~54 bars per morning. There is no 1-second structure to read.
- **~50% of bars carry `volume == 0`** and 94% have OHLC all equal; 27.8% of
  zero-volume bars are followed immediately by a same-price bar carrying volume.
  Volume is smeared several seconds behind price. Window totals are sound,
  1-second volume timing is not. All shape features use 30s buckets.
- **Opening volume decays by default** — pool-mean shares by 30s bucket run
  15.4%, 9.6%, 13.2%, 12.0%, 10.2%, 9.0%, 9.9%, 7.3%, 7.1%, 6.4%. Against a flat
  prior every morning is a "fading spike" and the feature merely re-encodes the
  clock. Persistence is only meaningful relative to the pool on the same day.

## The headline result inverts the brief

The states that most resemble sustained aggressive demand have the **worst**
subsequent five-day excess returns.

| archetype | share | n | +5d excess | clustered t |
| --- | --- | --- | --- | --- |
| persistent_demand | 5.3% | 3,346 | **-0.53%** | -4.38 |
| heavy_vol_no_progress | 8.6% | 5,388 | **-0.27%** | -3.26 |
| absorbed_recovered | 9.8% | 6,212 | -0.12% | -1.40 |
| chaotic | 5.5% | 3,460 | +0.05% | 0.58 |
| orderly_breakout | 7.2% | 4,505 | +0.07% | 0.85 |
| rejected_breakout | 10.9% | 6,843 | +0.09% | 1.14 |
| unremarkable | 49.5% | 31,183 | +0.12% | 2.97 |
| fading_spike | 2.7% | 1,683 | +0.15% | 1.12 |

The continuous representation says the same thing independently: quintile
spreads of -0.54% (total volume), -0.51% (trade frequency), -0.48%
(persistence) and **+0.47%** (concentration — bursty is *better*).

It is a genuine interaction, not total volume restated. Within the heaviest
volume quintile, low persistence gives +0.18% and high persistence -0.63%, a
spread of -0.80% (t=-3.04); in the lightest quintile the same split is -0.29%
and not significant. **Heavy volume is not the bad state. Heavy volume that
keeps arriving is.**

And it is not simply "price already ran up". `persistent_demand` and
`orderly_breakout` both require price above the open; matched on how far and
paired by session, the difference is -0.96% (t=-3.46) at +0.5–1.0% advance and
-0.87% (t=-3.44) at +1–2%.

## Robustness, in the order it was checked

- **Entering earlier does not rescue it.** The volume spread is -0.47% at t=30s
  against -0.54% at t=300s. This is *not* the H003 entry-slippage effect.
- **Not an illiquidity artefact.** The heavy-and-persistent cell is negative in
  all five turnover quintiles, including the most liquid (-0.59%, t=-3.88,
  median turnover Rs 53 cr).
- **Sign-stable** across all three subperiods, both size tiers and 7 of 8
  sectors, and *strengthens* as the archetype bands tighten (-0.46 / -0.53 /
  -0.59 at hi = 0.60 / 0.667 / 0.75).
- **Beats a multiplicity-corrected null.** Over 492 opening-behaviour cells the
  observed max |t| is 6.37 against a within-date permutation null whose max |t|
  has p95 = 3.17.

## Two defects found in the existing pipeline, which matter more than the above

**The screener selects a morning using that morning's own closing price
(H015).** Indicators on the candidate row for date D come from date D's close;
the entry is 09:20 on date D. `require_above_ema_mid=True` means *every*
candidate morning is a session that closed above its 50-day EMA, and the
contraction filters require the entry day itself to have been quiet. This
contaminates the pool underlying H001–H006 as well.

Splitting the +5d excess at the entry-day close:

| | total | 09:20 → day-D close | day-D close → D+5 |
| --- | --- | --- | --- |
| volume q5 − q1 | -0.54% | **-0.35%** | -0.19% |
| persistent_demand | -0.53% | **-0.39%** (t=-8.2) | -0.15% (t=-1.4) |
| heavy_vol_no_progress | -0.27% | -0.11% (t=-3.2) | **-0.17%** (t=-2.3) |

**About two thirds of the headline effect sits in the segment the screen
conditions on.** What survives into genuinely forward territory is -0.15% to
-0.30%, and only `heavy_vol_no_progress` is majority-forward and nominally
significant. On the forward-only outcome the whole behavioural family still
beats its null, but marginally: observed max |t| 4.99 against null p95 3.91.

**Correction (2026-08-19, after review).** The paragraph that stood here argued
a real intraday fade was "at least as plausible" as selection, on the strength of
the `above_ema_mid` slack test (-0.28% where the day-D close is within 0.5% of
the 50-EMA against -0.43% where it is more than 10% above). That test exonerates
one filter and says nothing about the **contraction** family, which is the one
that can invert the sign rather than merely inflate it: a persistent-demand
morning that kept running all day has a wide day-D range, fails contraction, and
is excluded from the pool, while one that faded into a narrow range is kept. The
pool retains the failures and discards the successes. That mechanism alone can
manufacture the entire inversion, and it is now the **leading** explanation. The
intraday-fade reading is secondary.

Consistent with it: `persistent_demand`'s forward-only effect is -0.15% at
t≈-1.4 — not convincing. The headline -0.53% is mostly entry-day.

**Phase 2.4's t-statistics treat mornings as independent (H016).** They are
~650 sessions, not 63,698 draws. The inflation is about 2.9x: H001's headline
"+1d excess t=4.2" is **t≈1.4** clustered, and H002's -3.3 to -7.0 become
roughly -1.1 to -2.4. This strengthens H001's rejection rather than weakening it.

## Hypotheses answered

- **H009 rejected as stated, reverse supported.** Persistence is bad, not good.
- **H010 inconclusive.** `time_above_open_frac` fixes the Phase 2.3 censoring
  (median 0.66, no pile-up at zero) but predicts essentially nothing: -0.02%
  spread. A dwell-time lookahead was found and fixed here; correcting it did not
  change the conclusion.
- **H011 partially supported.** `move_per_vol` is monotone across quintiles
  (+0.39%) and `heavy_vol_no_progress` is the only archetype whose effect is
  majority-forward. The microstructure measures (VWAP position, uptick share)
  are flat.
- **H012 rejected.** Path efficiency has the wrong sign and negligible size.
  Tape *tidiness* does not predict; tape *activity* weakly does.
- **H013 supported as a representation.** The archetypes recover the continuous
  findings and name them, and the naming is what makes the result arguable with
  a discretionary trader.
- **H014 inconclusive.** Entry time does nothing unconditionally (flat +0.02% to
  +0.05% across t, clustered t below 1.7), but the *state* evolves — 72.8%
  archetype persistence over 30s, and only 48% of mornings ever labelled
  `persistent_demand` still are at t=300s. No `setup_quality(t)` model was
  fitted: with the surviving forward effect at ~-0.2% and H015 unresolved, that
  would be fitting an artefact with more parameters.

## Three limits on everything above, beyond the contamination

- **The outcome variable is wrong for this strategy.** These results ask "what
  is the excess return at D+5". The payoff is enter → stop losers quickly → a
  minority run +15-20% → sell half → trail. A pool where 70% of setups end -3%
  by D+5 but exit at -1% on the stop, and 10% reach +18% before giving most of
  it back, reads as a bad strategy under this label and a profitable one under
  the actual rule. H006 remains the unresolved question and needs a stop/target
  payoff simulator, not more features.
- **"Persistent demand" names a mechanism the data cannot see.** Volume is not
  buying volume. Unusually much trading is equally consistent with a crowded
  news event, two-sided disagreement, breakout chasers, institutions unloading
  into eager buyers, or exhaustion. `heavy_vol_no_progress` is the one archetype
  whose name matches what is measured, and it is also the one that survives.
- **The pool is far broader than the trader.** If the uncle sees ~50 plausible
  names a morning and trades one, ~98% of these mornings are material he would
  reject. No unconditional edge across the whole pool is the expected result,
  not evidence against him. Reconstructing his decision boundary needs a sample
  of his actual dated picks.

## What this is worth

A short list of frozen, testable statements for the backfill, and one pipeline
defect that has to be decided on first. It is **not** an edge: the largest
survivor is about -0.2% at five days, it is a short rather than a long, and the
strategy under investigation is a long-only swing trade. The most useful output
for the conversation with the uncle is the inversion itself — the opening states
that look most like institutional accumulation are, in this pool, the ones that
do worst, and that is a claim he can push back on from experience.
