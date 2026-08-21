# brickbreak

An AI-driven trading research laboratory for NSE equities.

`MISSION.md` is the authoritative statement of purpose. The question the whole
repository is arranged around:

> **Can an AI, given rich point-in-time market context, identify unusually
> attractive trading opportunities better than strong simple quantitative
> baselines?**

Not *does the AI make money* — that is answerable by luck. The question is
whether **selection** improves outcomes relative to the opportunities it was
given, measured on the identical candidate set against baselines that see
exactly the same cases.

This is a research instrument, not a trading system. Nothing here places orders.

---

## The loop

```text
IDEA                      a sentence: "stocks that resist a selloff may rebound harder"
  ↓
OPPORTUNITY DEFINITION    frozen: generator, case budget, which judge, and the bar
  ↓
CANDIDATE GENERATION      broad and high-recall — deliberately not optimised
  ↓
CASE CONSTRUCTION         one situation, as a trader could have known it
  ↓
DECISION                  AI and every baseline, on identical cases
  ↓
══ SEAL ══════════════    decisions hashed and committed
  ↓
REVEAL                    the future — the only step that spends sample
  ↓
EVALUATION                selector lift, per-session paired, cost-aware
  ↓
LEARNING                  which kinds of reasoning preceded which outcomes
```

Run it:

```bash
.venv/bin/python -m src.cli opportunity "Stocks that resist a broad selloff may rebound harder" --hypothesis H041 -n 500
```

```bash
.venv/bin/python -m src.cli replay RPL_<id> --phase generate && .venv/bin/python -m src.cli replay RPL_<id> --phase build
```

```bash
.venv/bin/python -m src.cli replay RPL_<id> --phase decide
```

```bash
.venv/bin/python -m src.cli replay RPL_<id> --phase reveal && .venv/bin/python -m src.cli replay RPL_<id> --phase evaluate
```

`decide` and `reveal` are separate commands because they sit on opposite sides
of the seal. Read what the judge actually saw with `cases RPL_<id>`, and what it
decided with `decisions RPL_<id> --full`.

---

## The four ideas that make the answer trustworthy

**Generation is not selection.** A generator finds situations *worth examining*;
it is not the trading decision. Tuned until it looks profitable, it has stolen
the experiment — the lift is then measured against a baseline that already
contains the answer. The default generator is `liquid_universe`: every tradeable
name, every session, no opinion. A narrow generator flatters the selector by
hiding its hard cases.

**The case cannot see the future, and that is tested rather than promised.**
Every number comes from the as-of panel (indicators end at D-1) plus date D's
opening call-auction print. `tests/test_case_pit.py` builds a case against a
panel truncated at D and against the full panel and requires the bytes to be
**identical**. This project has caught four distinct non-price lookaheads and
assumes there is a fifth.

**Cases are anonymised by default.** A model may simply remember what a named
Indian stock did in a named quarter, and no amount of frame hygiene closes a
leak that lives in the weights. The symbol and the calendar never reach the
judge; prices are rebased to 100 and dates become sessions-before-the-decision.
Running the same case set with identity revealed and differencing the two is a
*measurement of memorisation* (H042), and it gates belief in everything else.

**Baselines run at the AI's own take rate.** A selector that takes 12% of what
it is shown beats one that takes everything on any pool better than average,
with no skill involved. Matching the rate leaves only *which* ones it took.

---

## Reading a result

```text
DID SELECTION HELP?   (per-session paired, HAC-corrected)
  vs the pool it was given    +82.4 bps   t=3.1
  vs what it skipped          +97.1 bps   t=3.4
  vs top_n_by_score           +31.0 bps   t=1.9
```

Every outcome is **excess** return over the equal-weighted market compounded
across the same holding window, so market exposure is the zero line rather than
an arm somebody has to remember to run. Contrasts are per-session paired
differences — controls drawn from adjacent sessions tripled every contrast in an
earlier phase of this project (H020), because winners cluster on local market
troughs.

**The bar is in basis points, not in t**, and that is a measured decision.
Against 60 coin-flip selectors on this data the session-clustered,
Hansen-Hodrick-corrected |t| still exceeded 1.96 **13.3%** of the time — the
corrections work, they simply cannot invent independent observations at a few
dozen non-overlapping blocks. A bps-denominated bar rejected the same nulls 59
times out of 60. Transaction costs are 0.40% round trip, this project's measured
conservative floor, so a lift inside that is not a result.

