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

---

# Addendum — Phase 2.8: reverse discovery (2026-08-20)

**Everything in this section is EXPLORATORY / DATA-GENERATED.** It was produced
on the exploration window (2023-08-21 → 2026-08-18) and confirms nothing. The
2020-2023 backfill is holdout and `explore.fence()` raises rather than filters.

## What was asked, and what was done differently

Previous phases ran forwards — propose a rule, measure its forward return,
reject it. That loop has now rejected the 09:20 entry (H001), both stated
filters and every tightening of them (H002), and the traded-payoff defence of
all three (H017). The instruction for this phase was to invert it: define
path-aware outcome kinds, find matched failures for each strong winner using
only decision-time information, and search backwards for what separates them.

New code: `src/context.py` (market regime, breakout location, relative strength
— the three families no existing panel could see), `src/discovery.py` (outcome
taxonomy, matched controls, discriminant search, clustering, regime splits,
ranking, freezing), `python -m src.cli context` and `python -m src.cli discover`,
plus `tests/test_context.py` and `tests/test_discovery.py` (20 tests; suite now
168).

## The pool had to be rebuilt first, and it is much larger now

The re-pull under the corrected screen finished for the exploration era.
`opening_features.parquet` was stale, which silently cut candidate-panel
coverage to 69.4% until it was rebuilt.

| | before | after |
| --- | --- | --- |
| candidate panel | 63,698 rows | **140,265** (92.8% coverage) |
| behavioural panel, exploration window | 63,698 mornings | **85,065** |
| sessions | 650 | 676 |

**The exploration window is 100% fetched.** All 2,955 still-missing pairs are in
the 2020-2023 holdout, which stands at 86.7% of its new candidates — the pull
process on the server hung at 16:03 BST with 4,705 pairs outstanding and needs a
fresh Breeze token to finish. That gap matters for the holdout test, not for
this phase.

### One more lookahead, found and fixed

`behaviour.py` normalised opening volume, churn and chaos by `median_vol_20` and
`atr_pct` read off the **unlagged** metrics panel. Both are 20-session rolling
windows that include date D's own full-day volume and range. A lookahead inside
a *denominator* is the easiest kind to miss, because the feature it contaminates
does not look like a price feature at all. Now reads `screen_metrics_asof`.

## The outcome taxonomy corrected itself before it was used

Nine path-aware states, priced under the strategy's own exit rule rather than
assumed to be meaningful (H018). Two things came out of that:

**The stop as stated is not a stop.** At t=180s the running-low stop has a
median distance of **0.41%** against a median ATR of **3.37%** — one eighth of a
normal day's range. Risk is floored at 0.5 x ATR, lifting median R to 1.70%.

**A state called `clean_winner` earned +0.05% excess.** Defined as a large MFE
reached quickly, with no requirement that it hold, it filled the target on 10.2%
of trades and made nothing. It was split into `spike_and_fade` and a
`clean_winner` that must still be positive at the horizon. A path taxonomy is as
capable of being wrong as a return label; the fix is to price every state before
using it.

The three winner states are worth +13.31%, +2.86% and +1.29% excess; all six
failure states sit between -0.31% and -1.65%. **Winners are slow**: `monster`
takes a median 8 sessions to peak, `slow_winner` 7. Nothing in this pool rewards
an immediate move.

**The largest single block has no name in the brief.** `shaken_out` — stopped
out, and *then* the stock moved 3%+ — is **27.7% of all mornings**, median MFE
+7.53%. More than one morning in four is a stop problem rather than a selection
problem.

## The methodological finding is the biggest one

Same-session matching starves in this pool: a median of 82 candidates per
session across 20 sectors leaves 3 rows per cell. Widening the control band to
+/-2 sessions raised matched winners from 2,446 to 4,105 with better balance —
and **tripled every headline contrast**:

| matching band | sets | `open_base_pos_20` t |
| --- | --- | --- |
| same session | 2,446 | -2.89 |
| +/-1 session | 3,811 | **-15.13** |
| +/-2 sessions | 4,105 | **-16.04** |

