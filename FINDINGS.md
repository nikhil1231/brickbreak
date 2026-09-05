# FINDINGS

## H064-H065 — Low-capacity announcement AI does not produce edge (2026-08-30)

**Answer: retire this programme.** We tested the strongest version the current
point-in-time data can support: long-only NSE EQ names with trailing 20-session
median traded value of INR 0.5–25 crore, after material corporate disclosures.
This is a **low-capacity** universe, not a historical small-cap universe;
point-in-time market capitalisation is not available.

### The data and seal

The feed's one-line summary was inadequate (415/699 sampled disclosure records
had fewer than 100 characters), so linked NSE attachments were archived through
the data module before judging. Of 696 unique attachments, 695 downloaded and
689 yielded text; the final 640-case set carried text for 692/699 disclosure
rows. Issuer names, symbols, CIN/DIN, scrip codes, email/web fields, obvious
letterheads, signatures and calendar dates were scrubbed. The remaining
historical-memory risk cannot be proved away, so the replay is exploratory.

`RPL_H064_ANNOUNCEMENT_AI_V1` used 640 cases, four per each of 160 seeded train
sessions, case hash `6bca49067378a63b`, prompt
`announcement_batch_v1`, Codex `gpt-5.6-terra`, zero failed calls. Decisions
were sealed before outcomes. V1's evidence record is void because two
diagnostics were wrong at the realised 2.66% take rate: baselines were matched
to total count rather than the same take sessions, and the HH estimator was
asked for 19 lags from only 17 dated observations, manufacturing enormous t
statistics through near-zero variance. V2 (`...V2_BASELINE_REPAIR`) retains the
identical cases and AI decisions, matches every baseline inside the same
sessions and returns corrected t as unknown when dates do not exceed lags.

### H064: the AI did not select or rank

The judge returned 17 TAKE, 119 WATCH and 504 SKIP decisions.

| 20-session excess | mean gross | after 40 bps | vs AI |
| --- | ---: | ---: | ---: |
| AI TAKE | **−113.1 bps** | **−153.1 bps** | — |
| all material disclosures | +13.5 | −26.5 | AI lift **−230.3** (session paired) |
| top 60d RS, same 17 sessions | +226.9 | +186.9 | AI minus baseline **−340.1** |
| frozen subject/keyword heuristic, same sessions | +154.6 | +114.6 | AI minus baseline −267.8 |
| walk-forward fixed-price model, same sessions | +108.7 | +68.7 | AI minus baseline −221.8 |

Seventeen take sessions provide zero complete non-overlapping 20-session
blocks, so no corrected t exists. That makes the exact effect imprecise, but it
does not leave a promising lead: the mean is negative, loss magnitude exceeds
win magnitude, and every non-random baseline is positive on the identical
dates. Nor did the action threshold hide a useful score. Across all 620 cases
with outcomes, AI confidence rank IC was **0.005 (HH t 0.14)**; choosing the
highest-confidence name each session produced −26.0 bps gross and −39.5 bps
lift. AI action followed by confidence was worse (−61.3 bps gross, −74.8 lift).

### H065: the only mechanical lead did not replicate

The frozen announcement heuristic's train diagnostic—one pick per session—was
+131.6 bps gross excess (+91.6 after cost), +118.1 bps lift, HH t 1.21. The
coarse pattern was plausible: acquisitions/orders positive, resignations
negative. H065 therefore froze the four constructive exact subjects before
opening validation or test: acquisitions, agreements, orders/contracts and
monthly business updates.

| partition | all material | selected | selected gross | net | lift | HH t |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| validation | 3,408 | 731 | +13.8 bps | **−26.2** | −0.6 | −0.01 |
| test | 4,030 | 979 | **−96.4 bps** | **−136.4** | +11.1 | 0.27 |
| pooled | — | — | — | — | **+4.6** | **0.12** |

Every frozen clause failed. Category stability failed too: acquisitions were
+48.3 bps in validation and −133.0 in test; orders/contracts +121.0 and −42.9.
The train lead was sample noise/regime concentration, not disclosure drift.

### Consequence

There is no evidence here that an AI reading public disclosures in lower-
capacity names adds alpha, and no evidence for the simpler constructive-subject
strategy. The broad pool itself returned +13.5 bps gross in train and the
selected rules were below costs out of sample. Do not rescue this by forcing a
higher AI take rate, adding subject/keyword combinations, changing the turnover
band or scanning horizons: those are new searches on outcomes already read.
The only live investable research result remains H060's long-history momentum
rule and its forward registration; this programme adds no new edge.

---

## Breeze historical data feasibility (Phase 0)

**Status: COMPLETE.** Run date 2026-08-18/19. `breeze_connect==1.0.69`, Python 3.11.8.
Evidence: ~200 live API calls, all logged in `data/metadata/api_calls.jsonl`,
full matrix in `data/metadata/feasibility_report.json`.

**Source relocation (2026-08-21).** Historical `src/<module>.py` references
below describe the paths used when the work ran. Current code is grouped under
`src/research_data/` for data access and `src/research/` for hypothesis-family
research; the measurements and evidence were not rewritten.

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

---

# Addendum — the ruler, not the market (2026-08-22)

**No sample was spent producing anything below.** Every number here comes from
Monte-Carlo against the lab's own evaluator, or from descriptive statistics of
price dispersion. Nothing was tested, nothing was promoted, and the dispatch
ledger did not move.

## The simulator was 2.6x quieter than the tape

`tests/test_selector_eval.py` assumed a **3.0%** standard deviation on 10-day
excess returns. Measured on `data/normalized/daily_bars_adj.parquet` at
`generators.DEFAULT_MIN_TV_CR = 1.0` — 1,647 sessions, ~1,150 names a session:

| liquidity floor | names/session | median within-session SD |
| ---: | ---: | ---: |
| 1 cr | 1,146 | **7.94%** |
| 10 cr | 506 | 7.37% |
| 50 cr | 207 | 6.57% |

Untrimmed, the pooled figure is 22.4%. Every safety property this lab believed
about its own bar had been established at 3.0%.

## Consequence 1 — the bar in basis points is not safe at 7.9%

The default bar had no significance term, so its false-alarm rate is a pure
function of how wide the sampling distribution of the measured lift is. On a
500-case replay that distribution has SD ~92 bps, so the 60 bps threshold sits
inside the noise. Pure-noise selectors, 8 cases/session, 150 seeds:

| blocks | cases | bps only | bps + \|t\|>2 | bps + \|t\|>2.5 |
| ---: | ---: | ---: | ---: | ---: |
| 4 | 504 | **13%** | 4% | 2% |
| 9 | 1,000 | 9% | 3% | 2% |
| 18 | 2,000 | 8% | 2% | 2% |
| 54 | 5,992 | 3% | 3% | 2% |

PLAN.md's earlier conclusion — *promote on bps, never on t* — was right about t
and wrong to stop there. Neither term alone controls the false-alarm rate; the
conjunction does. On the shipped path over 250 seeds the conjunction admits
8.8% at 4 blocks, 3.2% at 9, 2.4% at 18, which is what sets
`MIN_INDEPENDENT_BLOCKS = 8`.

## Consequence 2 — the power had never been measured, and it is fatal at 500 cases

| blocks | cases | power at a true 150 bps edge |
| ---: | ---: | ---: |
| 4 | 504 | **31%** |
| 18 | 2,000 | 69% |
| 54 | 5,992 | 99% |

150 bps is the optimistic end of a plausible discretionary selection edge; real
quantitative ones live nearer 20–80. **A 500-case replay cannot answer the
mission's question**, and the earlier plan sized every replay at 500. The floor
is ~2,000 cases and the design works at ~6,000 — roughly 8M input tokens, which
is money rather than sample and therefore the one binding constraint here that
can be bought out of.

## The defect that would have wasted the first replay

`excess_lift` is takes against the pool **of the same session**, and the pool
contains the takes: in a session of k cases with m taken, the contrast equals
`(1 − m/k)` times take-vs-skip. At k=1 that factor is zero.

`generators.sample` round-robins one case into every session before any session
gets a second. `train` holds **749 sessions**. `sample_n` is **500**. So the
default configuration puts exactly one case in each of 500 distinct sessions,
and the primary metric is structurally zero. Verified against a planted 300 bps
edge:

| cases per session | measured lift | verdict |
| ---: | ---: | --- |
| 1 | **0.0 bps** | passed 0/25 |
| 2 | 166.5 bps | passed 23/25 |
| 3 | 234.2 bps | passed 24/25 |

The report is otherwise fully populated. It fails *toward the null*, so it would
have read as the honest "the AI has no edge" answer the lab is braced for.

Shape is also a free lever — at a fixed 500-case budget, 63 sessions of 8 has
99% power against 150 bps where 250 sessions of 2 has 72% and 500 of 1 has none.

## What changed in the code

- `opportunity.py` — `min_excess_lift_t` added to `MIN_MEANINGFUL` (floor 2.0)
  and to `DEFAULT_PASS_CRITERION` (2.5); `validate_pass_criterion` now refuses a
  bar of magnitude alone *or* significance alone; `MIN_INDEPENDENT_BLOCKS = 8`;
  `validate_sample_adequacy` added.
- `evaluate.py` — reports `cases_per_session` and `pool_attenuation`; new
  `INADEQUATE_SAMPLE_SHAPE` verdict class; the `sample_caveat` rewritten, having
  previously asserted the opposite of what is true.
- `generators.py` — `sample` raises below 2 cases per session on all three paths.
- `tests/test_selector_eval.py` — harness defaults to the measured `REAL_NOISE_PCT`
  = 7.9; nine new tests; three power studies behind `-m power`.
- `distil.py` + `tests/test_distil.py` — the new stage, below.

## The stage that follows from all of this

If a selection cannot be tested at any affordable case budget, then the judge's
**picks** are the wrong output. Its **reasons**, written as a predicate, run
over the whole panel where the sample is. `discretionary/distil.py` scores a
distilled rule on fidelity to the judge (Cohen's kappa, not raw agreement —
two 25% selectors agree 62% of the time knowing nothing) and hands the survivor
to the signal path for edge. The authoring step refuses any frame carrying a
forward label.

## Data state — updated 2026-08-22

The 1995–2019 legacy bhavcopy archive is complete and local: 6,218 sessions,
7,371,508 rows, 490 MB, 0 errors, synced from the server 2026-08-22. Raw only —
normalisation into the panel is not done. Against `train`'s 749 sessions it is
~8x the independent blocks, which by the table above is worth about a factor of
three on the detectable edge. The 2020-2023 window remains spent.

---

# Addendum — the dispersion gate, run on the corporate-event pull (2026-08-22)

Second moments only. No direction was measured, no arms were compared, nothing
was promoted, and the dispatch ledger did not move. The gate asks one question:
**do outcomes after this event fan out more than they otherwise would?** A
family that scores 1.0 has nothing for any selector to separate; one that scores
high may have something, and says nothing about whether it is findable.

## The null band, established on real data

Three administrative announcement types and a random draw, which should all
read 1.00 and do. This is what makes the rest of the table readable:

| control | dispersion ratio | tail ratio |
| --- | ---: | ---: |
| random name-days | 1.014 | 0.999 |
| Shareholders meeting | 1.010 | 1.012 |
| Certificate under SEBI (Depositories) | 1.036 | 1.031 |
| Copy of Newspaper Publication | 0.981 | 0.924 |

**The null band is roughly 0.92–1.08.** Under full matching it tightens to
±0.04. Anything inside it is nothing.

## The result: bulk deals, and almost nothing else

Control matched on the session, then additionally on a point-in-time volatility
quintile and a liquidity quintile. The middle column is where most candidates
die.

| family | h | session only | + volatility | + vol & liquidity | n |
| --- | ---: | ---: | ---: | ---: | ---: |
| **deal: bulk** | 1 | 1.788 | 1.386 | **1.357** | 17,582 |
| **deal: bulk** | 10 | 1.506 | 1.255 | **1.225** | 17,285 |
| ann: Financial Result Updates | 1 | 1.283 | 1.188 | **1.154** | 19,497 |
| ann: Outcome of Board Meeting | 1 | 1.296 | 1.205 | **1.202** | 28,481 |
| ann: Financial Result Updates | 10 | 1.008 | 0.995 | 0.971 | 19,454 |
| ann: Outcome of Board Meeting | 10 | 1.063 | 0.998 | 1.007 | 27,547 |
| deal: block | 1 | 0.893 | 0.846 | 0.972 | 2,154 |
| ~ADMIN Shareholders meeting | 1 | 1.017 | 1.010 | 0.997 | 27,013 |
| ~CONTROL random | 1 | 0.982 | 1.011 | 0.990 | 27,000 |

**About half the raw bulk-deal effect was confound** — deals happen in jumpy,
thinner names — and a 22–36% excess dispersion survives anyway, at both a
one-day and a ten-day horizon, on 17,000 events across 1,600 sessions at ~11
per session. That last number matters as much as the ratio: it is the case-set
shape §3.3 says the evaluator needs.

**Earnings-type announcements are real but fast.** 1.15–1.20 at one day,
gone by ten (0.97–1.01). Whatever the news does, it is spent almost
immediately. That is a materially worse proposition than it looks, because a
0.40% round trip against a one-day move is a far larger hurdle than against a
ten-day one.

**Block deals are the mirror image** — outcomes after a negotiated block are
*calmer* than normal at the session-only level (0.82–0.89). Small sample and it
does not survive matching cleanly, so it is noted rather than claimed.

**Flat at every horizon and every matching level**, which was the surprise:
Acquisition (0.94), Press Release (0.96), Credit Rating (0.98), Investor
Presentation (1.00), Allotment of Securities (0.96), Disclosure under SEBI
Takeover Regulations (1.03). These are precisely the announcement types the
"an LLM can read the context" thesis leans on hardest.

## What this changes

The ranking argued earlier today put earnings first and deals second. **The
data reverses it.** Bulk deals are the only family that is simultaneously
large, well-shaped, robust to the obvious confound, and alive at a horizon
where transaction costs are survivable.

Two cautions that the gate cannot address and this addendum does not claim
otherwise. Dispersion is not predictability — the fanning may be ordinary
volatility clustering around flow. And a further confound beyond volatility and
liquidity (deals co-occurring with news) has not been excluded.

## Data state — the corporate-event pull

| source | rows | point-in-time usable | coverage |
| --- | ---: | ---: | --- |
| deals | 341,532 | 162,633 | 2020-01→2026-08, 3,453 symbols, 98.8/session |
| announcements | 1,623,117 | 996,956 | 2020-01→2026-08, 2,632 symbols, 605/session |
| financial_result_filings | 1,330 | 510 | **8 symbols only** |

"Usable" means `first_tradable_session` resolved; the remainder predate the
price tape. Every join above is on `first_tradable_session`, so the first
actionable session's own move is excluded from every window.

