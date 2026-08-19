# brickbreak — NSE swing-trading research

**Phase 0** (complete): Breeze data-access feasibility spike → [FINDINGS.md](FINDINGS.md), verdict **GO**.
**Phase 1** (current): historical daily screener + interactive threshold explorer. No trading, no backtest, no second-level fetching.

---

## Phase 1 — the daily screener

The funnel, in order. Every threshold is a field on `ScreenConfig`; nothing is
baked in as a belief.

```text
point-in-time universe (that day's bhavcopy)
  -> tradeability   price / series / traded
  -> size bucket    exclude the largest N (default 250)
  -> liquidity      median 20d traded VALUE, not share count
  -> sector uptrend equal-weight sector index EMA, and/or sector breadth
  -> stock uptrend  EMA stack, close above EMA50
  -> contraction    ATR ratio, base depth, BB-width percentile, NR7, ...
  -> candidate      only these names/dates ever need 09:15-09:20 tick data
```

### Where the daily data comes from — not Breeze

Phase 0 assumed Breeze for daily bars. NSE's own archives turn out to be
strictly better for this layer, and need no authentication:

| Source | Gives us |
| --- | --- |
| `sec_bhavdata_full_DDMMYYYY.csv` | full-universe daily OHLCV **plus turnover and delivery %**, ~2,500 names/day, back to 2020 |
| `ind_nifty*list.csv` | sector labels (Industry) and size tiers (50/100/200/500/750) |

Bhavcopy is **point-in-time by construction**: each file lists exactly the
securities that traded that day, which is what removes survivorship bias.
Breeze is now needed *only* for 1-second opening data on screened candidates.

> **Three archive traps (all handled, all regression-tested):**
>
> 1. **Holiday URLs don't 404.** NSE serves the *previous* trading day's file —
>    requesting 26-Jan-2026 returns 23-Jan-2026 rows. Taking the URL date on
>    faith duplicates a session onto every holiday.
> 2. **A session's file is not always at that session's URL.** The 2021-11-04
>    Muhurat bhavcopy is served at the **05112021** URL. So every response is
>    filed under the date *inside* it, never the date requested — which handles
>    trap 1 as a side effect.
> 3. **NSE trades on some weekends.** Union Budget Saturdays, Diwali Muhurat and
>    disaster-recovery drills are real sessions on Sat/Sun. A Mon–Fri-only sync
>    silently dropped ten of them; each hole reads downstream as a market-wide
>    one-day price step. Weekends are now requested and cached as markers.
>
> Plus one genuine one-off: on **2022-08-08** the `.csv` URL returns an XLSX
> workbook, so the parser sniffs for a zip header and falls back.

### Corporate actions — reconciled, not asserted

Bhavcopy prices are raw: TATASTEEL's 1:10 split on 2022-07-28 appears as a
−90% day. Untreated it corrupts every EMA, ATR and `ret_60d` spanning the
ex-date.

The obvious shortcut — read the adjustment out of bhavcopy's `PREV_CLOSE` —
**does not work**. NSE leaves that column raw on TATASTEEL's split and
pre-adjusts it on DRCSYSTEMS'. It is inconsistent, so it is unusable either way.

Instead, two sources are cross-checked. NSE's corporate-actions API gives exact
stated ratios but an occasionally-off ex-date; the tape shows exactly where
prices stepped but cannot tell a 1:2 split from a stock that genuinely halved.
A ratio is applied **only where both agree** (739 of 847 ex-date events), and
every disagreement is written to `data/metadata/ca_reconciliation.parquet`
rather than silently resolved.

Adjusted bars carry `*_raw` twins. Indicators use adjusted prices; anything
asserting what was *tradeable* — the minimum-price screen, a stop, a circuit
limit — uses the price that actually printed.

See the 2026-08-19 addendum in `FINDINGS.md` for the full reconciliation, and
for the three findings that fell out of it: actions sharing an ex-date must be
combined, `Bonus Ncrps 4:1` is not an equity bonus, and the corporate-actions
feed keys on today's symbol while the tape keys on the old one.

### Sector uptrend — two independent reads

NSE publishes no free market-cap file and no sector-index history covering
smaller names, so sector trend is derived from the bars themselves:

1. **Equal-weight synthetic sector index** — mean daily return of a sector's
   constituents, compounded. Equal-weight rather than cap-weight because we have
   no caps, and because a cap-weighted sector index is mostly a proxy for its two
   largest members, which is not what "the sector is moving" means.
2. **Sector breadth** — % of constituents above their own EMA50. Robust to one
   megacap dragging the index.

`sector_mode` selects `index` / `breadth` / `either` / `both` / `off`.

### Contraction — a family, not one number

The description ("volatility contraction, small-range or doji-like candles")
maps onto several measurable things that don't always agree, so
[src/indicators.py](src/indicators.py) computes all of them and lets the screen
decide: `atr_ratio` (ATR5/ATR20), `base_depth` (k-day high-low as % of price),
`bb_width_pctile` (percentile-ranked, since 3% is tight for a smallcap and loose
for a large cap), `range_pct_ma`, `nr_k` (NR7), `body_ratio`/`doji_like`,
`inside_day`, `vol_squeeze`, and `contraction_steps` (successively tighter
blocks — the VCP shape).

### Size buckets — an honest limitation

NSE publishes no free market-cap file (`MCAP*.xlsx` 404s) and Breeze's master has
`IssueCapital` empty for all 2,901 names, so a true continuous market-cap rank is
**not available**. `size_tier_rank` is instead the smallest NSE broad index
containing the symbol — 50, 100, 200, 500, 750, or 9999 (outside NIFTY Total
Market). Coarse, but real and roughly point-in-time. Treat it as buckets:
1-50, 51-100, 101-200, 201-500, 501-750, 751+.

Sector labels cover ~750 symbols (NIFTY Total Market). Everything below is
`UNCLASSIFIED`; `sector_require_labelled` controls whether those are dropped.

### Running Phase 1

```bash
.venv/bin/python -m src.cli sync-nse --start 2022-01-01
```
Downloads bhavcopy + index lists. No auth. ~1,200 files, a few minutes.

```bash
.venv/bin/python -m src.cli sync-corp-actions
```
Fetches NSE corporate actions, reconciles stated ratios against observed price
steps, and writes `data/normalized/daily_bars_adj.parquet`. Prints which events
were adjusted, which were resolved to a pre-rename ticker, and which were left
raw. Run this **before** `build-metrics`.

```bash
.venv/bin/python -m src.cli build-metrics
```
Computes the indicator panel once into `data/normalized/screen_metrics.parquet`,
using the adjusted bars when they exist (and warning loudly when they do not).

```bash
.venv/bin/python -m src.cli serve
```
Opens the interactive screener at http://127.0.0.1:8765 — move thresholds and
watch the funnel and candidates/day respond. Filtering runs server-side in
pandas over the full panel, so the whole history stays explorable.

```bash
.venv/bin/python -m src.cli screen --set min_size_rank=500 --set min_median_tv_cr=2
```
Headless equivalent, prints the funnel summary as JSON.

---

# Phase 0 — Breeze data-access feasibility spike

A small, throwaway-grade tool that answers one question empirically: **can ICICI
Direct's Breeze API supply historical NSE cash-equity data good enough to
research a swing-trading strategy that depends on first-five-minutes-of-session
behaviour?**

There is no strategy code here, and there should not be until
[FINDINGS.md](FINDINGS.md) reaches a verdict.

## What it does

| Module | Purpose |
| --- | --- |
| [src/config.py](src/config.py) | Env/credential loading, paths |
| [src/security_master.py](src/security_master.py) | Downloads + parses ICICI's public NSE scrip master; maps NSE symbol → ISEC `stock_code` |
| [src/breeze_client.py](src/breeze_client.py) | Thin instrumented wrapper; times and logs **every** call to `data/metadata/api_calls.jsonl` |
| [src/universe.py](src/universe.py) | The 10-security test universe (liquid / thin / delisted) |
| [src/fetch_sample.py](src/fetch_sample.py) | The probe matrix — depth, limits, stability, corporate actions, indices |
| [src/validate_data.py](src/validate_data.py) | Data-quality checks → machine-readable JSON |
| [src/storage.py](src/storage.py) | Parquet raw + normalized storage |
| [src/estimate.py](src/estimate.py) | Extrapolates full-download cost from measurements |
| [src/cli.py](src/cli.py) | Entry point |