A real effect does not quadruple when one day of slack is added to a matching
rule. Measured: under a +/-2 band the winner's own session sits **0.45% lower in
the equal-weighted market index** than its controls' sessions, on 71.2% of sets,
because winners cluster on local market troughs. Under same-session matching
that offset is exactly zero.

Had this phase reported the +/-2 numbers it would have announced a large,
significant, sign-stable breakout-location effect that is mostly a restatement
of "the winner's morning was lower in the market". `date_window` now defaults to
0 and `discovery.market_offset` prints the diagnostic on every run.

**This is the third time a convenience taken to get more usable rows imported
information the comparison was meant to exclude** — after the screener lookahead
(H015) and the naive t-statistics (H016).

## What actually survives

With the market held exactly fixed, 68 features, 2,446 matched sets, and a bar
set at the 95th percentile of the permuted maximum |t| (3.36, not 1.96):

| feature | family | std. diff | t | clears bar |
| --- | --- | --- | --- | --- |
| `px_vs_ema_fast` | stock trend | -0.107 | -4.27 | yes |
| `px_vs_ema_mid` | stock trend | -0.107 | -4.10 | yes |
| `deliv_pct` | price/volume | +0.081 | 3.16 | no |
| `high_vs_open_pct` | gap/open | -0.068 | -3.11 | no |
| `open_base_pos_20` | breakout location | -0.074 | -2.89 | no |

Two features, saying the same thing: **winners sat slightly further below their
own short-term moving averages.** Stable across calendar thirds, sectors, market
regimes, all nine sensitivity variants, and at t=60s and t=300s. Neither
replicates in the tight tier, which holds prior run-up, base width, gap and
opening volume fixed as well — though that tier has only 608 sets and its
failure is weak evidence.

**In decision units the effect is small.** Win rate 17.15% in the lowest
quintile against 14.65% in the highest, on a 16.13% base: a lift of 1.06 to
0.91. The gap between a t of -4.3 and a lift of 1.06 is the whole lesson — a
paired design over thousands of sets detects shifts far below anything
tradeable, and a significance test alone would have been read as a result.

**The direction is against the breakout premise.** Every surviving and
near-surviving contrast points the same way: winners were further below their
moving averages, lower in their base, further below their 20- and 50-day highs,
with weaker 60-day returns and relative strength. This pool does not reward
proximity to a breakout level. It is not merely "more room to travel" — the
tilt holds inside every quartile of extension, at the same slope (H021), and
`atr_pct` is matched and balanced to 0.03.

## Breakouts do not need a trending market — the sign is backwards

| market state (as of D-1) | sessions | win rate | vs pool |
| --- | --- | --- | --- |
| trending up | 168 | 14.27% | 0.88 |
| trending down | 36 | 12.77% | 0.79 |
| chop / sideways | 447 | **17.67%** | 1.10 |

Monotone on the continuous trend measure too: 17.97% in the least trending
tercile against 15.05% in the most. **And the largest effect anywhere in this
phase is market volatility, not any stock-level feature** — 11.71% in the bottom
tercile against 20.23% in the top, a 1.7x spread against 1.06x for the best
stock feature.

That last one carries a mechanical caveat that must travel with it: winners are
defined by excursion bars and everything moves more in a volatile market. `R` is
floored on each stock's own ATR, but market-wide volatility is not controlled.
It is a fact about *when* the outcome states occur, not an established edge.

The base-position tilt has the same slope in both regimes, so there is no "this
setup works only when the market trends" structure — there is a market state
that lifts all the win rates together.

## Clustering found no second archetype

k-means (k=4) on the winners, then every morning assigned to its nearest winner
centroid: best lift 1.22x at a 2% radius (n=351), 1.14x at 5%, 1.07x at 10%.
Lift decaying as the neighbourhood grows is the signature of fitting a small
sample. Measured in sample, against centroids built from the winners themselves,
the multivariate combination does not beat the best single feature by enough to
matter.

## Limits, in the order they bite

1. **Only 2,446 of 10,743 winners matched (23%).** The matched winners are far
   more liquid (median turnover 22.7 cr against 6.1 cr) and less monster-heavy
   (26.8% against 37.3%). The contrast describes winners that *have* a
   lookalike failure on their own session, which is the right subsample for the
   question and a narrow one.