**The filings table is a pilot, not a pull.** 8 symbols cannot support anything,
and the announcement subjects are a poor substitute for it — "Financial Result
Updates" is a notification category, not the filing. If the earnings family is
to be tested at all, that pull has to be finished first.

---

# Addendum — what a bulk deal actually is (2026-08-22)

Still label-free. The event layer, the client classification and the dispersion
gate below read no outcome mean, compared no arms and spent no dispatch. The
family is registered as [[H043]].

## The file does not describe what it appears to describe

`data/normalized/deals.parquet`, bulk rows with a resolved first tradable
session — 113,380 of them:

| | share |
| --- | ---: |
| client-name-days that are near-flat round trips | **40.4%** |
| total bulk volume done by those flat clients | **58.6%** |
| rows from the top-20 clients | 38.0% |
| of those top-20 rows, share that are round trips | 83.2% |
| name-days carrying both a BUY and a SELL | 72% |

The top of the client list is Graviton Research Capital, HRTI, NK Securities
Research, QE Securities and XTX Markets — market makers whose intraday turnover
crosses the 0.5% reporting threshold and whose overnight position is zero.
Reading "a large buyer appeared" off those rows is reading liquidity provision
as information. The share is rising: 24.5% of rows in 2020, 40.7% in 2026.

## Splitting the file removes most of the result

Control matched on session, point-in-time volatility quintile and liquidity
quintile throughout.

| subset | h=1 | h=10 | n | per session |
| --- | ---: | ---: | ---: | ---: |
| all bulk, as reported | 1.386 | 1.225 | 15,373 | 11.2 |
| round-trip only | 1.323 | 1.218 | 12,331 | 9.0 |
| directional | 1.431 | 1.384 | 3,042 | 2.9 |
| — accumulation | 1.489 | 1.364 | 1,666 | 2.1 |
| — distribution | 1.344 | 1.478 | 1,359 | 1.9 |
| ~CONTROL random | 1.035 | 1.006 | 27,000 | 16.5 |

Every figure above is on the partitioned frame `research_data.frame.load_events`
returns, with purged boundary events dropped — which is why the counts are
smaller than the raw file's.

**A session whose only bulk activity was a market maker crossing its own book
is followed by outcomes 20% more dispersed than matched controls.** No
positioning was disclosed. So most of yesterday's headline is an attention or
volume effect that survived matching on volatility and liquidity — which is a
caution about the gate as much as about the family.

What survives is the increment: **1.384 for directional flow against 1.218 for
round-trip sessions at h=10.** That is the hypothesis, and it makes round-trip
sessions the correct control. A test against the matched panel would clear
easily and prove nothing.

Two things worth noticing in the split. Distribution fans outcomes out more
than accumulation at h=10 (1.489 against 1.273) — large sellers, not large
buyers, mark the uncertain situations. And the tradeable event set is a quarter
the size of the headline: 3,042 events, not 15,373.

## The lookahead this family invites

The client classification is what makes the event mean anything, and the
obvious implementation of it reads the future — labelling a 2021 deal by a
client's 2025 behaviour. `client_profile` is expanding and shifted, a client
with fewer than ten prior sessions is `unknown` rather than assumed, and
`tests/test_bulk_deals.py` asserts both, including that the first session of any
client has no profile at all. This is H015 in a new costume and it would not
have announced itself.

## Shipped

`src/research/families/bulk_deals/` — `events.py` with the point-in-time client
book, profile and event construction. `tests/test_bulk_deals.py`, 10 tests.
`alpha_eval/spread.check` gained `match_on`, with a test that a fake family
drawn only from jumpy names scores 1.79 unmatched and 1.00 matched.

**Nothing here is a directional result and none of it may be read as one.**

---

# Addendum — is the bulk-deal test worth commissioning? (2026-08-22)

Still no sample spent. Everything below is dispersion, structure, or simulation.

## Two design questions, settled

**Does a bulk deal beat simply knowing volume was high?** Yes, at ten days.
Adding an abnormal-volume quintile to the matching barely moves it:

| event set | +vol+liq | + also abnormal volume |
| --- | ---: | ---: |
| all bulk days | 1.225 | 1.176 |
| round-trip only | 1.218 | 1.195 |
| directional | 1.384 | **1.458** |

At h=1 volume explains most of it (directional falls 1.592 → 1.341). At h=10 it
explains none. **Round-trip days survive volume matching too (1.195)** — so the
earlier characterisation of them as noise was wrong, and market-maker presence
carries something beyond volume. It is simply weaker than directional flow.

**Head to head on bulk-deal days only, directional against round-trip:**

| arm | h=1 | h=10 |
| --- | ---: | ---: |
| directional | 1.202 | 1.284 |
| — accumulation | 1.147 | **1.021** |
| — distribution | 1.092 | **1.331** |

**At ten days the entire increment is distribution.** Accumulation is 1.021 —
indistinguishable from the round-trip control it is measured against. Large
sellers mark the situations that separate; large buyers do not.

## A correction to this morning's block arithmetic

PLAN.md quotes `independent_blocks = sessions / horizon`. For a *paired*
contrast that is too harsh: pairing inside the session cancels the market
factor, which carries most of the overlap.

A first attempt to measure the residue used a placebo — random events with the
real per-session counts — and read a lag-1 autocorrelation of +0.020 at h=10
against +0.900 for a full overlap. **That reading was an artefact.** Random
reassignment destroys event-set persistence, and persistence is precisely what
carries the correlation. The honest measurement is structural and needs no
outcome at all:

| lag (sessions) | share of distribution names recurring |
| ---: | ---: |
| 1 | **0.190** |
| 2 | 0.140 |
| 5 | 0.095 |
| 10 | 0.050 |

34% of distribution events have another on the same symbol within 14 days; 46%
of symbols appear exactly once. So the overlap share is ~0.19 — neither of the
extremes. `alpha_eval.spread.event_persistence` measures it, with tests at both
ends.

## The power of the test, at the measured persistence

Simulated on the real session structure — the actual sessions, the actual event
and control counts on each — against the bar frozen this morning (≥60 bps and
|t| ≥ 2.5):

| true edge | 50 | 75 | 100 | 150 | 200 |
| --- | ---: | ---: | ---: | ---: | ---: |
| **distribution** (1,363 events, 734 sessions) | 10% | 27% | **46%** | 86% | 99% |
| directional (3,042 events, 1,032 sessions) | 18% | 46% | **70%** | 99% | 100% |

**The test detects 150 bps and is a coin flip at 100.** Realistic selection
edges are 20–80 bps. Run today, a null result would be uninformative — which is
the worst possible outcome, because it costs the sample and settles nothing.

## What changes that, and it is already on disk

122,293 bulk deals from **2004–2019** sit in the file with `session_status =
before_tape`, across 3,914 sessions and 2,359 symbols — against 113,380 usable
deals over 1,645 sessions today. Building the legacy price panel roughly
doubles the events and **triples the sessions**, which is what power depends
on: 734 paired sessions becomes ~2,500, and the detectable edge falls by about
1.8x. A 100 bps effect goes from a coin flip to near-certain, and 50–75 bps
comes into range for the first time in this project's history.

The fit is lucky and worth stating: this family needs **only OHLCV and volume**.
The legacy archive has no delivery percentage and no VWAP, which rules out most
of the lab's other work — and rules out none of this.

**Recommendation: do not spend the sample yet. Build the legacy panel first.**
It costs no sample, the raw data is local, and it is the difference between a
test that cannot answer the question and one that can.

---

# Addendum — the counterparty, and the pre-2020 panel (2026-08-22)

No sample spent. Taxonomy and panel construction read no outcome at all.

## Who is actually on the other side

`bulk_deals.clients` classifies the free-text counterparty name. 29,123 raw
names collapse to 11,084 entities after normalisation — the same firm appears
as `QE SECURITIES LLP` / `QE SECURITIES`, and as `ASIT C MEHTA INVESTMENT
INTERMEDIATES` / `INTERRMEDIATES` / `INTERRM`. That is not tidiness:
`client_profile` needs ten prior sessions before it classifies anyone, so an
entity split across three spellings can carry thirty sessions and be `unknown`
in all three.

| type | rows | share | entities |
| --- | ---: | ---: | ---: |
| individual | 34,885 | 36.3% | 8,274 |
| **prop_hft** | 34,034 | **35.4%** | **27** |
| corporate | 11,687 | 12.1% | 1,068 |
| broker | 8,697 | 9.0% | 288 |
| unknown | 2,871 | 3.0% | 720 |
| foreign_portfolio | 2,221 | 2.3% | 287 |
| **mutual_fund** | 867 | **0.9%** | 218 |
| insurance | 348 | 0.4% | 42 |
| promoter_related | 299 | 0.3% | 124 |

**Twenty-seven entities are 35% of the file.** Institutional investment — the
thing the disclosure is imagined to reveal — is 0.9%. The counterparty in a
bulk deal is overwhelmingly a market maker or a wealthy individual, not a fund.

**The taxonomy does not sharpen the test, and that is a negative result worth
recording.** Splitting distribution events by seller type at h=10:

| net seller | ratio | n | per session |
| --- | ---: | ---: | ---: |
| individual | 1.195 | 2,568 | 2.49 |
| corporate | 0.971 | 826 | 1.50 |
| broker | 1.301 | 324 | 1.22 |
| foreign_portfolio | 0.457 | 231 | 1.16 |
| mutual_fund | 0.572 | 166 | 1.08 |

Only the individual arm clears the two-per-session floor at which a
within-session dispersion is readable at all, and it reads *below* the unsplit
distribution figure of 1.331. Every institutional category is too small to say
anything. The taxonomy answers the counterparty question and buys no power.

## The pre-2020 panel

**The premise that blocked this was wrong.** NSE's corporate-actions endpoint
was assumed to start in 2020 because that is where the local cache started. It
serves **2003** onward. 26,222 legacy actions are now on disk, including 416
splits and 391 bonuses, and the legacy panel is reconciled by the same
two-source rule as the modern one rather than adjusted off the tape.

**Two construction errors, both caught by measuring rather than reading.**

*Ratios too close to 1.0.* A first canonical list included 4:5 and 5:4, and
"adjusted" 5,722 ordinary 20–25% sessions into corporate actions. That does not
lose data, it manufactures it, and nothing downstream could have seen it. The
list is now split: only ratios a normal session cannot imitate are ever
adjusted; 3:5 through 5:3 are marked and left alone.

*A parser gap.* 299 of 416 legacy splits — 72% — carried a stated ratio that
`parse_subject` could not read, because the pre-2020 feed writes `Fv Split
Rs.10/- To Rs.2/` where the modern feed writes `... Per Share To ...`. Fixing
it took matched events from 519 to 773 and unparsed from 374 to 77. **The fix
changes zero modern events and 297 legacy ones**, so every finding resting on
`daily_bars_adj.parquet` is unaffected.

Result, 10-day windows, share of rows per bin (×1e5):

| daily return | legacy | legacy, quarantined windows dropped | modern |
| --- | ---: | ---: | ---: |
| (−52%, −48%] | 11.6 | **2.4** | 1.3 |
| (−48%, −42%] | 9.0 | 4.9 | 0.3 |
| (−35%, −25%] | 60.1 | 17.8 | 5.7 |

7,316,207 bars, 1995–2019, 2.5% of rows lost to quarantine. The 1:2 split zone
falls from nine times the modern rate to about twice it.

**This panel is not yet at the modern panel's standard and must not be quoted
as if it were.** After cleaning, the left tail still runs 2–3x the modern rate.
Some of that is genuine — 2008, thinner small caps, wider bands — and some is
probably residual corporate actions. Enough to build features on; **not yet
enough to trust a dispersion measurement from**, which is precisely what a
spurious fat tail corrupts. Validating it is the next step, and the deals it
would unlock still need `pipelines/events.py` re-run against the extended tape
before their `first_tradable_session` resolves.

## A file I broke and restored

`fetch_actions` writes `corporate_actions.parquet` as a side effect. Calling it
for 2003–2019 overwrote the modern actions with legacy-only rows. Caught by the
row count, fixed by re-running over the full 2003–today range from the intact
JSON cache; the file now holds 41,456 actions and 700 of 703 splits carry a
ratio. `daily_bars_adj.parquet` was never rebuilt and never changed.

---

# Addendum — the out-of-sample check, and two things it broke (2026-08-22)

The 2005-2019 era was opened for the first time. Still second moments only; no
outcome mean read, no dispatch spent, H043 still frozen.

## The extension worked

`corporate_actions` reaches 2003, the parser fix explains 297 more legacy
splits, and `events.build_deals` accepts a session calendar. Passing it the
combined 2005+ tape resolves the deals that had been stranded:

| | before | after |
| --- | ---: | ---: |
| usable bulk deals | 113,380 | **234,520** |
| sessions | 1,645 | **5,351** |

## The out-of-sample check cannot be performed, and that is the finding

| era | directional vs round-trip | accumulation | distribution | per session |
| --- | ---: | ---: | ---: | ---: |
| 2005-2019 | 0.743 | 0.807 | 0.685 | 1.61 |
| 2020-2026 | 1.240 | 1.003 | 1.310 | 3.14 |

Read naively that is a reversal. It is not, because **the estimator does not
work on the older era.** Random events carrying the real per-session counts:

| era | null dispersion | sd | range |
| --- | ---: | ---: | --- |
| 2005-2019 | **1.148** | **0.245** | 0.781 – 1.510 |
| 2020-2026 | 1.061 | 0.063 | 0.939 – 1.152 |

The legacy null is four times noisier and its own mean sits at 1.148. The
"reversal" at 0.685 is 1.9 sd below that — indistinguishable from noise. The
cause is the readability floor this lab already has: 1.6 directional events per
session, under the 2.0 a within-session dispersion needs. Lowering the
liquidity floor to 0.25 cr and 0.1 cr does not fix it (1.79 and 1.87 per
session).

**So the 2005-2019 era cannot check this family, at any liquidity floor, with
this contrast.** It is not spent — nothing was concluded from it — but it is
not the confirmation the earlier addendum expected it to be, and the argument
that the legacy panel makes this family testable was wrong for this design.

## The null is 1.06, not 1.00

Every dispersion figure this project has quoted was read against a random draw
of *arbitrary* group size. Against random events with the **real** per-session
counts — thin groups, as the family actually has — the modern null is 1.061
with sd 0.063. So the headline 1.240 is about 3 sd, not the 4 the raw ratio
suggests. Nothing is overturned; everything is smaller than it read.

## The narrowing to distribution is withdrawn

H043 was narrowed this morning to sell-side flow, on 1.331 for distribution
against 1.021 for accumulation. Varying the liquidity floor — a parameter
nobody had varied:

| liquidity floor | directional | accumulation | distribution |
| --- | ---: | ---: | ---: |
| 1.00 cr | 1.240 | 1.003 | **1.310** |
| 0.25 cr | 1.233 | 1.026 | **1.200** |
| 0.10 cr | 1.238 | 0.969 | **1.075** |

**`directional` is flat across all three; `distribution` collapses from 1.310
to 1.075 and meets the null.** The sell-side narrowing was fitting the 1-crore
floor, registered as a pre-registration four hours after it was chosen and
before it had been varied once. That is the H024 disease at small scale, caught
by varying a parameter rather than by any insight, and it is exactly what
`PLAN.md` §7 warns about the case format: *every one of those is a parameter
nobody has varied.*

**What survives** is the unnarrowed claim: directional flow, either sign, at
1.233-1.240 against a 1.061 null, stable across every floor tested. Modest,
robust, and about 3 sd — which is a far weaker thing than this morning's table
implied.

---

# Addendum — the separation screen, and what a bulk deal turns out to be (2026-08-23)

The first moment was read, on `train` only, under the design registered in
HYPOTHESES.md ("H043 pre-flight") **before the screen was run**. Eleven
features, three liquidity floors, two horizons, sixty-six readings, all of them
below. No dispatch spent; `validation`, `test` and `forward` untouched.

The question was the one left standing after the withdrawal: directional flow
fans outcomes out at 1.24 against a 1.06 null, and fanning out pays nothing
unless something says *which* names went which way. **Does any simple coded
feature separate outcomes within directional days?**

## First, a feature that was measuring a corporate action

`deal_vs_close_pct` compared a raw deal price against a **back-adjusted**
close. In any name that later split or bonused, the adjusted close is the deal
price divided by the factor, so the feature returned the factor. On the train
directional set: 24.9% of events sit in a name carrying a later adjustment,
17.7% of premiums read beyond ±20% against 1.1% once both legs are raw, and
the median premium falls from **+1.82% to 0.00%**. The whole apparent premium
was the adjustment. Bulk deals print, on median, exactly at the close.

`_scale` now demands `close_raw` and `med_vol_raw` by name and raises on the
adjusted columns; `report.context` supplies both spaces and takes the
liquidity floor as an argument, because a floor that can only be changed by
editing a module constant is a floor nobody varies.

## The screen: nine of eleven features are inside the null band

Excess over the built null, in basis points of forward excess return. The null
re-points each event at a same-session name matched on volatility, liquidity
and volume-surprise quintile, keeps the event's features, and is centred on
its own mean — the matching means a volatility feature partly reproduces
itself in its own null, and reading a raw spread against a band assumed to sit
at zero would credit the feature with what the matching already contains.

h=10, the family's horizon:

| feature | 0.10 cr | 0.25 cr | 1.00 cr | band |
| --- | ---: | ---: | ---: | ---: |
| **vol20** | **−561** | **−536** | **−444** | 172 / 196 / 271 |
| premium_pct | −419 | −380 | −162 | ” |
| net_flow_signed | −291 | −190 | −260 | ” |
| direction_sign | −152 | −77 | −122 | ” |
| value_vs_turnover | +54 | −55 | −177 | ” |
| volx | −19 | −73 | −260 | ” |
| round_trip_share | +114 | +45 | −75 | ” |
| mom20 | +1 | +73 | −308 | ” |
| net_flow_abs | +30 | −38 | +59 | ” |
| dir_clients | +12 | −7 | −47 | ” |
| premium_signed | −22 | +19 | +114 | ” |

The band is the 95th percentile of the **largest absolute spread across all
eleven features** per null draw, which is what an eleven-feature screen has to
clear. Two features clear it at every floor with a stable sign: `vol20`, and
`premium_pct` at h=1 (−184 / −149 / −107 against a band of 57 / 62 / 72).

**Every feature that describes the deal itself is inside the band.** Net flow
against normal volume, deal value against normal turnover, how many clients
printed, how much of the day was market making, and the direction of the flow
— the one the hypothesis is named after — separate nothing.

## Then the two survivors were asked whether they are about the deal

Three populations, same sessions, same statistic. The rung that matters is the
middle one: a round-trip day is a day when a prop desk crossed its own book
and went home flat. A large print happened; **no position was disclosed.**

`premium_pct`, top-minus-bottom tercile, bps:

| population | h=1 | h=10 | n |
| --- | ---: | ---: | ---: |
| no deal, magnitude-matched | −12 to −23 | −6 to +10 | ~1,000,000 |
| round-trip bulk day | −68 to −130 | −216 to −399 | 5,940–8,165 |
| directional bulk day | −107 to −184 | −162 to −419 | 1,179–1,801 |

`vol20`, same three:

| population | h=1 | h=10 |
| --- | ---: | ---: |
| no deal | −1 to +6 | −15 to +59 |
| round-trip bulk day | −31 to −80 | −227 to −457 |
| directional bulk day | −90 to −129 | −444 to −561 |

**Both survivors are already at full strength on days when nobody took a
position.** The round-trip arm carries five to eight times the sample, so its
readings are the better-measured of the two, and the directional increment
over it is inside the noise at every floor — at 1.00 cr and h=10 the
directional premium reads *smaller* (−162) than the round-trip one (−216).

## What this means for H043

H043 does not claim that bulk-deal days are unusual. It claims that
**directional** flow adds something over round-trip flow, and that the
addition is findable. The screen was the cheapest possible test of the second
half, and the answer is that nothing about the disclosed position separates
outcomes — while two things that have nothing to do with the position separate
them identically whether a position was disclosed or not.

That is the same shape as the finding that split the file in the first place:
round-trip days carried the dispersion, and now round-trip days carry the
separation too. The counterparty story — a promoter selling, a fund forced out
— is not what this file is measuring.

## The power statement, which is the other half of a null

At 1,179–1,801 events over ~500 train sessions, the eleven-feature band is
**±57 to ±72 bps at h=1 and ±172 to ±271 bps at h=10.** Nothing smaller is
visible here at all. A 500-case replay carries a third of the events and its
judge cannot be run at 200 permutations, so its detectable magnitude is worse
than this by a wide margin. **A feature this screen cannot see is not a
feature a replay could have found**, which is what makes a null here decisive
rather than merely disappointing.

## One thing worth keeping, and it belongs to somebody else

A bulk print that lands far from the close is followed by continuation — the
name keeps moving the way it moved between the print and the close — at
−68 to −184 bps at h=1, five to eight times its magnitude-matched deal-free
twin (−12 to −23 bps on a million rows). It is coded, it is cheap, it needs no
judge, and **it is not H043**: it is strongest on the arm H043 excludes. Under
the distillation rule it is a quantitative idea found nearby and must be
registered as its own hypothesis rather than credited to this family. Two
known contaminants to clean first: the event session is D+1 by construction
(NSE publishes after the close; 76% at a one-session gap), so the feature
spans a day and a half of realised return, and a name that goes ex-split
inside that gap still produces a spurious ±100% premium.

---

# Addendum — H044 survives its train cleanup (2026-08-23)

**SUPERSEDED later on 2026-08-23 by the execution check below.** The table is
retained as the registered close-to-close diagnostic, not as executable alpha.

`validation`, `test` and `forward` were not read. H044's final exploration was
registered in HYPOTHESES.md before this run: pool all bulk events, remove
corporate-action gaps, subtract an exact same-length no-deal twin inside each
session, and demand more than 40 bps at all three liquidity floors both with
and without premiums beyond 10%.

## Two pieces of the apparent edge were real contaminants

First, `all_vwap` and `dir_vwap` were means of client-level prices. A one-share
print therefore received the same weight as a million-share print. They are now
`sum(value) / sum(quantity)`, asserted by `tests/test_bulk_deals.py`.

Second, the no-deal twin's previous VWAP was initially shifted *after* the
liquidity filter. If a name failed the floor on the immediately previous
session, the shift jumped to an older row and silently compared a multi-session
move with the event's one-session move. Previous raw VWAP and adjustment factor
are now fixed on the full tape before filtering, also under regression test.

The corporate-action quarantine removes any event whose adjustment factor is
missing or changes between the deal print and first-tradable close, or whose
reconciliation record lands in that interval. It removed 31–43 event
symbol-sessions depending on the liquidity floor. The twin receives the
corresponding factor-change quarantine.

## The exact twin explains some continuation, not most of it

Basis points of next-session excess return, equal-weighted over sessions that
carry both event tails and both twin tails:

| floor | extreme cap | event top−bottom | twin top−bottom | event−twin | DK t | paired sessions |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1.00 cr | none | −93.4 | −19.6 | **−73.8** | −3.22 | 526 |
| 1.00 cr | 10% | −85.5 | −14.9 | **−70.6** | −3.12 | 516 |
| 0.25 cr | none | −104.7 | −25.9 | **−78.8** | −4.58 | 604 |
| 0.25 cr | 10% | −94.7 | −21.4 | **−73.3** | −4.65 | 587 |
| 0.10 cr | none | −107.2 | −31.8 | **−75.4** | −4.61 | 628 |
| 0.10 cr | 10% | −120.7 | −26.4 | **−94.3** | −3.31 | 617 |

The same-length ordinary move carries 15–32 bps of continuation, so the bulk
print is not merely a renamed short-horizon momentum feature. After subtracting
that twin, 71–94 bps remains, in the registered direction and above the 40-bps
cost floor in every cell. Removing `|premium| > 10%` does not weaken it.

This is the point to stop. The result is still a train finding, but it is now a
specific one rather than a contaminated one: **a large bulk print far from the
next tradable close contains an incremental next-day continuation signal.**
HYPOTHESES.md freezes the 1-crore validation test at the train cuts −1.7510% /
+2.1473%, with a joint −40-bps and t≤−2 bar. No validation outcome has been
opened.

---

# Addendum — H044 fails when the trade is made executable (2026-08-23)

`validation`, `test` and `forward` remain untouched.

Two different clocks had been called "next day". The first implementation
also shifted outcomes after filtering the liquid universe. For 25 of 7,177
clean 1-crore events, a row falling below the floor pushed the exit forward by
a median 18 calendar days. Computing the next row on the full tape changes the
primary event-minus-twin increment from −73.8 to **−54.0 bps** (t=−2.86).
Small in count and large in influence; the corrected close-to-close diagnostic
still survives, so this is not the rejection.

The rejection is that the diagnostic buys its entry with hindsight. The
feature is `deal_vwap_D / close_D+1`: it does not exist until D+1 has closed.
The close→next-close outcome assumes the trade entered at the same completed
close used to decide it. At the earliest executable price, D+2 open, the
event-specific continuation is gone:

| outcome | event top−bottom | twin top−bottom | increment | DK t | paired sessions |
| --- | ---: | ---: | ---: | ---: | ---: |
| corrected close→next close | −72.4 | −18.4 | **−54.0** | −2.86 | 527 |
| next open→close | +23.6 | +17.7 | **+5.8** | +0.35 | 527 |

The executable estimate is noise and points in the opposite direction. Gross
open→close return is −71.0 bps for the purported long tail and +41.7 bps for
shorting the purported down tail. The latter is below the lab's 40-bps cost
floor once sessions receive equal portfolio weight; the train book loses after
costs. H044 is **REJECTED at train** and its frozen validation test is
withdrawn without being run.

---

# H045 source probe — equity-futures cash-and-carry (2026-08-23)

This was an E0 feasibility/magnitude probe registered in HYPOTHESES.md before
the basis was read. It is not a backtest and spent no outcome partition.

NSE's historical contract report supplied 50 March-2024 stock-futures rows:
ten sessions from 02–15 January for RELIANCE, HDFCBANK, ICICIBANK, INFY and
TCS. All 50 joined to the point-in-time raw cash bhavcopy. Close/settlement
gross implied annualised carry was median 9.40%, p10 8.09% and p90 10.29%,
against the RBI's 6.94% 91-day T-bill cut-off on 03-Jan-2024. That is a roughly
2.5 percentage-point gross cushion before dividends, execution, funding,
margin drag, taxes and physical-settlement costs.

TCS demonstrates the dividend contract. It announced ₹27 per share on 11-Jan
for a 19-Jan record date. Including that cash flow raises the 12-Jan indication
from 6.28% to 9.62% and the 15-Jan indication from 5.16% to 8.62%. The
unadjusted basis is not merely noisy; it ranks dividend contracts incorrectly.

Lots inferred from contract count and reported turnover imply median cash legs
of ₹6.10–9.17 lakh across the five names. One lot nearly consumes the lab's
entire trading-capital range before futures margin, so the practical question
is capital efficiency and cash-flow stress, not how much leverage can be
applied.

Across the same five hypothetical 02-Jan entries, basis compression by 15-Jan
ranged from ₹0 to ₹30.10 per share, a 0–22.34% annualised realised return on
the cash leg over thirteen calendar days (median 14.72%). This says the path is
variable enough for a PIT early-exit rule to be a coherent later question. It
does not show that such a rule beats hold-to-expiry: both legs use closing/
settlement marks, the exit date was inspected retrospectively and switching
costs were not charged.

One silent source defect appeared immediately: historical `Underlying Value`
was either missing or a present-day value repeated down every old row. It is
not PIT and is unusable. Cash must come from the bhavcopy. Futures settlement
is a last-half-hour weighted price, not an executable quote, so the observed
spread licenses only the next data-contract step.

Verdict: build a bounded daily derivatives/contract/dividend/margin pre-flight,
then test the simple net hold-to-expiry baseline. Do not invest in early-exit or
leverage optimisation unless that baseline first clears a frozen low-risk-rate
buffer after conservative all-in costs.

---

# Addendum — Earlier entry preserves a bulk-deal signal, not primary net alpha (2026-08-23)

H046 moved the clock to the first genuinely executable opportunity after the
disclosure: compare the bulk print on D with D's completed close, then enter at
D+1 open and exit at D+1 close. This uses no D+1 information to select the
trade. `validation`, `test` and `forward` were not read.

The train signal is clear and event-specific. At the registered 1-crore floor,
the event top-minus-bottom spread is −55.6 bps against −2.4 bps for the exact
same-session no-deal VWAP-to-close twin: an increment of **−53.2 bps** with
DK t=−2.99 over 523 paired sessions. The sign and magnitude survive the 10%
extreme cap and both lower liquidity floors (−53.4 to −68.1 bps, all t≤−2.99).

That is information, but it is not enough money at the primary floor. In
excess-return terms after the lab's 40-bps round trip, the 1-crore long,
short and 50/50 long-short arms earn **−16.9, −5.4 and −12.2 bps per trade**.
The tempting +74.9-bps raw short return is partly the market falling on the
same sessions; the short's actual excess is +34.6 bps before cost. H046 is
therefore rejected at its registered economic gate without validation. The
0.25/0.10-crore short robustness rows are +7.3 to +15.2 bps net excess, but a
lower-liquidity row cannot replace the frozen 1-crore primary after inspection.