The report prints `independent_blocks` and says in words not to promote on a
t-statistic.

---

## What else is here

The discretionary loop sits on top of an alpha lab that predates it and is
unchanged by it.

| | |
| --- | --- |
| `src/research_data/` | **the only door to market data.** Point-in-time panel, versioned splits, corporate actions, symbol renames, the feature catalogue, forward labels |
| `src/alpha_eval/` | rank IC, quantile profiles, factor neutralisation, the canonical backtest, the bracket trade simulator, session-clustered and HAC inference |
| `src/persistence/` | the four research objects — hypothesis, exploration, signal, evidence — plus manifests and the sample-budget ledger |
| `src/runner/` | the signal path: an LLM writes `compute(df) -> Series` in an isolated worktree; label-free pre-flight, the dispatch gate, multiplicity accounting |
| `src/discretionary/` | the loop above |
| `src/research/families/` | concrete research lines (opening-window, resilience). A leaf of the architecture, never imported by the lab |

The **signal path still works and is still used** — `python -m src.cli suggest`,
`plan`, `job`, `explore`, `compare`. A replay and an exploration spend the
partition the same way and are counted by the same multiplicity code; a replay
files evidence under `signal_id = "replay:<id>"` so `burden` sees it beside
every signal ever scored.

### Discipline that is enforced rather than encouraged

- **Partitions, never date ranges.** A hand-written window is how a holdout gets
  read twice. `research_data.splits` assigns whole quarters to
  train/validation/test with purged boundaries, plus a permanent forward lane.
- **The sample budget refuses rather than warns.** 2020–2023 has been read twice
  and is spent for the opening-window and resilience families; descendants are
  blocked from scoring on those quarters. When lineage is ambiguous, it blocks.
- **A bar has to be able to fail.** A threshold of zero is a sign test wearing a
  number's clothes, and one passed that way once (H037). Bars below transaction
  costs or inside the noise are rejected before dispatch.
- **The budget is spent late.** A replay that is defined, generated, built and
  judged has read nothing about what happened next. Only `reveal` touches the
  partition, so abandoning a replay before it costs nothing.

---

## Data

Daily OHLCV comes from **NSE's own bhavcopy archive** — free, unauthenticated,
carrying turnover and delivery percentage, and point-in-time by construction:
each file lists exactly what traded that day, which is what removes survivorship
bias. Breeze is needed only for 1-second opening data.

```bash
.venv/bin/python -m src.cli sync-nse --start 2022-01-01
```

```bash
.venv/bin/python -m src.cli sync-corp-actions && .venv/bin/python -m src.cli build-metrics && .venv/bin/python -m src.cli context
```

Order matters: renames → corporate actions → indicators. Adjusting before
merging bakes a fake step into every ticker handover.

Corporate actions are **reconciled, not asserted**: NSE's stated ratios are
cross-checked against where prices actually stepped on the tape, a ratio is
applied only where both agree, and every disagreement is written out rather than
silently resolved. `PREV_CLOSE` is not usable as an adjustment source — NSE
leaves it raw on one split and pre-adjusts it on another.

`AGENTS.md` carries the full list of archive traps, Breeze gotchas, and the four
lookaheads this project has caught. Read it before touching the data layer.

---

## Setup

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env`. For the discretionary loop set `ANTHROPIC_API_KEY`
to use the concurrent API path; without one it falls back to an installed
`claude` or `codex` CLI, which is free under a subscription but serial and slow
— fine for working on a prompt, wrong for five hundred cases.

```bash
.venv/bin/python -m pytest tests/ -q
```

Leakage tests are part of the suite, not optional extras. Tests marked `network`
hit live NSE and are deselected by default.

```bash
./scripts/run_backend.sh
```

Starts the backend and web application at http://127.0.0.1:8080.

---

## Research state

`HYPOTHESES.md` is the ledger — every hypothesis proposed, tested, supported or
rejected, with a stable ID, and nothing is ever deleted. A result later found
wrong is annotated and kept, because the next person with the same idea needs to
know it was tried and why the answer did not count. `FINDINGS.md` is the
chronological evidence.

Neither is superseded by any refactor, including this one.

The previous README, describing the project as a breakout screener, is at
`archive/README_2026-08-22.md`.