2. **One market.** 2023-2026 is a single rising regime with 447 chop sessions
   and only 36 trending-down ones. The `trending_down` row is 556 mornings.
3. **The pool is still ~98% material a discretionary trader would reject**
   (`PLAN.md` §7). No unconditional edge across 66,597 screened mornings is the
   expected result, not evidence against the strategy.
4. **The breakout level is crude** — the highest high over 20 or 50 sessions,
   not a drawn chart level. Both lookbacks agree, which is some comfort.
5. **Nothing here is out of sample.** Four structures and two near-misses are
   frozen in `data/metadata/discovery_frozen.json` with the exact configs needed
   to replay them.

## What this phase is worth

It did not find a profitable subset. What it produced is: a validated outcome
taxonomy that prices its own labels; a matched-control design with a correct
null; one measured confound that would have manufactured a headline finding; a
clear negative on the trending-market hypothesis; and a shortlist small enough
to be honest about.

The most actionable observation is not a setup at all — it is that 27.7% of
mornings are stopped out before a move of 3%+ that then happens. That is a stop
question, and this phase deliberately did not chase it.

---

# Addendum — Phase 2.9: the shotgun, and the first thing that works (2026-08-20)

**EXPLORATORY.** Run on explicit instruction to try a lot of things and not
worry about overfitting, on the exploration window only. ~1,500 configurations
were searched on the same window they are measured on. The 2020-2023 holdout is
untouched. Nothing here is confirmed.

## The framing that was wrong all along

Every phase until now asked *"do the mornings passing this filter beat the
market on average"*. Nine hypotheses answered no. But that is not the strategy:
a discretionary trader looks at a morning's candidates and trades **one**. A
pool with zero average edge can still contain a usable ranking, and the two
questions have different answers.

They do here. `src/shotgun.py`, `python -m src.cli shotgun`. H024.

## What did not work

- **Exits alone.** 720 configurations, both directions, over the whole pool.
  The best *long* excess is -0.155%. Longs make money raw (+0.69% over 20
  sessions) and lose to the market — that is beta, not edge.
- **Shorts.** The only configs positive on both raw and excess are shorts, best
  +0.29% excess on +0.13% raw. Untradeable in Indian mid-caps and inside the
  noise. Recorded, not pursued.

Two measurement errors were caught in this sweep and both would have produced a
false positive on the first pass:

- **The benchmark sign must follow the position.** Alpha is `r - m` for a long
  and `r + m` for a short. Subtracting the market from a short charges it twice
  and, in a single rising sample, ranks shorts by how badly the market did.
- **`trail_from`.** Trailing from entry rather than from the scale-out is a
  different rule — 47% of trades exiting on the trail at a median hold of 2
  sessions against 5 — and conflating them broke the first validation against
  `payoff.simulate`. Corrected, the two simulators agree at r = 0.981 with an
  identical exit mix.

## What worked

Two daily, as-of features, ranked within each session and averaged equally:

- `dist_52w_high` — proximity to the 52-week high (top decile is within ~3.7%)
- `deliv_pct` — delivery percentage, the one feature that also survived the
  Phase 2.8 matched contrast

Top N per session, enter at the open, **no stop**, hold 30 sessions.

**Per trade** (top 5/day, n=3,209): +1.40% vs the equal-weighted market
(t=5.69), +1.32% vs the same-day pool average (t=6.38), raw +3.19%.

**Portfolio, daily mark-to-market, 0.40% round-trip cost:**

| book | CAGR | max DD | Sharpe |
| --- | --- | --- | --- |
| all candidates, no selection | 7.96% | -24.6% | 0.54 |
| top 3 / day | 22.71% | -13.5% | 1.70 |
| **top 5 / day** | **26.83%** | **-12.2%** | **1.93** |
| top 10 / day | 25.20% | -14.3% | 1.76 |
| top 50 / day | 17.03% | -20.4% | 1.11 |
| equal-weighted market | 18.33% | -24.3% | 1.02 |

The decay in N is monotone and smooth — the edge concentrates at the top and
dilutes into the market by top-50. That is what a real ranking looks like; a
fitted crevice does not degrade gracefully.