H047, the fixed 15:15 D+1 entry, stopped even earlier. Train contains 15,500
bulk symbol-events across 2,438 symbols, but `research_data` has no broad
full-session intraday dataset; the seven one-minute probe files are not an
unbiased panel. No 15:15 outcome was read. The honest result is **DATA GAP**, not
a large-cap backtest.

---

# H055 PA2 source probe — native five-minute Breeze history is usable with a strict collector (2026-08-24)

No forward return was read. A bounded, repeated RELIANCE probe established the
source semantics needed before the price-action bootstrap can run.

- Native 1-minute, 5-minute and 30-minute endpoints returned 376, 76 and 13
  rows respectively for 03-Feb-2025. Repeating the five-minute request produced
  byte-identical payload content.
- Across 75 regular buckets, every native five-minute OHLCV row equalled the
  corresponding five one-minute rows aggregated from its timestamp. The source
  timestamp is therefore the **bar start**, and a five-minute row is not
  available until timestamp + five minutes.
- A deliberately wide five-minute request returned exactly 1,000 rows, starting
  on 11-Mar despite asking from 01-Jan: Breeze silently keeps the **tail**.
  Frozen requests must remain below the cap and a capped response is rejected.
- Native five-minute data returned for sampled sessions in 2017, 2018 and 2020,
  so the endpoint is deep enough for the 2020+ PIT bhavcopy programme.
- Some sessions append a zero-volume 15:30 marker. It is not a tradable interval
  bar, but it can carry the official close. The canonical collector now
  preserves it in a separate closing-marker shard and excludes it from decision
  bars.
- Regular five-minute bars reconciled to 99.05% of daily volume on the sampled
  session, but did not exactly reproduce daily low or close. Intraday bars must
  therefore remain the execution/geometry source and bhavcopy the official
  daily/context source; neither silently substitutes for the other.

The point-in-time identity preflight clears the declared 95% symbol-session and
98% lagged-traded-value thresholds in every year from 2020 through 2026. A
50-anchor, 60-session, train-only bootstrap is frozen as 250 cap-safe requests
(maximum 225,000 regular rows). Its request hash is
`3bb343383853e60e8df7df5c6b9df615e80685b129334cf11a8a6230d73bd259` and its
acquisition-code hash is
`e0dda0f9c35c4bb86be8a7e342a3cfae434842c316e60fd52d02e9b4abe0558a`.

**Superseded acquisition status later on 2026-08-24.** After the Breeze session
was refreshed, v3 ran all 250 requests but rejected 241 as "bars outside the
regular session" (3 `ok`, 5 `empty`, 1 `partial`; 221,062 source rows). The
source commonly supplies pre-open 09:05 records, terminal 15:30 records, and a
small number of evening special-session records alongside regular bars. These
records are not decision bars, but rejecting the whole response discards valid
regular history. v3 is retained as failed-ingestion provenance and is not an
admissible dataset.

The corrected v4 contract preserves every such record in a separate
session-marker shard, excludes it from decision data, and measures requested
session coverage explicitly. A partial archival response is settled with its
missing sessions declared and counted against coverage; cap, authentication,
schema, duplicate, timestamp, and unrequested-session errors still block
admission.

v4 then ran the same 250-request, 3,000-symbol-session bootstrap on `hp-ts` in
78 seconds and passed local content verification: 235 complete responses, 10
declared partials, 5 empty responses, 221,482 source rows, 217,928 admitted
regular bars, 70 missing sessions, and **97.6667% requested-session coverage**.
There were no capped, authentication, schema, duplicate, timestamp, or
unrequested-session failures. The admitted data product contains 967 sessions
and 47 symbols after frozen split/purge handling.

The outcome-free E0 distribution is not dry: the broad causal generator yields
1,007 train candidates across 529 independent sessions and 45 symbols (median
2 and maximum 6 candidates per session). Under the transparent 400-bp block-
sigma assumption, the two-sided 5%/80% MDE is 48.7 bps against the frozen
80-bp useful-effect bar. Source, PIT identity, capacity and useful-effect-power
gates therefore pass. This is feasibility and density, not predictive evidence.

The first 60-case annotation bundle was invalidated before annotation because
its charts highlighted the coded zone and its sidecar supplied the coded zone
kind, distance, touch count and rejection score. Agreement on that bundle would
have been circular. The replacement is a content-hashed, anonymised blind set:
no zone overlay or derived zone answer, neutral ATR/price-scale context, correct
relative time ending at `t=0`, one frozen prompt, and zero outcome fields. Its
representation gate remains **BLOCKED, UNSPENT** pending one human and two
frozen model passes. No case was transmitted to an external provider and no
shape or directional outcome was opened.

**Annotation execution update, 2026-08-25.** The two frozen model passes have
now completed on the replacement blind set. `gpt-5.6-luna` accounted for all
60 cases with 58 valid structured judgements and two explicit failed calls;
`gpt-5.6-terra` accounted for all 60 with no failed calls. Failed calls were
retained as neutral `CALL_FAILED` rows rather than dropped or retried. Both
passes used the identical content-hashed charts, prompt hash and case-set hash,
with no tools, a read-only empty working directory, anonymised identity and no
outcome fields. The representation gate remains **BLOCKED, UNSPENT** pending
the complete frozen human pass; model answers remain hidden from that reviewer
until finalisation. No shape or directional outcome has been opened.

**H055 PA7 representation result, 2026-08-25.** The owner completed and froze
all 60 human cases before model answers were revealed. The design is complete,
but the preregistered representation gate **FAILS**: median pairwise composite
class kappa is 0.0868 against the 0.40 bar, and median zone-centre disagreement
is 1.52 lagged ATR against the 0.50 bar. Pairwise diagnosis is also weak rather
than one bad aggregate: Luna–Terra composite kappa is 0.231 with 0.575 ATR
centre disagreement; owner–Luna is 0.023 and 2.095 ATR; owner–Terra is 0.087
and 2.130 ATR. The models moderately agree on interaction alone (kappa 0.466)
but not on stance (0.227); owner–model interaction and stance kappas are near
zero. The owner selects fewer zones, more retests, fewer breaks, more avoids,
and materially more distant levels than either model. This does not test alpha
and does not prove that price action is useless. It shows that the current
case/prompt/representation does not encode one shared discretionary concept.
E1 remains blocked and no outcome was opened.

---

# H056 machine-geometry kickoff — selective retests exist, but the bootstrap is too small for outcomes (2026-08-25)

H055's human-representation failure is preserved. H056 was registered before
directional access and asks whether machine-discovered geometry can transfer
without agreeing with a human drawing. No forward return, excursion, target
hit, stop hit or trade payoff was opened in this kickoff.

The causal zone state machine now represents both directions of role reversal:
resistance→support and support→resistance. It also exposes only completed,
session-aligned 60-minute 20/50 EMAs; records bars and cumulative ATR that wick
through the far edge of a flipped level; records bars from break to retest; and
keeps the nearest already-known opposing zone available for structural target
planning. Future-append, incomplete-hour, bullish-flip and bearish-flip tests
pass.

The first manual prior is frozen in H056: at least 12 completed five-minute
bars from zone confirmation to break, at least 3 and no more than 36 bars from
break to retest, completed retest close on the new-role side, aligned completed
60-minute 20/50 EMA stack and fast-EMA slope, at most one bleed bar and 0.25 ATR
cumulative penetration, a stop 0.10 ATR beyond the far edge, and an already-
known opposing target offering at least 1.5R and 80 bps. Six-, twelve- and
twenty-four-bar stagnation exits are a declared development grid; they have not
been scored.

On `pa_bootstrap_v4` train, 149,871 five-minute bars across 643 sessions and 47
symbols contain **3,222** completed role-reversal retests (1,578 long, 1,644
short). Only **16** pass the complete initial prior (10 long, 6 short), spanning
16 sessions and 11 symbols. Rejection reasons are non-exclusive: target room
2,943, reward/risk 2,890, higher-timeframe trend 2,214, retest too early 1,611,
no usable opposing target 1,463, zone too young 832, bleeding 821, retest stale
309, and cooldown 1. The machine-readable report is
`data/metadata/research_store/price_action/h056_structural_preflight.json`.

This is not a failed alpha test; it is an outcome-free sample-shape result. It
shows that the 60-session-per-anchor bootstrap was designed for H055's broad
annotation question and is too small for H056's selective execution question.
No threshold is relaxed from these counts. The next data spend is a wider old-
NSE development manifest plus separately contracted foreign-market data,
followed by label-free coverage and fold manifests. Outcomes remain sealed
until there are enough independent eligible sessions to price an 80-bp useful
effect and the full adaptive development batch is compiled.

**Full NSE development manifest, later 2026-08-25.** Train and the former
validation partition are now explicitly development; test and forward are
excluded. The frozen `h056_nse_development_v1` manifest contains 543,697 PIT
symbol-sessions across 1,712 mapped symbols, split into 53,303 cap-safe native
five-minute requests with 41,054,625 expected maximum rows. Its hash is
`fd9770999c903c05f470e715e5c5029b0ad97bb4d3a7b23fc3a2fd9d369f49f0`;
the acquisition-code hash is
`c06b9bccd88717a8fe9a9797bd5afab384d2803f63d54d59c4f32722177096f4`.
Every partition/year clears 95% mapped symbol-session and 98% mapped traded-
value coverage. The manifest was copied to `hp-ts` and its code hash matched
the remote worker. A one-call authentication probe stopped before acquisition
because the daily Breeze session key was expired. The resumable full pull is
ready but not running; it requires the ordinary manual Breeze refresh and is
not worked around with a different, survivorship-biased source.

**Acquisition started, later 2026-08-25.** After the owner refreshed the daily
token, the updated credential file was copied to the designated `hp-ts`
collector with mode 0600. A bounded one-request probe authenticated and settled
one complete 897-row response with no cap or schema failure. The full frozen
manifest then started in detached `tmux` session `h056_nse_dev` under the
resumable supervisor. The first running snapshot had 124 new attempts, 107
complete, 7 declared partial, 1 empty, 9 unsettled errors, 89,834 rows, zero
authentication failures and zero capped responses in 37.9 seconds. Errors are
retained for supervisor retry; this is a progress snapshot, not an admitted
dataset or coverage result.

---

# H057 — levels do not interrupt the path, and the most-watched ones interrupt it *less* (2026-08-25)

Registered in HYPOTHESES.md with its statistic, grid, controls, primary cell and
frozen bar fixed before the study ran; the registration is timestamped in git at
`d421f6c`, before this read. This spends logged path exposure on the development
partitions (train plus the former validation). No sign, directional hit rate or
payoff was opened. Test and forward are absent from the dataset by construction.

## What was measured

13,860,800 five-minute bars, 302 symbols, 1,081 sessions, 2020-01-22 to
2026-07-21, over the point-in-time stock-futures universe. Decisions on completed
hourly bars; the barrier race on the five-minute path. 203,296,543 approach
events — 18,625,512 real, the rest matched controls.

For every first touch of a knowable level, two symmetric barriers are placed at
`barrier x lagged session ATR` from the touch bar's close: `rejection` back the
way price came, `penetration` onward. Whichever is hit first inside the horizon
wins. Both barriers are equidistant from the same starting price, so **0.5 is a
coin flip by construction** — the null needs no model.

32.6% of races resolved (595,964,675 of 1,829,668,887 cell-events); 67.4% hit
neither barrier within the horizon and 0.06% were `ambiguous` — both barriers
inside one five-minute bar, where the order is genuinely unknowable and is
recorded rather than guessed.

## The result: FAIL, on every detector, at the primary cell

Barrier 0.50 ATR, horizon 24 bars. Frozen bar was contrast >= +0.02 with
session-clustered t >= 3.0 and permutation p <= 0.05.

| detector | control | real | pseudo | contrast | t | sessions |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| anchor | permuted_geometry | 0.4718 | 0.4778 | **-0.0060** | -5.26 | 1,078 |
| anchor | random_price | 0.4708 | 0.4845 | **-0.0122** | -8.79 | 1,077 |
| fractal | permuted_geometry | 0.4932 | 0.4902 | +0.0034 | +6.23 | 1,079 |
| fractal | random_price | 0.4934 | 0.4893 | +0.0042 | +8.56 | 1,079 |
| multi_touch | permuted_geometry | 0.4639 | 0.4682 | -0.0033 | -1.45 | 1,077 |
| multi_touch | random_price | 0.4647 | 0.4711 | -0.0065 | -2.92 | 1,077 |
| volume_profile | permuted_geometry | 0.4664 | 0.4652 | +0.0037 | +0.87 | 1,060 |
| volume_profile | random_price | 0.4722 | 0.4666 | +0.0023 | +0.58 | 1,060 |

The **single most positive cell in the entire 72-cell grid** is
`volume_profile / permuted_geometry / 0.50 / 12` at +0.0120 with t=1.95: 60% of
the required magnitude and failing significance. Nothing anywhere in the
registered neighbourhood approaches the bar.

This is not an underpowered null. With 1,081 independent sessions and 18.6M real
events the standard errors are in the third decimal place; a +0.02 effect would
have been unmissable. The study had ample power to find the thing and did not.

## The one large effect points the wrong way

The largest statistic in the grid is `anchor / random_price / 0.35 / 48` at
**-0.0201, t = -16.97**, and the whole `anchor` family is negative in all 18 of
its cells (mean -0.0046 against `permuted_geometry`, -0.0117 against
`random_price`).

`anchor` is prior-session high/low/close, prior-week extremes, the opening range
and round numbers — precisely the levels a discretionary trader draws, and the
only detector with no free parameters. Price **penetrates those prices more
readily than it penetrates a matched fake price at the same distance**.

A coherent mechanism exists and it is the opposite of the folk model: the most
watched prices are where resting stops and breakout orders sit, so arriving
there triggers continuation rather than reversal. This lab has met this shape
before — H034/H038's resilience score inverted the same way.

This is a direction read off a registered statistic, and its falsification
clause explicitly contemplated a contrast at or below zero, so reporting it is
in bounds. **Trading it is not.** An inverted-level breakout claim is a new
hypothesis carrying its own multiplicity burden and its own economics, and the
economics below do not obviously support it either.

## What the numbers are worth in money

Median session ATR on this universe is 283 bps of price. At a 0.50 ATR barrier,
an expected edge is `(2 x contrast) x 0.5 ATR`:

| | contrast | bps per resolved race |
| --- | ---: | ---: |
| fractal, primary cell | +0.0034 | +0.96 |
| volume_profile, best cell in grid | +0.0120 | +3.40 |
| **the frozen bar itself** | +0.0200 | **+5.66** |
| anchor, primary cell | -0.0060 | -1.70 |