## Setup

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
```

### Environment variables

Copy `.env.example` to `.env`. `.env` is gitignored; never commit it.

| Variable | Lifetime | Where it comes from |
| --- | --- | --- |
| `BREEZE_API_KEY` | long-lived | Breeze app registration page |
| `BREEZE_API_SECRET` | long-lived | Breeze app registration page |
| `BREEZE_SESSION_TOKEN` | **expires daily** | browser login, see below |

### Daily login (required before any live call)

Breeze has no headless auth. The session token must be obtained through an
interactive browser login, and it expires every day around midnight IST.

```bash
.venv/bin/python -m src.cli login-url
```

Open the printed URL, log in with your ICICI Direct credentials, and copy the
`apisession` value out of the redirect URL. Paste it into `.env` as
`BREEZE_SESSION_TOKEN`, then:

```bash
.venv/bin/python -m src.cli check-auth
```

## Running

```bash
.venv/bin/python -m src.cli master
```
Downloads and summarizes the NSE scrip master. **Needs no authentication** —
run this first to see the universe stats.

```bash
.venv/bin/python -m src.cli run --quick
```
Connectivity + daily + first-five-minute probes only (~30 calls).

```bash
.venv/bin/python -m src.cli run
```
The full matrix: historical depth walk-back, max-range-per-call, repeat
stability, delisted securities, corporate actions, index availability.
A few hundred calls, throttled to ~85/min by default (`--throttle`).

```bash
.venv/bin/python -m src.cli estimate --securities 2900 --bytes-per-row <measured>
```
Extrapolates storage/calls/duration from the measured call log.

```bash
.venv/bin/python -m pytest tests/ -q
```
26 tests, all offline except the scrip-master download.

## Outputs

```text
data/
  raw/         one parquet per API call, fields exactly as returned
  normalized/  interval=<iv>/<code>__<call_id>.parquet
  metadata/
    api_calls.jsonl          append-only log of every call (the evidence base)
    feasibility_report.json  the full probe matrix result
    universe_summary.json    scrip-master stats
    cost_estimate.json       extrapolation
```

Normalized schema: `security_id, symbol, timestamp, open, high, low, close, volume`.

Timestamps are stored **tz-naive IST wall-clock**. Breeze labels its stamps with
a `Z` suffix but the values are IST; attaching UTC would shift every bar by
5h30m. `validate_data` asserts intraday stamps land inside 09:15–15:30 to keep
that assumption honest.

## Gotchas the spike proved the hard way

These are measured behaviours, not warnings copied from docs. See
[FINDINGS.md](FINDINGS.md) for the evidence.

- **1,000-row hard cap per call, returning the *tail*.** A wide request gets
  `Status: 200` and silently drops the *beginning* of the range. Always chunk
  under 1,000 rows and assert the returned span.
- **`stock_code` must be the ISEC short code.** `RELIANCE` returns 0 rows with
  no error; `RELIND` works. `TCS` maps to itself, so a few large caps can make
  broken code look fine.
- **Daily data is unadjusted after ~2023.** A single series can contain an
  artificial -50% or -90% step across a split/bonus ex-date.
- **Silent archive gaps exist** (2026-08-05 is missing 15:16-15:30 across
  symbols). Missing data arrives as HTTP 200 with fewer rows.
- **1-second bars are sparse**, only seconds with trades. This loses no volume:
  1s sums match 1-minute totals exactly.
- **Use v2 for everything.** v1 cannot serve 1-second data and disagreed with v2
  on row counts for the same daily window.

## Deliberately not here

No dashboards, no database, no strategy engine, no order execution, no
portfolio simulation, no optimiser, no agents. Phase 0 is a measurement
exercise.

## Known limitation carried forward: survivorship bias

Retrieval of delisted history **works** — `ANDBAN` (Andhra Bank, merged 2020),
`CENBN` (Centurion BoP, merged 2008) and `BHAFIN` all returned data for their
trading years. The problem is **discovery**: the scrip master is a current-day
snapshot carrying only ~57 inactive EQ stubs, with `DateOfDeListing` and
`DeleteFlag` empty in all 5,729 rows.

A point-in-time universe therefore needs NSE's bhavcopy archive, joined to ISEC
codes via ISIN. See the `PLACEHOLDER` section in
[FINDINGS.md](FINDINGS.md#placeholder-point-in-time-universe-future-work).