Year by year against the market: 2023 +22.5% vs +24.5%, 2024 +28.6% vs +29.2%,
**2025 -1.1% vs -8.3%**, **2026 +20.2% vs +5.9%**. It matches the market when
the market is strong and separates when it is not, which is where the halved
drawdown comes from.

## The three checks that matter more than the headline

**It is selection, not beta.** Benchmarked against the same-day mean of every
other screened candidate under the identical exit rule — which removes the
pool's own beta, size and style exactly — all 60 tested cells stay positive,
best +1.25% at t=8.28.

**It beats its own permutation null.** Shuffling the score within each session,
holding pool, dates, exit rule and pick count fixed, 400 times: null p95
+0.387%, null max +0.665%, observed **+1.322%** — beating 100% of shuffles.

**The contraction screen is load-bearing.** The identical ranking applied
elsewhere:

| where the ranking runs | CAGR | Sharpe |
| --- | --- | --- |
| inside the contraction screen | 25.86% | 1.64 |
| full tradeable universe | 8.75% | 0.65 |
| only what the screen rejected | 9.40% | 0.69 |

Neither half works alone — the screened pool returns 7.96% against a 16-18%
market, and the ranking on the open universe returns 8.75%. Together, 25.9%.
**That is an interaction, not a sum**, and it is close to the uncle's stated
setup: volatility contraction, near the highs, strong delivery. This is the
first evidence in the project that his screen is doing something.

## The finding that costs the most to accept

**The 1-second tick data contributes nothing to the only thing that works.**
Entering at the 09:15 opening print instead of the tick price at t=180s gives
CAGR 26.39% against 26.83%, per-trade excess +1.37% against +1.40%. The score is
built entirely from daily as-of features.

180,000 API calls, the daily-token blocker, three phases of behavioural
features, an entry-time grid and a nine-state opening taxonomy are all
irrelevant to it. That should not be softened — but it has an upside worth as
much as the cost: the rule can be tested on the full daily history and the full
universe, and its holdout test does not depend on tick coverage at all.

## What this is not

- **Not out of sample.** ~1,500 configurations searched on the window they are
  measured on. The permutation null covers the ranking *given* the feature set;
  it does not cover the search that chose the features.
- **Not the uncle's strategy.** No stop (Phase 2.8's `shaken_out` says the stop
  is what breaks it), a 30-session hold rather than a +15% target and trail, and
  ~142 concurrent positions rather than one name a day.
- **One market.** Four years, one of them partial, one broad regime.

## Data state

The holdout pull finished at 21:21 BST 2026-08-19 — 42,703 of 42,703 pairs
settled, 2,290 with data, 0 errors. The 2020-2023 backfill is complete and
synced (1,445 session files). It has never been read.

---

# Addendum — Phase 3: a family, a stress test, and the holdout (2026-08-20)

**The holdout has been opened. The verdict is FAIL, and H024 — the project's
only positive result — does not replicate.**

## What was asked

Generate three to five more structurally distinct profitable candidates on the
exploration set, stress-test them across purged temporal blocks and regimes,
freeze everything with exact definitions and a family-level pass criterion, and
then open the 2020-2023 holdout once.

## Why a family and not a better single rule

H024 came out of ~1,500 configurations searched on the window that measured it.
One survivor from a sweep that wide is the shape of a thing that might be there,
not the thing. The cheapest way to find out is to ask whether anything *else*
works, and to require the something-elses to be mechanically unrelated — a
different information source, a different selection mechanism, a different exit,
a different portfolio. Five correlated variants of one ranking passing a holdout
is one result. Five unrelated rules passing is five, and the family-level claim
("selection inside this screen carries information") is what is actually at
stake.

## The frame changed, and the tick data was dropped

`src/family.py` builds its pool from the as-of screen alone and enters at date
D's adjusted **opening print**. H024 measured the tick entry at 26.8% CAGR
against the opening print's 26.4%, so the 1-second panel buys 0.4pp and costs
the ability to test anything at all before 2023. Three things follow: the
holdout window is built by the identical code path; the pool is the screen
rather than "the screened mornings a tick pull happened to cover"; and every
scoring feature is strictly from D-1 — the date-D open is the entry, so using it
as a feature would mean acting on a price at the instant it prints. That
excludes Phase 2.8's top feature (`open_base_pos_20`) and is a real cost, paid
for rules that are unambiguously implementable.