Against a futures round trip of roughly 6-10 bps. Note the third row: **even
clearing the registered bar would not have been tradable as an average.** That
was stated in the registration — the bar was a detectability threshold, not an
economic one — and it holds. The observed effects are a fifth of a threshold
that was itself below cost.

`fractal` deserves one sentence of its own: +0.0034 at t = +6.23 is the exact
failure mode this lab has recorded before. Across 115,728 stock-days the
standard error is tiny, so a 0.3-percentage-point nothing reads as six sigma.
The frozen bar demanded magnitude as well as significance, and that is the only
reason this is not being written up as a discovery.

## What survives

`volume_profile` is the only detector with a consistently positive sign
(mean +0.0054 / +0.0069, positive in every one of its 18 cells) and it is the
only one with a mechanism behind it — participants hold inventory where volume
transacted. It never reaches the bar and mostly fails significance, so it is not
a result. It is the one place a redesign would start rather than a new idea.

## Limits of this read

1. **Resolution.** Only a third of races resolve inside the horizon. The rate is
   computed on resolved races; both books face this identically, but a mechanism
   that acts only over longer horizons would be under-served by a 48-bar cap.
2. **The revisit confound is unfixed.** Real levels sit at prices price has
   already visited; a random fake may sit where it never has.
   `permuted_geometry` matches distance-from-reference, width and volatility but
   not prior-visit frequency. This would matter most if the result had been
   positive. It cuts against the `anchor` inversion less than it might appear,
   since the inversion is *negative* and the confound would if anything inflate
   real levels' reaction.
3. **First touches only.** A level's second or third test is not distinguished
   from its first. Practitioner lore says the two differ; this design cannot see
   that and a descendant would have to.
4. **No selection.** This is an unconditional average over every approach. It
   says information is not present *on average*; it does not prove no selector
   could find a subset. That is a weaker statement than "levels are useless",
   and it is the honest one.

## Consequence for the programme

H057 is **REJECTED at its frozen bar**. Level geometry does not carry the
reaction information the price-action programme was resting on, and the failure
is located precisely: not in coverage, not in power, not in costs, but in the
representation itself.

H056 does not resume on this representation. Its manual retest priors sit on top
of a level concept that has now been measured and does not do what the priors
assume. Reviving it would require a different object, not different thresholds.

What this does not say: it does not say discretionary traders cannot make money,
and it does not say no conditional subset exists. It says that the unconditional
claim — that arriving at a level makes reversal more likely than a matched
non-level — is false on this universe, at this horizon, over six years, and that
the most-watched levels invert it.

---

# H057 audit — the reviewer cannot separate real levels from controls, and would not trade either (2026-08-26)

Registered with its bar before scoring. Balanced 60-case blind deck, 30 real
detector levels against 30 `permuted_geometry` controls, anonymised rebased
140-bar hourly charts ending at the decision bar. Chance is 0.5 by construction.
Spends no new sample.

## The registered bar

| | value |
| --- | ---: |
| discrimination rate | **0.5333** |
| standard error | 0.0644 |
| z vs chance | **0.52** |
| 95% interval | [0.41, 0.66] |
| accuracy on real levels | 0.567 |
| accuracy on controls | 0.500 |
| mean stated confidence | 0.47 (max 0.80) |

The interval covers 0.5. Under the registered rule this **upholds H057's
rejection**: the machine's levels and the reviewer's are the same object on
exactly the cases that were scored, so the null answers the intended question
rather than a different one. The reviewer called "real" 32 times and "fake" 28,
so there is no degenerate answer inflating the rate.

## The take rate is the more informative half

| | taken | rate |
| --- | ---: | ---: |
| real levels | 5 of 30 | 16.7% |
| controls | 5 of 30 | 16.7% |
| overall | 10 of 60 | 16.7% |

Identical to the decimal. **Whatever made those ten charts tradable, it was not
the drawn line** — the reviewer was reading bar structure and ignoring the level,
on both decks equally. The notes say it without prompting: "line is just drawn
through stuff, nothing to trade", "not clear enough levels", "not enough info to
trade it".

So the audit does two things at once. It confirms H057 measured the object the
reviewer means, and it confirms the reviewer would not trade 83% of the
population H057 measured. Both are true and they are not in tension: the study
correctly answered a question about a candidate set nobody would trade.

**Consequence.** H057's fourth stated limitation — that it averages over every
approach and cannot see a selected subset — stops being a caveat and becomes the
live question. The unconditional claim is settled. The conditional one has not
been touched, and the honest way to touch it is to let the reviewer define the
population rather than slice this one.

## A non-result, recorded so it is not rediscovered

On real cases only, recognition by detector: `anchor` 0.714, `multi_touch`
0.714, `fractal` 0.444, `volume_profile` 0.429. The ordering is consistent with
the reviewer's notion of a level being prior-session and multi-day structure
rather than bar patterns or volume nodes — which would also explain PA7's
kappa failure. But each cell holds 7-9 cases, SE is about 0.17, and 0.714
against 0.5 is z ≈ 1.25. **This is a direction for a redesigned representation,
not evidence.** High-confidence calls (>0.50, n=11) scored 0.636 against 0.571
for the rest; n=11, also nothing.

Mean confidence of 0.47 with no case above 0.80 is itself consistent with the
null: the reviewer found the task genuinely hard throughout rather than easy on
a recognisable subset.


## 2026-08-27 — H058 Stage 0 frozen: the reviewer defines the population

Outcome-free. No forward bar was read, loaded or rendered, and the bundle
cannot contain one. Registered at HYPOTHESES.md before the deck was built.

**Why.** H057's audit upheld its own null and simultaneously showed that the
null was about charts the owner would never trade — 16.7% taken, identical on
the real and control decks. Argument cannot close that gap; the only way to
learn whether his selection carries anything is to let him mark his own setups
on a deck he did not construct, and compare what he takes against what he
passes over on the same sessions.

**The deck.** 170 daily charts over the point-in-time stock-futures universe on
the `validation` partition: 120 distinct decisions plus 50 shown a second time,
at least 60 charts later and drawn at 128 bars instead of 140 so the repeat is
the same decision on a differently framed image. Drawn from 60,311 eligible
symbol-sessions across 193 symbols and 352 sessions; 0 source failures. Charts
are anonymised, rebased to a last close of 100, and end exactly at the decision
bar. `test` is untouched.

**Stage 0 measures two things and gates on one.** Test-retest agreement on
take/skip, and the cost of a data point. The bar is registered: kappa below 0.20
ends the programme, 0.40 or above opens Stage 2 at full size, between them Stage
2 opens only at the reduced size. Simulated at this deck's size — 50 pairs, 17%
take rate — a random reviewer is stopped 91% of the time and reads as
full-proceed 1%; a reviewer at a true kappa of 0.60 proceeds 87% and is wrongly
stopped 1%.

**Sizing, which is the point.** At an assumed per-trade dispersion of 1.4R,
detecting +0.20R takes 385 trades and +0.30R takes 171. At a 17% take rate those
are roughly 2,264 and 1,006 charts, or about 4.8 and 2.1 hours. Stage 0 replaces
the assumed take rate and pace with measured ones before that time is committed.

**Two defects found while building, both worth recording.**