On the exploration window the daily-entry frame reproduces H024 at +1.06% vs
the same-day pool (t=5.32) and CAGR 23.50% against the tick version's +1.32%
and 26.83%. Different pool (69,536 screened mornings against 68,333 tick-joined
ones), same result.

## The search: 234 configurations over seven axes, one kept per axis

| axis | what it claims | configs | best in sample |
| --- | --- | --- | --- |
| B pullback | the weakest candidate in the screen wins | 45 | nothing cleared |
| C relative strength | strength vs market and sector wins | 45 | +1.230% (t=4.76), SR 1.27 |
| D base quality | the tightest base wins | 45 | +0.715% (t=3.28), SR 1.51 |
| E regime timing | hold the pool only in some market states | 9 | +1.107% (t=3.79), SR 0.69 |
| F exit structure | the exit carries it, no selection | 72 | nothing cleared |
| G instrument type | less liquid, cheaper, more volatile wins | 9 | +0.924% (t=3.28), SR 1.16 |
| H sector capped | same score, one name per sector | 9 | +0.548% (t=2.74), SR 1.01 |

The objective was fixed before the search: portfolio Sharpe subject to positive
market-excess at clustered t≥2, one winner kept per axis. Sharpe rather than
CAGR because the same yardstick has to serve a concentrated long book and a
partly-invested one, and because it is the quantity the holdout bar is written
in — the search and the test are measured on one ruler.

**The two axes that failed are results.** No exit rule applied to the whole pool
beats the market (H029), on a different pool and entry from the sweep that first
said so. And the matched-pair contrast that Phase 2.8 spent its whole budget on
does not become a selection rule (H025) — a 0.107-standardised shift detected by
a paired design is not tradeable, exactly as H019's own write-up warned.

## A lookahead, caught by a test, one step before the holdout

The first version of axis G won on `size_tier_rank` at +1.312% (t=5.11) and
Sharpe 1.46. Size tiers come from NSE's **current** index constituent lists, so
a 2021 row carries 2026's membership — and membership is assigned on market cap,
which is to say on the returns being scored. `test_every_frozen_feature_is_a_d_
minus_one_quantity` failed on it, the axis was re-run without it, and its winner
changed. This is the fourth lookahead in this project found inside something
that is not a price: after the screen's own close (H015), the `median_vol_20`
denominator, and `time_above_open_frac`'s dwell time. **The pattern is now
unmistakable — the dangerous ones are never in the numerator.**

## Purged blocks, and the measurement that changed an answer

Six contiguous blocks across the exploration window, with the last 30 sessions
of each dropped so no trade's holding window crosses a boundary (a 30-session
hold makes abutting blocks share information, and "positive in five of six"
would otherwise be a fiction). It costs 35% of the sample.

Separately, portfolio statistics were moved onto a **span** convention: cash
sessions earn zero and still count against the clock, measured from a book's
first live session to its last. The old convention annualised over the sessions
a book *held* something, which flatters a rule that sits in cash — E's timing
rule reported 14.11% against a market at 18.24% and became 10.18% against 15.11%
once it was charged for being out. For an always-invested rule the two agree
exactly.

## What was frozen, and what the bar was

Two members: **A** (H024, unchanged) and **C** (relative strength). Six
information-only rules — the axis winners that failed either the in-sample gate
or the stress test — replayed on the holdout for what they say about the
in-sample screen, and barred by construction from changing the verdict.

The members share almost nothing: **9.6% Jaccard overlap** in the symbol-days
they trade, with a 0.81 correlation of daily book returns that is market beta
rather than agreement.

The bar, written before the window was opened. Per member: positive
market-excess at clustered t≥2; portfolio Sharpe above the market's over the
same span at 0.40% round trip; at least a third of the exploration alpha
retained. Family PASS needs the union book to clear the first two *and* both
members to pass; PARTIAL if only the union book does; FAIL otherwise, and a FAIL
drops the family without re-tuning.

## The holdout

2020-12-29 → 2023-07-06, 59,844 screened mornings over 575 sessions. It starts
at the archive's 250th session so every rolling window is full, and its last
entry is purged by 30 sessions so nothing settles on exploration prices.

| | exploration | holdout | retention |
| --- | --- | --- | --- |
| A momentum location (H024) | +1.172% (t=4.83) | **-0.627% (t=-1.98)** | -0.53x |
| C relative strength | +1.230% (t=4.76) | **+1.366% (t=3.31)** | 1.11x |
| union book | +1.106% (t=5.60) | +0.359% (t=1.17) | 0.32x |
| equal-weighted market | 18.25% CAGR, SR 1.02 | **41.78% CAGR, SR 2.25** | |

**Members passing: 0 of 2. VERDICT: FAIL.**

## Two things happened and they must not be blurred

**H024 does not replicate.** Negative, at t=-1.98, with the sign of its alpha
reversed. The first thing this project found that worked, does not work.

**Everything else was killed by the second clause, in the hardest possible
window.** The equal-weighted market compounded at 41.78% at a Sharpe of 2.25
over the holdout — the post-COVID small-cap melt-up. C matched its return
(41.50%) with a deeper drawdown, so its Sharpe (1.74) sits below buy-and-hold.
Against the same-day pool, which is the selection question and is immune to what
the market did, C beat it by **+1.73% a trade at t=4.98** — a *larger* effect
than in the window it was found in.

That clause is not being reopened. It was chosen before the run because "beats
the index" is the question a person with money faces, and a bar applied only
when it is passed is not a bar. But the split says exactly which claim survived:

- **Selection inside the screen carries out-of-sample information.** C at
  +1.73% vs pool (t=4.98), and the information-only replays agree — G at +2.66%
  (t=6.92), H at +1.38% (t=5.22).
- **Turning that information into a portfolio that beats buy-and-hold did not
  work**, in either window, for any rule tested.

## The methodological result: the stress test did not predict anything

| rule | stress verdict | holdout alpha |
| --- | --- | --- |
| A momentum location | survives | -0.627% |
| C relative strength | survives | +1.366% |
| D base quality | killed | -0.645% |
| G instrument type | killed | **+2.298%** |
| H sector capped | killed | +1.016% |

Two of the three rules the purged-block filter killed were positive out of
sample, one of them the strongest result in the phase; one of the two it kept
was negative. Six blocks of ~110 sessions hold one regime apiece, so
leave-one-block-out is a test of regime uniformity rather than of robustness,
and a rule that pays in some regimes and not others is what a real rule looks
like. **Do not use it as a promotion gate again** (n = 6 rules; a direction, not
a measurement).

## Where the pool's return actually lives, and why it is not tradeable

The strongest out-of-sample rule in the phase ranks on illiquidity: least
traded, lowest priced. +2.298% vs market (t=6.16), CAGR 54.89% against 41.78%.
Its picks have a **median 20-day traded value of ₹0.71 crore** — about ₹7
million a day — with 93% outside the top 500 and 74% of picks in one
unclassified sector. At a 2.00% round trip, which is a fairer number for names
that thin, the in-sample book returns 8.41% against a market at 18.25%. It is a
measurement of where the return sits, not a strategy.

## Data state

The 2020-2023 backfill has been read. `data/metadata/family_holdout.json` is the
record, and `family.holdout()` refuses to run a *different* family against it.
The only untainted data this project has left is the future: sessions after
2026-08-18. Anything after this is a forward test.

---

# Phase 4 — resilience in market declines (H034-H036)

**Exploratory, on 2023-08-21 → 2026-08-18 only.** A new family, unrelated to
everything above: no tick data, no opening window, no screen. A daily
cross-sectional signal over ~650 liquid names a session. Code in
`src/resilience.py`, causality tests in `tests/test_resilience.py`, numbers in
`data/metadata/resilience.json`, reproduced by `python -m src.resilience`.

## The question, and the answer