*The screening panel's four price columns are not one candle.* `daily_panel`
serves the as-of-open panel, where `open` is date D's opening print while
`high`, `low` and `close` are date D-1's — correct and documented for a morning
screener (`research_data.pipelines.asof`), and wrong for anything that draws a
bar. The first deck was rendered from it, which both mispainted every candle
(only 38% of bars closed at or above their open, and the open sat outside its
own bar's range 23% of the time) and put the *next* session's opening print on a
chart that is supposed to end at the decision bar. `assert_no_forward_labels`
does not catch this: it looks for `fwd_ret_`-prefixed columns, and this leak
arrives in a column called `open`. Charts are now drawn from
`corporate_actions.load_adjusted()`, and `setup_grind.assert_session_aligned`
refuses any frame whose open falls outside its own bar more than 0.1% of the
time — the cheapest possible tell, checked rather than assumed. ATR is now
computed from the bars on the chart, which removes the whole class of
cross-panel alignment error rather than reasoning about it per use.

*Thirty repeat pairs was too few.* At 30 pairs a genuinely consistent reviewer
(true kappa 0.60) would have been wrongly stopped 6% of the time. Fifty pairs
cuts that to 1% for about twenty extra charts, so the deck carries fifty. The
take rate is counted over first showings only; counting a repeat twice would
both narrow the interval dishonestly and drag the rate toward whatever the
repeated cases happened to be.

**Interface.** The deliberative review form is right for sixty cases that each
deserve a paragraph and wrong for a hundred and seventy where how fast the
skips go by is itself the measurement — a form that takes twenty seconds to fill
turns a four-second judgement into a twenty-four-second one, and the take rate it
produces is then a fact about the form. A `ui_mode: "grind"` layout is added
beside it: F takes, J skips, three clicks place entry, stop and target, 1-3 sets
conviction and the deck advances on its own. Pixel-to-price comes from an axis
emitted by the renderer into the case sidecar rather than from constants
duplicated in the browser. Verified in the running app that a click at a chosen
ATR offset round-trips exactly, that a stop on the wrong side of the entry is
refused in both the browser and the server, and that a saved case advances in
frozen deck order — jumping to the first unreviewed case anywhere would let a
repeat land beside its original.

Nothing here is a result about the market. It is a deck, a bar, and a way to
grind through it.


## 2026-08-28 — H058 Stage 0: consistent enough to proceed, at the reduced size

Outcome-free. No forward bar was read. The verdict below comes from the bar
frozen in the manifest at `3b05083`, before the owner saw a chart.

**Result: PROCEED, REDUCED.** Test-retest kappa **+0.348** over 50 repeated
charts (raw agreement 0.76), which falls between the registered stop of 0.20 and
the registered full-size threshold of 0.40. Stage 2 therefore opens only at the
0.30R size. 170 charts in 36.5 minutes.

**Take rate 23.3%** (28 of 120 first showings, 95% Wilson 16.7-31.7%),
comfortably inside the registered [5%, 60%] band. Pace was better than assumed:
**3.0s per skip** against the 5s used in pre-study sizing, and 22.1s per take.
Re-sized on the owner's own numbers, the 0.30R test costs 733 charts and about
1.5 hours; the 0.20R test costs 1,650 charts and 3.4 hours.

**The informative number is not kappa.** Of 10 charts taken on first showing, 6
were taken again; skips reproduced at 80%. Take reproducibility of ~60% means
the take population is a mixture of a reproducible core and a fringe that
averages nothing, which dilutes any real effect toward zero: for the pooled
result to read +0.30R, the core would have to carry roughly +0.50R. The Stage 2
sizing table is correct for the tradability question — live, one trades what one
marked — and optimistic for the question of whether the eye has edge.

**What the geometry says, and it is the encouraging half.** On the 6 charts
taken twice the owner drew materially the same trade: direction agreed 6 of 6,
entry within 0.17 ATR, stop within 0.40 ATR, reward:risk 2.44 against 2.23.
Across all 42 takes, median stop 0.88 ATR (~2.3% of price), median reward:risk
2.45, 35 long against 7 short. At 10 bps a futures round trip costs 0.043R,
which is noise — the universe correction at d421f6c is what bought that.

**Two candidate artefacts checked and dismissed.** The deck drifted from 10
takes on first showings to 14 on second showings, which would be a fatigue or
order effect; McNemar on the 12 discordant pairs gives an exact two-sided
**p = 0.39**, so it is noise and is not interpreted. Separately, the repeats are
rendered at 128 bars rather than 140 to defeat pixel recall, which risks the
reframing itself moving the take rate. In 35 of 50 pairs dropping the 12 oldest
bars left the visible price range identical, and those pairs drifted the same way
(17%→26%) as the genuinely reframed ones (27%→33%). The reframing is not
carrying the result.

Note that the recall caveat and the reframing caveat push in opposite
directions — memory inflates agreement, a changed picture deflates it — and this
design cannot separate them. A future Stage 0 wanting a clean number should
carry three arms: identical repeat, reframed repeat, and fresh chart.

**One instrument defect, and its cause.** The conviction scale was used
12/29/1 across 42 takes — level 3 essentially never. Asked afterwards, the owner
reports he read "conviction 3" as confidence in the strategy as a whole, which he
does not yet have, rather than as a ranking among his own takes. The scale
measured the wrong thing by construction. It is retained for Stage 2 but
reworded to a relative comparison against his own other takes, where an honest
answer is available to someone who doubts the whole enterprise.

**What this does not say.** Nothing about edge. Stage 0 read no outcome, and a
perfectly reproducible reviewer with no edge scores kappa 1.0. Consistency was
a necessary condition and it has been met; that is the entire claim.


## 2026-08-29 — H058 Stage 2 FAILED as an experiment. It is not a null.

**87.5% of the takes never traded.** Of 128 resolved takes, 112 were `no_fill`:
8 stops, 6 time exits, 2 targets. The effective sample was sixteen trades. The
registered futility rule fired STOP on the selection contrast, and that verdict
is **void**, because a statistic that is seven-eighths structural zeros is not
measuring selection. It would have been voided for the same reason had it said
CONTINUE, and that is the test of whether the voiding is principled.

**Root cause, and it is a registration defect of mine.** `EXECUTION_RULES` gave
the entry level a **3-session** window. That number was chosen to fit
`split_v1`'s `max_horizon` of 20 (3 + 15 = 18), not to fit how the owner marks.
He marks patient pullbacks: median entry **2.60 ATR from the last close**, 43.5%
of them beyond 3 ATR, 88 of 131 longs waiting *below* the close and 36 of the
shorts waiting *above* it. A 2.6 ATR move inside 3 sessions is roughly a 1.5
sigma event. The window could not have filled his trades and the 12.3% fill rate
is arithmetic, not evidence.

Fill rate against entry window, computed on the already-spent partition as a
structural diagnostic — **payoffs at the longer windows were deliberately not
computed**, because that is a second rule-modified read of a spent partition:

| entry window | would have filled |
| --- | --- |
| 3 sessions (registered) | 12.3% |
| 5 | 19.2% |
| 10 | 31.5% |
| 15 | 39.2% |
| 20 | 44.6% |
| 30 | 51.5% |

Median time to first touch, among entries that are ever touched, is **8
sessions**. Even an unbounded window fills only about half: **half of his marked
setups never trigger at all.** That is a second sizing defect on top of the
first — 385 takes was never 385 trades, it was at best ~190, so the deck was
undersized for its own bar before the window problem is counted.

**What the numbers were, for the record, and they mean nothing.** Primary
−0.007R (SE 0.046, t −0.15); tradability +0.009R (SE 0.053, t +0.17); matched
skips −0.008R. Sixteen real trades cannot produce an estimate and these are
reported only so that nobody later reconstructs them as suppressed. The
Hansen-Hodrick implementation also returned effective blocks exceeding the
observation count, which is not interpretable and needs fixing before any
successor uses it.

**The full list of what went wrong, in the order it happened.** The Stage 0 gate
opened a 733-chart study at +0.30R and a 1,650-chart study was built instead,
silently lowering the bar to +0.20R. The first resolver booked profitable
stop-outs, exited gaps at the stop rather than the open, and counted fill-day
lows that preceded the entry. The declared futures execution was resolved on
cash bars, pricing shorts an NRI cannot place. The required serial-overlap
correction was absent. Controls were one random skip rather than all of them.
And the entry window was mismatched to the population it was measuring. Every
one of these was found by review rather than by the tests written alongside the
code.

**What it cost.** `test` is spent — read three times, twice for voided interims
and once here. It cannot be reused. Roughly 250 charts were marked under two
CONTINUE verdicts that were themselves artifacts of the resolver bugs.

**What survives, and it is not nothing.** The owner's 544 marks are outcome-free
judgements and remain valid for any successor. The style characterisation is a
real, reusable finding: patient pullback entries a median 2.6 ATR away, half of
which never trigger, held against a 1.65 ATR stop at a 2.15 reward-to-risk. The
resolver is now correct and pinned by adversarial tests that fail loudly on all
three original defects. And the deck, renderer, grind interface and pairing
machinery are sound.

**What a successor requires.** A dataset version purged for roughly 35 sessions
rather than 20, because a window matched to this style plus a 15-session hold
exceeds what `split_v1` was purged for. Sizing that counts *trades*, not takes,
at an assumed fill rate near 50%. The seven PLAN.md 9 baselines. And a fresh
partition: `forward`, which has accrued about 8 sessions, or a new grind on
`validation`. There is no shortcut back to a clean read of `test`.

### The window sweep, and why it settles the question anyway

The entry-window defect above raised an obvious objection: the partition is
already spent, so read it again with a window that can actually fill. That was
done, exploratory and labelled as such, and it does not rescue the hypothesis.

Only the entry window varies; the hold stays at the registered 15 sessions, so
this is a one-dimensional scan of eight cells. The full surface, never the
maximum alone:

| entry window | fill rate | trades | take mean R | take − skip R |
| --- | --- | --- | --- | --- |
| 3 (registered) | 12.5% | 16 | +0.009 | −0.037 |
| 5 | 19.5% | 25 | +0.024 | +0.014 |
| 8 | 28.9% | 37 | −0.016 | −0.017 |
| 10 | 30.5% | 39 | −0.010 | −0.012 |
| 15 | 38.3% | 49 | +0.012 | +0.007 |
| 20 | 43.8% | 56 | −0.000 | −0.045 |
| 25 | 48.4% | 62 | +0.012 | −0.010 |
| 30 | 50.0% | 64 | +0.020 | +0.005 |

**The best cell is +0.014R. The median permuted maximum of the same scan is
+0.052R and its 95th percentile is +0.197R, so the best cell we found is *worse
than the noise floor*; p = 0.683 against the scan's own permuted maximum.**
Three of eight cells are positive. Every take mean sits within ±0.024R of zero.
There is no window at which this works, and the fitted-in-his-favour maximum is
worth 1.8% a year against the 38% the registered bar implies.

This is the honest use of a spent partition. Contaminated analysis manufactures
false positives, not false negatives, so a scan tilted every possible way toward
finding something — eight tries, chosen after seeing an outcome — and still
landing below its own null is a **credible negative**, in a way a positive from
the same procedure would not have been.

**What it does and does not rule out.** At the widest window the sample is 64
trades, an SE near 0.175R, so a true +0.20R edge would be caught only about half
the time. This rules out a **large** edge, which is the only kind worth trading a
₹5-10 lakh book for. It does not rule out something small, and nothing here
should be written up as proof of no skill.

**Consequence, per the narrowed registration.** This retires *one selector*: one
person marking anonymised, rebased 140-day daily charts with no identity, no
market or sector context, no news, no intraday structure, no sizing and no
portfolio constraint. On that object, at every entry window from 3 to 30
sessions, selection carries nothing detectable and the takes make nothing. It
does not retire the owner's live process, and the H058 execution defects mean
the *registered* study still never ran.


## 2026-08-29 — H059: the last F&O tournament found one real lead, not a strategy

The final pass searched **918 configurations** across the four executable
families left standing: H046 bulk-print premium, H037 raw-drawdown reversal,
H026 relative strength inside the contraction screen, and futures-native
basis/OI/price features. H039 low-delivery selloffs entered as a declared
interaction. All 303,401 historical F&O symbol-sessions were used, every entry
was priced at the actual futures open, and multi-session outcomes were admitted
only when the same contract remained live through the exit. Known corporate-
action spans and returns beyond the 60% bad-print guard were removed.

The comparison was deliberately hostile to optimisation: 500 repetitions
shuffled outcomes across symbols inside every entry session and retained the
**best of all 918 cells** each time. The median null maximum was +71.8 bps after
20 bps and its 95th percentile was +138.2 bps. The real maximum was +157.9 bps,
for max-stat p = 0.022.

### The survivor: an isolated strong stock inside a weak sector

The winning rule is not H026's old long-only rule. On an F&O-adapted version of
the original contraction screen, rank candidates by lagged sector breadth,
**short the bottom name**, enter at the futures open and exit the same contract
20 sessions later. It produced:

| quantity | result |
| --- | ---: |
| entry sessions | 130 |
| distinct symbols | 64 |
| raw futures return, gross | +149.6 bps |
| raw return after 20 bps | **+129.6 bps** |
| F&O-universe excess, gross | +177.9 bps |
| excess after 20 bps | **+157.9 bps** |
| shuffled median / 95th-percentile maximum | +71.8 / +138.2 bps |
| maximum-statistic p | **0.022** |
| positive years | 6 of 7 |
| first / second half excess after cost | +146.9 / +168.9 bps |

The neighbouring portfolio sizes survive: bottom two and bottom three return
+115.8 and +110.1 bps excess after cost. Taking *all* candidates tied at the
weakest breadth gives +139.9 bps; banning another entry in a symbol until its
20-session trade exits gives +143.8 bps; and capping every outcome at +/-500 bps
still gives +95.0 bps. Arbitrary tie-breaking and a few giant moves therefore
do not explain the relationship.

The screen is essential. Shorting the weakest-breadth names across the whole
F&O universe earns only +19.7 bps after cost and turns negative in the second
half. The object appears to be a stock whose own tape is still firm and
contracted while participation across its sector has already weakened—an
isolated holdout that catches down over the next month.

### Why this is not ready to trade

The headline Hansen-Hodrick t is 5.38, but that is the wrong number to become
excited about: 130 overlapping 20-session entries contain only about **six
non-overlapping blocks**. The effect climbs from roughly break-even at five
sessions to +39-45 bps at 15 and +110-158 bps at 20, so the large value depends
on the full futures cycle. Same-contract availability puts entries immediately
after the prior expiry; a post-hoc split finds +256.6 bps after cost for calendar
dates above 20 and only +5.1 bps on dates 1-5. That may be month-end/expiry
mechanism or another fit and must not silently become a fifth parameter.

The historical sector labels are a 2026 snapshot. A sector label is less
return-sensitive than current index rank, which was removed from this screen,
but historical membership and the breadth derived from it are still not truly
point-in-time. And 2026 is the one negative year (-54.9 bps, only eight entries).

The raw-money split is less pretty than the excess split: after 20 bps it is
+26.3 bps in the first half and +233.0 in the second. A stop grid does not fix
that. No stop is best at +129.6 bps raw; 15%, 10%, 5% and 3% stops yield +115.1,
+76.7, +40.1 and +11.9 bps. This is a patient relative-weakness hold, not a
tight-risk chart setup.

### The other families

| family | fitted best after 20 bps | why it is not promoted |
| --- | ---: | --- |
| bulk premium | +99.3 bps excess | five-session long-high-premium cell, but HH t 0.96, 4/7 years, no positive neighbour; opposite the immediate H046 continuation and isolated |
| raw drawdown reversal | +86.7 bps excess | HH t 0.96; -68.5 first half, +241.9 second; broader bottom-three cells are positive but weaker |
| futures basis | +10.3 bps excess | bottom-three, five sessions; HH t 0.86 and only +18.1 bps raw after cost—too small for its noise |
| low-delivery selloff | -19.3 bps excess | clean rejection after 20 bps |

### The concrete answer to “why not just optimise?”

We did. An expanding walk-forward chose the best H026-family parameters using
only prior years and traded the chosen cell in the next year. It kept choosing
20-session **long-strength** configurations because those were the early
sample's maxima. They worked in 2022-24, then the selected rule lost **438.9
bps after cost in 2025**. Across five next-year cells, the optimiser averaged
only +11.3 bps and was positive three times.

ELI5: an optimiser is a talent-show judge watching 918 coin-flippers. It can
always name a winner. The useful question is whether it has found a talented
coin or merely the luckiest flip sequence. Here the later weak-breadth short is
interesting because three neighbouring portfolio sizes, both halves, six years,
outlier caps, cooldown and the full maximum-shuffle all point the same way. It
still needs a new episode and correct historical sector membership before the
word *edge* is earned.

**Decision.** Retire the discretionary-price-action programme and the four
failed H059 families. Do **not** archive the entire laboratory yet. Preserve one
small successor: rebuild sector breadth point-in-time, express this as one
entry per futures cycle with whole-lot capital constraints, and paper/forward
track it. If that correction or the next 12-18 monthly cycles removes the
relationship, retire the project without another search.

---

# Addendum — the 25 years nobody opened, and one thing that works (2026-08-29)

**EXPLORATORY, and deliberately so.** Run on explicit instruction to stop
protecting sample and find out whether anything at all is there. No partition
discipline was applied and none is claimed. What makes the central result worth
more than that label suggests is that its primary object — 1995–2019 — has never
been read by any hypothesis in this project, and that the thing found in it was
not chosen by a search.

## The premise that was wrong: this project is not out of data

Every data-state note since 2026-08-20 says the same thing — *the only untainted
data this project has is the future*. That is true of the 2020–2026 panel and
false of the disk. `data/normalized/legacy_bars_adj.parquet` holds **7,316,207
bars, 1995–2019, 6,218 sessions, 3,278 symbols**, corporate-action reconciled
against NSE's own feed back to 2003, bhavcopy-sourced and therefore free of
survivorship bias.

It has been used once, for the H043 dispersion check, which failed on event
density and concluded the panel could not serve *that design*. It has never been
used to test a directional hypothesis. It is roughly **five times** the modern
panel's session count.

## The screen: sixteen features, four eras, one survivor

Top-500-by-trailing-turnover PIT universe, signal fixed at the close of D, entry
at D+1's open, exit at the close of D+h, market-excess against the same-session
eligible cohort, t computed over non-overlapping session blocks.

Decile long-short in basis points, t in parentheses:

| feature | 1995-2004 | 2005-2011 | 2012-2019 | 2020-2026 |
| --- | ---: | ---: | ---: | ---: |
| **mom_12_1** (h=5) | 107 (4.4) | 46 (2.3) | 49 (3.1) | 43 (3.1) |
| **mom_12_1** (h=20) | 337 (3.3) | 98 (0.9) | 212 (3.0) | 192 (3.4) |
| range_pos_52w (h=5) | 78 (3.9) | 41 (2.0) | 56 (3.9) | 16 (1.1) |
| gap reversal (h=5) | −72 (−5.6) | −66 (−6.2) | −31 (−3.5) | −10 (−1.0) |
| vol_20 (h=5) | −104 (−4.3) | −76 (−3.5) | −49 (−2.7) | −20 (−1.3) |
| turn_surp (h=5) | −13 (−1.0) | −52 (−4.7) | −44 (−5.3) | −15 (−1.7) |

**Twelve-month-minus-one-month momentum is the only feature positive at t ≳ 2 in
all four eras.** The overnight-gap reversal and the low-volatility effect were
strong before 2012 and have decayed to nothing — textbook alpha decay, visible
here because the panel is long enough to see it.

This is not a discovery. Momentum is the most-published anomaly in finance. It
is reported because it is *present*, *stable*, and — unlike everything else this
project has found — **at a horizon where the round trip is a quarter of the
signal instead of three times it.** That is the whole difference.

## The book, long-only, costed on both legs

Top-500 PIT universe, 20-session rebalance, 40 bps round trip charged to the
book **and to the benchmark**, every mask and score strictly prior-session:

| panel | rule | CAGR | Sharpe | maxDD | benchmark |
| --- | --- | ---: | ---: | ---: | --- |
| legacy | momentum 12-1, n=40 | 21.88% | 0.83 | −78.3% | 10.20% / 0.51 / −75.6% |
| legacy | mom+52wk+lowvol, n=20 | **23.91%** | **1.32** | −53.9% | ” |
| modern | momentum 12-1, n=40 | **37.03%** | 1.34 | −32.8% | 21.75% / 1.16 / −24.7% |
| modern | mom+52wk+lowvol, n=40 | 25.73% | **1.63** | −17.3% | ” |

Eight of eight cells beat the investable equal-weighted benchmark on Sharpe.
Adding the 52-week-high and low-volatility legs roughly doubles legacy Sharpe
(0.83 → 1.32) and halves the drawdown, at the cost of return in the 2020–2026
melt-up — the same regime dependence H033 ran into.

**Limits, corrected after the stress package below.** 40 bps is optimistic for
Indian delivery equity, where STT alone is 20 bps a side. The book still clears
at 100 bps and the cost of getting there is **3.3pp (legacy) and 4.0pp (modern)**,
not the "roughly 6pp" first written here.
Entry assumes the closing auction. Momentum's −78% drawdown in 2008 is real and
is the known momentum-crash failure mode; a 200-day market-trend filter was
tested and helps at top-500 while *hurting* at top-200, so it is not a clean fix
and is not recommended. The legacy panel's left tail still runs 2–3× the modern
rate from residual corporate actions, blunted here by discarding |daily return|
> 50%.

## Three of my own errors, recorded because they are the instructive part

**A selection lookahead in a benchmark, which nearly produced a false defect.**
The first pass built the comparison index by averaging session D's returns over
a universe selected on session D's *turnover*. Turnover is known at the close;
the return is not. That inflated the benchmark from 21.55% to 25.9% CAGR and
generated an apparent 2–4pp "benchmark defect" in `context.mkt_index` that was
reported before it was checked. It does not exist. This is the fifth lookahead
in this project found somewhere other than the numerator, and the first found in
a *benchmark* — the object nobody audits because it is not the thing being
tested.

**A decomposition that varied nothing.** The attempt to size that supposed
defect compared "rebalance nightly" against "rebalance nightly": the harness's
universe-refresh parameter made the drift branch unreachable, and it read a
clean, confident **+0.00pp**. A null produced by a branch that never executes
looks exactly like a null produced by nature.

**A mean and a t computed on different samples.** The first event-study report
averaged every event session and took its t over every h-th one, which let
H053 print +51 bps with t = −0.5. Fixed to compute both on the same
non-overlapping blocks.

## `context.mkt_index` is a fair hurdle, measured

Since the suspicion was raised it was settled properly. Changing one thing at a
time, CAGR:

| | legacy | modern | effect |
| --- | ---: | ---: | --- |
| A nightly universe, nightly EW reset (`mkt_index`) | 7.77% | 21.55% | |
| B 20d universe, nightly EW reset | 7.82% | 22.03% | universe −0.05 / −0.48 |
| C 20d universe, weights drift | 8.40% | 22.29% | rebalancing −0.58 / −0.26 |
| D C + 40 bps round trip (investable) | 7.63% | 21.39% | cost +0.77 / +0.89 |

Free minus investable: **+0.14pp / +0.16pp CAGR and +0.00 Sharpe.** The
rebalancing term has the *wrong sign* for the story — letting weights drift
earns more than resetting nightly, so daily rebalancing costs this cross-section
money rather than manufacturing it — and the cost term cancels it.

**H033 is untouched.** Nothing here revises the family verdict, and the earlier
suggestion in this session that it might have been a benchmark artifact was
wrong. `mkt_index_investable` is added to `market_regime` as the hurdle a
portfolio claim should quote, with tests, as a documented near-equivalent rather
than a correction.

## H049 and H051–H054: all five rejected, on 31 years

Five hypotheses were registered on 2026-08-24 and never run. The blocker was
event density on the modern panel; the legacy panel removes it. Controls are the
registered baselines — the ordinary weekend against the long closure, month-end
against quarter-end, Monday–Thursday against Friday, and a gap-down without the
intraday rejection. Ten cells per panel, against a permuted max-|t| floor built
by shuffling each event mask within session:

| test | panel | n | ev bps | ctrl bps | contrast | t | floor |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| H051 pre-closure decline, h=10 | legacy | 1,619 | +185.3 | +11.6 | +173.7 | 0.7 | 2.8 |
| H052 post-closure laggard, h=5 | legacy | 2,890 | −27.9 | +26.6 | −54.5 | −1.0 | 2.8 |
| H053 quarter-end loser, h=10 | legacy | 2,992 | −81.0 | +83.6 | −164.6 | −2.0 | 2.8 |
| H054 Friday markdown, h=3 | legacy | 18,817 | −76.5 | −76.0 | **−0.5** | −0.0 | 2.8 |
| H049 selloff + gap rejection, h=10 | legacy | 33,294 | +34.6 | −180.4 | +214.9 | **4.8** | 2.8 |
| H049 selloff + gap rejection, h=10 | modern | 5,355 | −37.8 | −34.4 | −3.4 | −0.0 | 2.5 |

**H054 is the cleanest kill in the set and the one worth reading twice.** The
Friday arm loses 76.5 bps over three sessions on 18,817 events at t = −6.8
against a zero baseline — a large, well-powered, highly significant effect in
the *opposite* direction to the hypothesis, which is exactly the sort of number
that gets written up. Its Monday-to-Thursday control loses **76.0 bps**. The
entire effect is ordinary markdown continuation that has nothing to do with the
weekend. The registered baseline was designed to catch precisely this and it
caught it; without it this addendum would have claimed a discovery.

**H049 is the only cell clearing its floor, and it is not money.** The contrast
is real at t = 4.8, but it decomposes as +34.6 bps for the event arm against
−180.4 for the control. The signal is *"do not buy the gap-down that keeps
falling"*, not *"buy the one that rejects"* — the tradable arm earns 35 bps
gross against an 80 bps bar and a 40 bps cost. And it is absent in 2020–2026
(−3.4 bps, t = −0.0). This is the same shape as H030, H034, H046 and H057: a
real gradient that is not a trade.

**H052 cannot be tested at all**, which is a power result rather than a null.
Market-wide closures of four or more calendar days produce **33 event sessions
in 25 years and 5 in the modern panel**. No estimator recovers an 80 bps effect
from that, and none should be attempted.

## What this changes

The lab's machinery is sound. Pointed at 25 years it had never seen, it
reproduced every documented anomaly in the right direction and the right
magnitude, watched two of them decay on schedule, and rejected five registered
hypotheses with their own registered baselines. **The four programmes' null
results were real nulls, not measurement failure.** That is worth as much as the
positive finding.

The recurring failure mode is now precisely nameable, and it is not overfitting.
Across H030, H034, H044/H046, H049 and H057 the effect was real and smaller than
the cost of collecting it — H057's *registered bar* was itself below a futures
round trip. Every programme hunted at one-to-ten-session horizons where 40 bps
is a third to three times the whole signal. The one thing that survives is the
one thing held for twenty sessions.

## Data state — updated 2026-08-29

The 1995–2019 legacy panel has now been read for direction, exploratorily and
without partition discipline. It is **spent for confirmatory purposes** and must
be labelled that way in any successor. `test` remains spent (three reads),
2020–2023 remains spent (two reads). The only confirmatory sample this project
has is `forward` — sessions after 2026-08-18 — which is the correct place for
the momentum claim registered as [[H060]] to be settled.


## Correction to the section above — the book is not era-stable, the spread is

Run after the tables above, on the same data, before anything was taken to
`forward`. Full detail in HYPOTHESES.md, "H060 stress package".

Two named falsifiers cleared. The cost bar at 100 bps holds with room. And
corporate actions — the stated live data risk — are **not** the source of the
legacy spread: tightening the return guard from 50% to 25% *raises* the edge
from +9.48pp to +10.65pp, and a forward-looking diagnostic that quarantines
every adjustment-factor window leaves it at +9.13pp.

The third falsifier landed. Five-year blocks, momentum n=40 at 100 bps against
the benchmark charged the same:

| block | edge |
| --- | ---: |
| 1995-1999 | **+47.2pp** |
| 2000-2004 | −2.7pp |
| 2005-2009 | −1.4pp |
| 2010-2014 | +10.3pp |
| 2015-2019 | +5.9pp |
| 2020-2024 | +16.6pp |

**Three of five legacy blocks beat the benchmark and the aggregate is carried by
one of them** — 1995-1999, which is also the thinnest and worst-documented
stretch of the archive. Excluding it, the remaining four average about +3.0pp
with two negative.

This does not contradict the era table, and the distinction is the point. The
era table measures the **cross-sectional decile spread**, which is positive at
t ≳ 2 in all four eras and is the robust object. The book is a concentrated
40-name portfolio built on top of that spread, and it is **regime-dependent**:
it can lose to buy-and-hold for five years at a stretch. Only the first should
ever be described as era-stable, and the section above should be read with that
correction attached.

The registration was also tightened as a consequence: it named momentum *and* a
composite without saying which decided the verdict, which is a two-shot test
wearing one bar. The primary is now singular — momentum 12-1, n=40 — and the
composite cannot rescue a primary failure.

---

# Addendum — four directions, one signal (2026-08-29)

`src/research/families/final_tournament.py` is **not mine.** It appeared in the
working tree at 13:40 today, claims the ID H059 for an executable F&O
tournament, and was run by its author at 13:47; its results were committed in
`588677b` alongside this file's previous addendum. It is coherent, self-labelled
`exploratory_all_partitions`, and builds a permuted-maximum null over its whole
grid — which is the right shape.

It was **re-run here independently** at the same 500 permutations and seed, into
a scratch directory rather than over the author's output. The two runs are
**bit-identical** on every family and on the overall statistic, which makes this
a clean reproduction rather than a second opinion. (An earlier note in this
session said the module had never been run. That was wrong — the output sits in
`data/metadata/research_store/h059/` and the check that missed it looked one
directory too high.)

918 configurations over five families, 2020-01 to 2026-08, 303,401 futures rows
across 1,650 sessions. Net 20-session excess in basis points, against each
family's own permuted maximum:

| family | configs | best | null median | null p95 | p | promotable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **relative_strength_screen** | 162 | **157.9** | 65.4 | 138.2 | **0.022** | 20 |
| bulk_premium | 108 | 99.3 | 40.5 | 77.7 | 0.018 | 2 |
| drawdown_reversal | 216 | 86.7 | 27.0 | 65.1 | 0.008 | 7 |
| futures_native | 378 | 10.3 | −7.2 | −1.6 | 0.002 | 1 |
| low_delivery_selloff | 54 | −19.3 | −13.6 | −6.9 | 0.996 | 0 |

Against the **overall** null across all 918 configurations — the statistic that
actually prices the search — the best result is 157.9 bps against a p95 of
138.2, **p = 0.022**.

**Read the margin before the p-value.** The best real configuration sits 14%
above the 95th percentile of its own noise. That is clearing the bar by a
fingernail, on a single regime, on partitions this project has already spent.
`futures_native` is the cautionary row in the same table: p = 0.002 on an effect
of **10.3 bps**, which is under a futures round trip — significance without
money, for the sixth time in this ledger.

**But the identity of the winner is the finding.** `relative_strength_screen` is
[[H026]]. That family has now been found four separate times, by four designs
that share almost no machinery:

| where | what it said |
| --- | --- |
| H026 exploration | +1.230% vs market, t=4.76 |
| **H033 holdout (2020-2023)** | **+1.366%, t=3.31 — passed clause 1 of its frozen bar**; +1.73% vs the same-day pool at t=4.98 |
| this tournament | best of 918 configs, 157.9 bps net at 20 sessions, p=0.022, 20 of 162 configs promotable |
| the 1995-2019 legacy scan | `mom_12_1`, `dist_52w_hi`, `range_pos_52w` all positive in all four eras |

Cross-sectional relative strength is the one thing this project keeps
rediscovering, and H033's split verdict said exactly this two months ago:
*selection inside the screen carries out-of-sample information; turning it into a
portfolio that beats buy-and-hold did not work.* Nothing since has contradicted
either half. **What has repeatedly failed is the portfolio, cost and regime
layer — not the signal.** The H060 block table is the same story again: a
persistent cross-sectional spread sitting under a book that can lose to
buy-and-hold for five years.

That reframes what is left to do. The open question was never "is there a
signal". It is whether a signal of this size can be wrapped in a book that
survives costs and a bad regime — and on the evidence of H033, H060's blocks and
this tournament, the honest answer is *sometimes, and not reliably.*

**One row not to build on.** The module's focused stop sweep reports 129.6 bps
net with `effective_n = 6`, a first half of 26.3 bps and a second half of 233.0.
The module flags it itself as post-selection optimisation on the same sample.
Six effective observations split 9:1 across halves is not a result.

---

# Addendum — H059's surviving cell does not survive step 1 (2026-08-29)

The successor plan's own first step was *rebuild historical sector breadth
point-in-time*, with the stopping rule *if either step kills it, retire the
project without another search*. It fired. The deeper reason it fired is not the
one the plan anticipated.

## What was contaminated, and which half is repairable

`meta.sector` comes from `nse_archive.build_symbol_metadata()`, which downloads
**today's** NSE index constituent CSVs — the same today-snapshot source whose
adjacent line, `rec["size_tier_rank"]`, produced the fourth lookahead in this
project (H033). The module's author explicitly disabled the size-rank screen to
avoid it and then inherited it through `sector`.

Two distinct contaminations follow:

- **Membership survivorship.** A name absent from today's lists gets no sector,
  and `build_h026_candidates` drops it via `dropna(subset=["sector_breadth"])`.
  Both the breadth denominator and the shortable universe are conditioned on
  surviving to 2026. Of 3,348 symbols that traded 2020-2026, today's lists label
  **537**; `announcements.industry` labels **1,042**, including delisted names —
  **827 gained.**
- **Classification drift**, which is *not* repairable here. `announcements.
  industry` is also a per-symbol snapshot: **0 of 1,413 symbols ever change
  label.** It fixes membership and nothing else. This is the weaker half — a
  bank stays a bank, while index membership churns constantly — and it is left
  standing rather than papered over.

## The re-test, through the module's own code path

`frame.load_daily_panel` was monkeypatched so only the label source moves; the
returns, costs, excess convention and permutation machinery are the module's.

| arm | n | net20 excess | HH t | halves | +yrs |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 published, module as-is | 130 | **157.9** | 5.38 | +146.9 / +168.9 | 6/7 |
| 2 my breadth, **snapshot labels**, no extra shift | 127 | 92.5 | 2.01 | +68.1 / +116.5 | 5/7 |
| 3 arm 2 + an as-of shift | 127 | 89.3 | 1.61 | +58.6 / +119.5 | 5/7 |
| 4 announcement membership, no shift | 130 | 74.1 | 1.28 | +176.8 / **−28.5** | 3/7 |
| 5 announcement membership + shift | 129 | **55.7** | 0.89 | +215.4 / **−101.5** | 4/7 |

The tournament's own overall permuted null is **median max 71.8 bps, p95 138.2
bps.** Only the published arm clears it. The membership-repaired arms sit at or
below the *median* of noise, their HH t falls from 5.38 to 0.89, and the
half-stability that was the headline evidence **inverts**: the second half goes
from +168.9 to −101.5.

## The real finding is in arm 2, and it is worse than the survivorship

Arm 2 holds the labels fixed and only re-derives breadth — "share of sector
members above their own 50-session EMA" — and the result still falls from 157.9
to 92.5. That could have been a bug in the re-derivation. It is not:

| my breadth vs the pipeline's, 30,362 overlapping sector-days | |
| --- | ---: |
| correlation | **0.968** |
| mean absolute difference | 4.93 breadth points |
| **sessions agreeing on which sector is weakest** | **61.3%** |

**The rule is `k=1, short_bottom`: it shorts the single candidate from the
`argmin`-breadth sector.** An argmin over ~20 noisy sectors is not stable even
when the underlying statistic is 97% correlated — two faithful implementations
pick a different sector, and therefore a different trade, **four sessions in
ten**. The strategy as specified is not identified by the data. Nothing about
point-in-time membership is needed to say that.

It also explains the k-ladder, which had been read as reassuring. Published,
k=1 (157.9) beats k=2 (115.8) and k=3 (110.1); repaired, the order reverses —
k=1 (55.7) is *worst*, k=2 is 83.5, k=3 is 92.9. Averaging over more names damps
the argmin instability. **k=1 leading its own neighbourhood was the signature of
the defect, not evidence against it.**

## Verdict

H059's surviving cell is **REJECTED at step 1 of its own successor plan**, under
that plan's stated stopping rule. What is retired is this cell, not the
observation underneath it — cross-sectional relative strength has now shown up
in four places (H026, the H033 holdout, this tournament, the legacy scan) and
none of that is touched. What died is the specific claim that shorting the
argmin-breadth name inside the F&O contraction screen carries +1.58% a trade.

Two things worth keeping for whoever comes next. A `k=1` argmin rule over a
noisy cross-sectional statistic should be treated as suspect **by construction**
and tested against a re-derivation of its own input before anything else is
spent on it — this cost one afternoon and would have cost twelve to eighteen
forward cycles. And a per-symbol label column that never changes over time is a
snapshot wearing a panel's shape; the one-line check (`groupby(symbol).nunique()
> 1`) belongs in the pipeline, not in a post-mortem.

---

# Addendum — H061–H063: the stock-option wheel has a payoff pattern, not a tradable edge (2026-08-30)

The final open branch was a cash-secured, physically settled stock-option wheel.
It required a fresh full-strike archive because the older futures files had
dropped strike and option type: **20,627,843 banded option rows, 287 stock
symbols, 2020-01 to 2026-08**, joined to raw cash closes and futures-derived lot
sizes. Nifty is taken from NSE's daily all-index archive; its published dividend
yield is accrued so the hurdle is total return rather than the easier price
index.

Two implementation defects were found before the corrected read. The stationary
bootstrap never restarted a block, so every draw had the same mean and its
interval collapsed to a point. And nominal expiries could collect premium and
interest without settling: June 2023's holiday-shifted contract settled one day
early, while the incomplete August 2026 contract had not settled at all. The
calendar now uses the contract's last trading session, excludes the incomplete
tail and fails closed on a missing cash settlement. HDFC's July-2023 contracts
are the special case that proves why this must be symbol-specific: the merger
force-expired every displayed July/August/September contract on 12 July.

## H061: the ordinary ten-name wheel fails

Base: ten equal slots, puts and calls nearest 5% OTM, 50-contract strike bar,
hold to expiry, 5% premium haircut, dated STT, physical-delivery charges and
0.25% broker settlement fee, collateral at repo.

| series | CAGR | vol | Sharpe | monthly-close max DD |
| --- | ---: | ---: | ---: | ---: |
| wheel | **7.85%** | 17.00% | 0.226 | −31.48% |
| Nifty 50 total return | 12.65% | 19.19% | 0.440 | −28.04% |
| Nifty TR + cash, volatility matched | **12.04%** | 17.00% | **0.440** | −24.86% |

The wheel's annualized mean gap to the matched hurdle is **−3.64pp**, stationary-
block 95% interval **[−9.39pp, +1.49pp]**. Even a frictionless ceiling returns
10.54%, below the passive hurdle. Removing the physical-settlement fee adds less
than one point; removing the premium haircut adds 1.38 points; setting collateral
yield to zero cuts CAGR to 4.01%. Costs hurt, but they are not why it loses. The
payoff itself gives up too much equity upside for the premium retained.

## H062: diversification and farther strikes reveal a coherent surface

CAGR edge over the volatility-matched hurdle:

| slots | 5% OTM | 10% OTM | 15% OTM |
| ---: | ---: | ---: | ---: |
| 20 | +0.07pp | **+2.24pp** | +1.64pp |
| 30 | −0.72pp | **+1.58pp** | +0.72pp |
| 40 | −0.02pp | **+0.87pp** | +0.37pp |

The 10%-OTM column wins at all three breadths and decays smoothly as breadth
rises. That is the only new pattern worth preserving: diversify single-name
assignment losses and sell less frequently exercised protection. It is not a
single optimized maximum. But the inherited 20-slot / 5%-OTM primary only ties,
and whole-lot capital already weakens it.

## H063: the promising 20-slot / 10%-OTM cell fails execution in combination

The first attack removed an actual timing impossibility. H062 ranked names and
strikes on the completed entry-day option tape, then assumed a fill on that same
close. Ranking and strike choice were moved back one trading session; the exact
strike then had to print on entry day. The result improved rather than vanished:
**14.52% versus 11.88% matched CAGR, 0.635 versus 0.474 Sharpe**, annual return-
gap interval **[−1.73pp, +6.58pp]**.

| attack on lagged 20-slot / 10%-OTM | CAGR edge | Sharpe edge |
| --- | ---: | ---: |
| 10% premium haircut | +1.86pp | +0.116 |
| 20% premium haircut | +0.33pp | +0.024 |
| actual last-trade price | +2.34pp | +0.144 |
| minimum 250 contracts at strike | +0.58pp | +0.037 |
| **last trade + 250 contracts + 10% haircut** | **−0.23pp** | **−0.008** |
| combined, whole lots at INR 2 crore | **−0.50pp** | **−0.034** |
| combined, whole lots at INR 10 crore | **−0.42pp** | **−0.021** |

At INR 50 lakh the combined book writes only **1.7 legs on average**, so its
apparently high Sharpe is mostly repo with almost no wheel. At INR 2 crore and
INR 10 crore it fills roughly twenty legs and loses to the matched passive book.

**Verdict.** There is a believable gross payoff pattern and no demonstrated
tradable edge. It survives any single charitable execution assumption and dies
when reasonable assumptions are applied together; its confidence intervals
include zero throughout. H061, H062's investable claim and H063 are retired.
Do not optimize another strike/slot cell on this archive. The only live project
claim remains H060 momentum on future data; the wheel adds no reason to keep an
active research branch.

---

# Addendum — H066–H071: index wheel, put hedges and quality/tranche tests (2026-09-05)

Four proposed extensions were separated because they answer different
questions. The Nifty wheel is an index/ETF payoff test; the bull put spread is a
defined hedge on the stock wheel; and Piotroski is a point-in-time data-coverage
problem before it is a strategy. A later user-supplied rule made the staggered
tranche claim testable as a declared approximation.

## H066: the Nifty wheel spends too much time out of the equity

The primary sells weekly NIFTY options nearest 0.15 absolute delta, keeps puts
fully cash-secured, and owns NIFTYBEES only after an in-the-money put settlement.
The option settles in cash against the index and the ETF is bought or sold at
that day's close, so the index/ETF basis and the extra trades are retained.

| series | CAGR | vol | Sharpe | daily max DD |
| --- | ---: | ---: | ---: | ---: |
| weekly 0.15-delta Nifty wheel | **5.90%** | 11.31% | **0.094** | −32.54% |
| NIFTYBEES buy-and-hold | 12.11% | 15.89% | 0.471 | −36.34% |
| Nifty 50 total return | 12.32% | 17.86% | 0.448 | −38.28% |
| Nifty TR 63% + cash 37% | **10.16%** | 11.31% | **0.448** | −25.63% |

The annualised mean gap to the volatility-matched hurdle is **−4.01pp**, with a
stationary-block 95% interval of **[−9.85pp, +1.32pp]**. The wheel is in the ETF
only **33.0%** of sessions: 230 puts produced 22 assignments into the ETF, and
116 calls produced 22 exits. Its 9.08% annualised option premium did not repay
the opportunity cost of missing a positively drifting index. Weekly 0.30-delta,
weekly 2%-OTM, both monthly variants, a five-per-cent premium-haircut diagnostic
and zero cash yield all remained below NIFTYBEES. H066 is rejected, descriptively
only because its result existed before registration.

## H067: the bull put spread buys excellent drawdown control too dearly

The executable H063 stock wheel was rerun with a same-expiry lower put at an
actually traded strike. Both legs use the entry-day last print after lagged
selection; the short premium is cut ten per cent, the long premium is marked up
ten per cent, and option purchase and physical-exercise costs are charged.

| arm | CAGR | matched CAGR | Sharpe | matched Sharpe | max DD |
| --- | ---: | ---: | ---: | ---: | ---: |
| H063 unhedged | 12.07% | 12.30% | 0.465 | 0.474 | −27.71% |
| **five-point bull put spread** | **7.28%** | **8.79%** | **0.276** | **0.474** | **−7.22%** |
| ten-point shape diagnostic | 10.20% | 10.47% | 0.451 | 0.474 | −15.62% |
| five-point, INR 2 crore whole lots | 6.68% | 7.91% | 0.247 | 0.474 | −4.94% |
| five-point, INR 10 crore whole lots | 6.76% | 8.66% | 0.213 | 0.474 | −7.37% |

The five-point hedge's aggregate purchase cost was **0.789% of short-put
notional**, leaving only **0.364%** net spread credit after both legs' execution
and fees, while only 6.64% of long puts exercised. It did what insurance should do—volatility
fell from 15.87% to 7.00% and the crash tail was capped—but failed both return
and Sharpe clauses. The ten-point diagnostic also lost to unhedged and matched
passive. H067 is rejected under its frozen stop; no other width is searched.

## H068: Piotroski 8–9 cannot be tested from the present archive

The coverage check is intentionally generous: any successfully archived XBRL
document counts, even before verifying that all nine F-score components and
their prior-period comparatives are available and unambiguous. The archive has
only five symbols. Against the H063 pre-outcome liquidity universe this covers
**327 of 10,385 eligible symbol-entry rows (3.15%)**, with a median of **three**
archived names per 20-slot cycle. The frozen gates were 80% and ten names.

H068 is therefore **NOT TESTED**, not rejected. Building a reducer over five
survivor-selected names would create exactly the point-in-time and restatement
lookahead the gate was meant to prevent. A valid attempt requires a broad
original-filing backfill, `first_tradable_session` eligibility, prior-version
comparatives, context-ambiguity checks and an explicit treatment of financial
companies before any wheel outcome is opened.

## H069: the 33%-33%-34% tranche rule lowers risk by surrendering return

The accessible primary description of Ranjit Kumar Mohanty's refinements names
[staggered buying and a bull put spread](https://www.elearnmarkets.com/face2face/details/how-this-64-year-old-became-a-successful-stock-market-trader),
but does not publish exact tranche triggers. The user's follow-up supplied a
specific version: buy 33% at entry, another 33% at the midpoint to the call
strike, and 34% when the strike is reached. It was frozen with daily-close
fills; a gap across both thresholds buys both tranches at the observed close,
not at prices the daily tape never offered.

| arm | CAGR | vol | Sharpe | daily max DD |
| --- | ---: | ---: | ---: | ---: |
| fully funded seven-stock covered call | **20.67%** | 16.61% | **0.908** | −29.01% |
| **33%-33%-34% staged call** | **14.43%** | 13.01% | **0.702** | **−22.53%** |
| staged volatility-matched Nifty + cash | 10.98% | 13.00% | 0.463 | −28.38% |
| current seven-stock basket, price return | 30.46% | 24.37% | 1.010 | −35.27% |

The staged arm beats its risk-matched Nifty hurdle, but fails the question it
exists to answer. It trails the fully funded control by **5.94pp annual mean
return**, stationary-block 95% interval **[−10.05pp, −1.91pp]**, and loses
0.206 of Sharpe. The drawdown reduction is real and comes from owning less
stock: mean equity exposure falls from 76.6% to 60.1%.

The financing description is also wrong in an important way. All 372 calls are
written for the full target position after only the first tranche is held. Peak
uncovered stock notional reaches **51.29% of current equity**. The daily cash
book never goes negative under full cash accounting, but that says nothing
about the SPAN required by a partially naked short call. H069 is rejected under
its return-and-Sharpe clauses. The basket's 30.46% price CAGR is a warning, not
a discovery: these seven present-day winners were selected after most of their
rise, so neither covered-call result is evidence for historical stock selection.

## H070: a rough historical Piotroski reconstruction makes the wheel worse

The proper XBRL gate remains failed. At the user's request a second, explicitly
approximate panel was built from public Screener annual tables, following the
[nine directions in Piotroski's original paper](https://www.anderson.ucla.edu/documents/areas/prg/asam/2019/F-Score.pdf).
The archived pages are present-day and potentially restated. Operating margin
stands in for gross margin, `Other Assets / Other Liabilities` for current
ratio, and reported equity capital for issuance. Scores become usable six
months after fiscal year end, which blocks obvious fiscal-year leakage but not
restatement lookahead.

The approximation covers all **379/379** liquid seven-basket symbol-entry rows.
The price of score 8–9 is breadth: a median of only **two** names qualifies per
cycle.

| arm | CAGR | vol | Sharpe | monthly max DD |
| --- | ---: | ---: | ---: | ---: |
| seven-stock wheel, unfiltered | **6.85%** | 7.09% | **0.217** | −13.08% |
| approximate score 8–9 wheel | **4.76%** | 4.99% | **−0.108** | **−9.38%** |
| filtered volatility-matched Nifty + cash | 7.88% | 4.98% | 0.474 | −6.35% |

The filter lowers drawdown because it leaves more cash idle, not because the
remaining positions earn more. H070 is rejected. This says nothing reliable
about Piotroski itself: it is one restated-data proxy on seven survivor-selected
names, and the original score was designed to separate distressed high-book-to-
market firms rather than today's large-cap compounders.

Latest score eligible under the deliberately conservative six-month lag at the
end of the option sample (2026-08-18): **BEL 8, HAVELLS 8, INDHOTEL 8, HAL 5,
JUBLFOOD 6, SIEMENS 6, ABB 4**. These are approximate reconstructions, not
vendor scores.

## H071: the supplied 30/12.5-delta spread also fails

The second Mohanty arm was made closer to the supplied description than H067.
Actual prior-session last prices were inverted only to label strikes; median
absolute deltas landed at **0.310 short and 0.123 long**, with a 6.72% median
strike width. Entry still requires both exact strikes to print the next session,
and every payoff uses observed premiums and physical settlement.

| arm | CAGR | Sharpe | monthly max DD | matched CAGR |
| --- | ---: | ---: | ---: | ---: |
| 0.30-delta short-put wheel | 7.09% | 0.214 | −16.87% | 9.61% |
| 0.30/0.125 spread wheel | 6.27% | 0.136 | −13.47% | 9.07% |
| **score 8–9 + spread** | **4.90%** | **−0.057** | **−13.39%** | **8.39%** |

The long put exercises in only 5.47% of unfiltered spread writes. It improves
the settled drawdown by 3.40pp but reduces return and Sharpe; the approximate
quality filter reduces both again. None beats its volatility-matched passive
hurdle. H071 rejects the combined branch without a delta or score rescue scan.

## Tax and SPAN: explicit boundaries rather than invented precision

Every result above is **pre-tax on both strategy and benchmark**. That is the
neutral comparison the data supports; it is not an after-tax estimate. The
wheel's much higher turnover means a tax model would not cancel symmetrically,
so no post-tax ranking is claimed without an investor entity, holding-period and
loss-offset specification.

Historical SPAN/exposure margin is also absent from the daily chain. H067 stays
fully cash-secured and therefore establishes the spread's payoff and cash loss,
not return on broker margin. The separate covered-call run measured a peak
daily mark-to-market funding drain of **9.86% of starting equity** even though
the shares covered the call; the fully cash-secured index wheel's corresponding
external funding need was zero. Neither number is a reconstruction of SPAN.
A margin-relief or tranche-capacity claim needs dated margin inputs plus a
liquidation rule, with variation-margin cash tracked separately from initial
margin.