Rank liquid stocks inside each sector by how well they held up, relative to what
their beta and sector predicted, during a broad-market decline identified using
only information available as of that morning. Does higher resilience buy higher
subsequent returns?

**No — and the gradient runs the other way.** Inside a decline, the *least*
resilient decile outperforms over the following 5-20 sessions and the most
resilient underperforms. It is short-horizon reversal, and it is monotone in how
deep the decline has been: below −6% over ten sessions the decile spread is
−0.70% at h=5 (t=−2.83) and −1.14% at h=10 (t=−3.65); above +1% it turns
positive and insignificant.

The literal form of the brief — quintiles inside each sector, sector-excess
returns — says the same thing with the cleanest statistic in the study: rank-IC
**−0.033 (t=−4.85)** at h=5, positive on 32% of sessions.

## Why this is a finding and not a strategy

Three separate reasons, and each is sufficient on its own.

1. **It does not clear the multiplicity bar.** Over the 20-cell grid of five
   market strata × four horizons, the permuted maximum |t| has median 2.31 and
   p95 3.43; the observed maximum is 2.45, p = 0.42. What is convincing here is
   the *consistency of the sign* — negative at every horizon, both decline
   windows, both market proxies, three excess-return definitions, six of six
   leave-one-episode-out drops, and 24 of 35 non-overlapping sessions (sign test
   p = 0.041) — not any individual t-statistic.
2. **The whole gross spread is smaller than the cost of collecting it.** At
   0.40% round trip the decile long-short nets −0.38% a trade at h=5. Long-only
   decile 1 nets −0.11% at h=5, +0.10% at h=10, +0.07% at h=20. That is the
   third time in this project (see H030) that a real cross-sectional gradient
   has turned out to be smaller than its own transaction costs.
3. **Most of it is a beta trade, and specifically one that no pre-decline beta
   can see.** Decile 1's fitted beta is 0.93 and decile 10's is 1.13, but over
   the next five sessions decile 1 *realises* 1.14 and decile 10 realises 1.04.
   Split the decline stratum on the market's realised forward return (NON_CAUSAL
   — this conditions on the future) and the beta-adjusted spread flips sign:
   −1.06% (t=−4.57) when the market rebounds, **+0.49% (t=+2.33)** when it keeps
   falling. When the market does not bounce, resilience does predict outperfor-
   mance, exactly as the hypothesis says. There is a residual after beta — a
   +0.18% vs −0.16% intercept difference over five sessions — but it is small.

## The control that will not resolve

The beta and sector adjustment earns nothing observable. Ranking on the plain
window return is at least as strong (−0.665%, t=−3.09, against −0.422%,
t=−2.45), and the two scores are collinear enough that fitting both leaves
neither estimable (resid +1.07 t=0.90, raw −1.68 t=−1.29). **This data cannot
separate "held up better than beta predicted" from "fell less".** Anyone
returning to this should design the separation in — orthogonalise the residual
against the raw drawdown before ranking, and accept the much thinner effective
sample that leaves — rather than hoping a regression will do it afterwards.

The other confounds came out clean. Trailing volatility strengthens the
resilience coefficient rather than absorbing it; pre-window relative momentum,
measured over 60 sessions sharing none with the decline window, is flat
(t=−0.12); turnover is flat (t=−0.23), so unlike H030 this is not illiquidity
wearing a disguise. And requiring a sector label — the `size_tier_rank` class of
snapshot lookahead — moves nothing: −0.422% on all liquid names against −0.435%
on the sector-labelled 84.4%.

## What this cost, in holdout terms: nothing, and that is the problem

Per H033 the 2020-2023 backfill is spent, so this ran on the exploration window
alone and **cannot be confirmed on anything**. The 2023-2026 window contains
roughly six to nine distinct decline episodes; the effective sample is those
episodes, not the 171 sessions and certainly not the 110,085 rows. Every number
above is data-generated. The only untainted data is still the future.

## Phase 4 addendum — the semi-stale replication, and what the score is made of

**Run once, on a spec frozen and hashed beforehand** (`resilience_frozen.json`,
hash `6738a48730b093ee`; `resilience.semi_stale()` re-hashes before it reads
anything). Window 2020-04-16 → 2023-07-21, 814 sessions, 163 in the decline
stratum. Result in `data/metadata/resilience_semi_stale.json`.

**SEMI-STALE, not out of sample.** 2020-2023 was opened once already against the
opening-window family (H033). Nothing that test learned bears on a
cross-sectional reversal signal, which is why it was worth spending — but the
window is no longer virgin and the label stays on the result. **The COVID crash
itself is not in this window**: there is no history in front of February 2020 to
fit a 120-session beta on, so what it contains is the post-COVID recovery, the
2021 run and the 2022 correction.

**Verdict on the frozen bar: PASS.** Both gated horizons negative, one at
|t| ≥ 2, depth gradient preserved. **And the bar had a clause that was too
weak** — h=10 satisfied "negative" with −0.037%, a number indistinguishable from
zero. It should have demanded a fraction of the exploration effect retained, the
way `family.PASS_CRITERION` does. Recorded as a lesson about writing bars; the
verdict is not revised, because a bar applied only when it is passed is not a
bar.

**What actually replicated is narrower than Phase 4 claimed.**

| | exploration | semi-stale |
| --- | --- | --- |
| h=1 decile spread | −0.125% (t −2.08) | −0.228% (t −2.58) |
| h=5 decile spread | −0.422% (t −2.45) | −0.484% (t −2.00) |
| h=10 | −0.561% (t −2.05) | −0.037% (t −0.10) |
| h=20 | −0.398% (t −0.83) | +0.367% (t +0.72) |
| deepest band (<−6%), h=5 | −0.702% (t −2.83) | −1.220% (t −3.03) |
| within-sector rank-IC, h=5 | −0.033 (t −4.85) | −0.042 (t −4.99) |
| k=20 window, h=5 | −0.318% (t −1.28) | −0.082% (t −0.34) |

**A one-to-five session reversal that deepens with the decline** — that is what
survives. The ten- and twenty-session horizons and the whole 20-session decline
window do not. Both halves are worth carrying: an effect that replicates at two
horizons and dies at two others is a narrower effect, not a refuted one, and
also not one to quote at the horizons where it died.

### What the score is actually made of (H038)

The H036 question — does the beta/sector adjustment earn anything over the plain
drawdown — has an algebraic answer, and the regression that could not resolve it
was asking the wrong way. Within one session `resid_i = r_i − beta_i · r_mkt`
with `r_mkt` constant, so projecting `resid` off `r_i` leaves only `−r_mkt`
times the part of `beta_i` that `r_i` does not explain. **Conditional on how far
a stock fell, "held up better than its beta predicted" is nothing but beta.**
Measured, not assumed: the per-session correlation with `−r_mkt · beta⊥drawdown`
is **1.000000 on 100% of decline sessions**.

So the score is two bets with opposite signs stapled together, which is why it
is weaker than either:

| component | exploration h=5 | semi-stale h=5 | semi-stale h=20 |
| --- | --- | --- | --- |
| drawdown ⊥ residual | −0.904% (ρ −0.95) | −0.250% (ρ −0.48) | −1.649% (ρ −0.84) |
| beta ⊥ drawdown | +0.555% (ρ +0.90) | −0.018% (ρ −0.02) | +1.485% (ρ +0.79) |
| beta alone | +0.759% (ρ +0.96) | +0.260% (ρ +0.18) | +1.745% (ρ +0.81) |

The "resilience proper" component is indistinguishable from ranking on beta, in
both windows and at every horizon, exactly as the algebra requires. **Do not
build a resilience score by subtracting beta and then ranking; that is a beta
sort wearing a name that suggests it is not one.**

### The cost verdict did not move

Long-only decile 1 earns +0.339% market-excess at h=5 in the semi-stale window
and nets **−0.061%** at 0.40% round trip. Replication changed the confidence in
the gradient and nothing at all about whether it can be traded.

## Data state — updated 2026-08-20

The 2020-2023 window has now been read **twice**: once by `family.holdout()`
against the opening-window family (H033) and once by `resilience.semi_stale()`
against the frozen resilience spec (H037). It is spent for any purpose. The only
untainted data this project has is sessions after 2026-08-18.
