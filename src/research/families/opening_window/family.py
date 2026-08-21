"""A family of structurally distinct selection rules, stress-tested and frozen.

WHY A FAMILY AND NOT A BETTER SINGLE RULE
Phase 2.9 produced one positive result (H024: rank inside the screen by
proximity to the 52-week high plus delivery percentage, take the top few, hold
30 sessions). It was found by a deliberately overfitting sweep, and the honest
reading of a single survivor out of ~1,500 configurations is "this is the shape
of thing that might be there", not "this is there".

The cheapest way to find out whether the survivor is a fluke is to ask whether
anything *else* works, and to insist that the something-elses are structurally
different from it — a different information source, a different selection
mechanism, a different exit, a different direction. Five correlated variants of
one ranking all passing a holdout is one result with a sample size of one. Five
mechanically unrelated rules passing is five, and the family-level statement
("selection inside this screen carries information") is what is actually being
claimed.

THE FOUR THINGS THIS MODULE DOES, IN ORDER, AND THE ORDER IS THE POINT
1. Search a bounded, pre-declared grid on the exploration window. Bounded
   because the last sweep's 1,500 configurations bought a maximum, and the
   defence against a maximum is a small denominator, honestly reported.
2. Stress-test the per-axis winners across **purged** temporal blocks and
   market regimes. Purged because a 30-session hold makes adjacent trades
   overlap, so blocks that abut each other are not independent — the last 30
   sessions of every block are dropped so no trade's holding window crosses a
   boundary.
3. Freeze the survivors, with exact definitions and a **family-level pass
   criterion written down before the holdout is opened**. Deciding the bar
   afterwards is the failure this whole project is arranged to avoid.
4. Open the 2020-2023 holdout **once**.

EVERYTHING HERE IS DAILY, AND THAT IS A DELIBERATE NARROWING
H024 measured the tick entry against the opening print at 26.8% vs 26.4% CAGR:
the 1-second data contributes nothing to it. So this module drops the tick panel
entirely and builds its frame from the as-of screen plus daily context. Three
things follow, all of them good:

- the holdout window is built by the *identical* code path, so a difference
  between windows cannot be a difference in how the frame was assembled;
- the candidate pool is the screen itself rather than "the screened mornings a
  tick pull happened to cover", which removes a coverage artefact that differs
  between the two windows by construction;
- every feature is strictly from date D-1. Date D's opening print is knowable at
  09:15 (`asof.KNOWN_AT_OPEN`) and `context.py` uses it, but this module enters
  *at* that print, so using it as a feature would mean acting on a price at the
  moment it prints. The open-derived context columns (`open_base_pos_20` and
  friends, including Phase 2.8's top feature) are therefore excluded from every
  score here. That is a real cost, paid for a rule that is unambiguously
  implementable.

WHAT HAPPENED, SO NOBODY READS THIS MODULE HOPEFULLY
The holdout was opened on 2026-08-20 and the verdict is **FAIL** (H033). H024,
the incumbent, came back at -0.627% against the market at t=-1.98 — the sign of
its alpha reversed. The relative-strength member replicated the *selection*
claim and beat the same-day pool by +1.73% a trade at t=4.98, and still failed
the bar, because the holdout market compounded at 41.78% at a Sharpe of 2.25 and
no rule tested beat buy-and-hold on risk-adjusted terms. The 2020-2023 window is
spent; `holdout()` refuses to run a different family against it. Anything that
comes after this is a forward test on sessions after 2026-08-18.

WHAT IS INHERITED FROM `shotgun.py` AND MUST NOT BE RE-DERIVED
The path builder, the vectorised exit simulator, the market-excess benchmark
(alpha is r-m for a long and r+m for a short), session-clustered inference, and
the top-N-per-session selector. Those were the parts that took two attempts to
get right; they are imported, not copied.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from ....core import config
from ....research_data.pipelines import context, daily_panel as build_screen
from . import explore, shotgun
from .screener import ScreenConfig, run_screen
from .shotgun import ExitConfig

# --------------------------------------------------------------------------
# windows
# --------------------------------------------------------------------------

HOLD = 30                 # the longest holding horizon any rule may use
COST_PCT = 0.40           # round-trip, charged half at entry and half at exit
N_BLOCKS = 6              # purged temporal blocks across the exploration window

EXPLORE_START = explore.EXPLORE_START      # 2023-08-21
EXPLORE_END = explore.EXPLORE_END          # 2026-08-18
# The screen can form its first candidate on 2020-04-20, but the holdout starts
# later than that **on purpose**, and the reason is a feature definition rather
# than a result. `dist_52w_high` is `rolling(250, min_periods=60)`, and the
# bhavcopy archive begins on 2020-01-01: before the 250th session the "52-week
# high" is the high of however much history exists, which in mid-2020 means a
# window that starts *below* the pre-COVID peak it should be measuring against.
# Half the incumbent's score would therefore mean something different in the
# holdout than in the exploration window, and a rule that failed would leave no
# way to tell whether it failed or was never computed. 2020-12-29 is the 250th
# session, the first date on which every rolling window in the panel is full.
#
# The holdout's last *entry* is purged by HOLD sessions so that every holdout
# trade settles inside the holdout window: a trade entered three days before the
# exploration window opens would otherwise be scored on prices from the window
# this project has already searched.
HOLDOUT_START = pd.Timestamp("2020-12-29")


class WindowBreach(RuntimeError):
    """Raised when a frame carries rows from outside the window it claims."""


def window_guard(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
                 what: str) -> pd.DataFrame:
    """Raise on any row outside [start, end]. Never filter.

    `explore.fence` does the same job for the exploration window and is used
    directly where that is the window in question. This one exists because the
    holdout run needs the same guarantee in the other direction — a holdout
    frame that silently picked up exploration rows would report a number that is
    part in-sample, and nothing downstream would say so.
    """
    lo, hi = df["date"].min(), df["date"].max()
    if pd.isna(lo):
        raise WindowBreach(f"{what} is empty")
    if lo < start or hi > end:
        raise WindowBreach(
            f"{what} spans {lo.date()} .. {hi.date()}, outside its declared "
            f"window {start.date()} .. {end.date()}")
    return df


def holdout_window() -> tuple[pd.Timestamp, pd.Timestamp]:
    """The holdout's first and last permitted **entry** dates.

    The end is HOLD sessions before the exploration window opens, measured on
    the market's own session calendar rather than in calendar days, because a
    30-session purge is 30 sessions regardless of how many holidays fall in it.
    """
    _, mkt = context.load()
    sessions = np.sort(mkt["date"].unique())
    before = sessions[sessions < np.datetime64(EXPLORE_START)]
    if len(before) <= HOLD:
        raise RuntimeError("not enough sessions before the exploration window")
    return HOLDOUT_START, pd.Timestamp(before[-(HOLD + 1)])


# --------------------------------------------------------------------------
# the frame: one row per screened morning, entered at the opening print
# --------------------------------------------------------------------------

# Context columns that end at D-1. The `open_*` family is deliberately absent —
# see the module docstring.
TRAILING_CTX = [
    "base_range_20_pct", "days_since_high_20", "n_touches_20",
    "prev_close_vs_high_20_pct", "base_range_50_pct", "days_since_high_50",
    "n_touches_50", "prev_close_vs_high_50_pct",
    "sec_ret_20d", "sec_ret_60d",
    "rs_20d_vs_mkt", "rs_60d_vs_mkt", "rs_20d_vs_sec", "sec_rs_20d_vs_mkt",
]
MKT_COLS = [
    "mkt_ret_5d", "mkt_ret_20d", "mkt_ret_60d", "mkt_vol_20d", "mkt_trend_eff",
    "mkt_up", "mkt_vs_ema50_pct", "mkt_dd_from_60d_high_pct", "mkt_breadth_pct",
    "mkt_regime",
]


def build_frame(start: pd.Timestamp, end: pd.Timestamp,
                cfg: ScreenConfig | None = None, verbose: bool = True
                ) -> pd.DataFrame:
    """Screened mornings in [start, end], with the entry at date D's open.

    The screen runs on `screen_metrics_asof` (H015): every indicator on the row
    for date D carries date D-1's value. `open` is the one exception the as-of
    panel allows through unlagged, and it is the entry price here, so the frame
    contains no date-D information other than the price being paid.
    """
    metrics = build_screen.load(asof_open=True)
    cands, _ = run_screen(metrics, cfg or ScreenConfig())
    d = cands[(cands["date"] >= start) & (cands["date"] <= end)].copy()
    d = d.sort_values(["date", "symbol"]).reset_index(drop=True)

    ctx, mkt = context.load()
    keep = [c for c in TRAILING_CTX if c in ctx.columns]
    d = d.merge(ctx[["symbol", "date"] + keep], on=["symbol", "date"], how="left")
    d = d.merge(mkt[["date"] + [c for c in MKT_COLS if c in mkt.columns]],
                on="date", how="left")
    window_guard(d, start, end, "family frame")

    d["entry_px_adj"] = d["open"].astype(float)
    # There is no intra-window running low here: the entry *is* the opening
    # print, so the whole of date D's range is still ahead of it and neither
    # extreme is unreachable. `shotgun.build_paths` masks day-0 extremes against
    # these two columns, and setting both to the entry is what tells it that
    # nothing on day 0 has printed yet.
    d["running_low_t_adj"] = d["entry_px_adj"]
    d["running_high_t_adj"] = d["entry_px_adj"]
    d = d[d["entry_px_adj"] > 0].reset_index(drop=True)

    if verbose:
        print(f"  frame {start.date()} .. {end.date()}: {len(d):,} mornings, "
              f"{d['symbol'].nunique():,} symbols, {d['date'].nunique():,} sessions")
    return d


def explore_frame(verbose: bool = True) -> pd.DataFrame:
    d = build_frame(EXPLORE_START, EXPLORE_END, verbose=verbose)
    explore.fence(d, "family exploration frame")
    return d


# --------------------------------------------------------------------------
# gates: named, causal, and thresholded on round numbers
# --------------------------------------------------------------------------
#
# Every gate reads only the market-regime panel, which `context.py` shifts by a
# session, so a gate for date D is a statement about the market through D-1.
#
# The thresholds are round numbers rather than sample quantiles **on purpose**.
# A tercile of `mkt_vol_20d` computed over the window being traded is a
# lookahead — it uses the whole sample's volatility distribution to decide what
# counted as "high" on day 30 — and it also silently redefines itself between
# the exploration and holdout windows, so the same rule would not be the same
# rule in the two places. A fixed number is a worse fit and an honest one.

GATES = {
    "none": lambda d: np.ones(len(d), bool),
    "mkt_off_high_3": lambda d: (d["mkt_dd_from_60d_high_pct"] <= -3).to_numpy(),
    "mkt_off_high_6": lambda d: (d["mkt_dd_from_60d_high_pct"] <= -6).to_numpy(),
    "mkt_at_high": lambda d: (d["mkt_dd_from_60d_high_pct"] > -3).to_numpy(),
    "mkt_below_ema50": lambda d: (d["mkt_vs_ema50_pct"] < 0).to_numpy(),
    "mkt_above_ema50": lambda d: (d["mkt_vs_ema50_pct"] >= 0).to_numpy(),
    "mkt_high_vol": lambda d: (d["mkt_vol_20d"] >= 20).to_numpy(),
    "mkt_low_vol": lambda d: (d["mkt_vol_20d"] < 12).to_numpy(),
    "mkt_trending_up": lambda d: (d["mkt_regime"] == "trending_up").to_numpy(),
    "mkt_chop": lambda d: (d["mkt_regime"] == "chop").to_numpy(),
}


def gate_mask(frame: pd.DataFrame, name: str) -> np.ndarray:
    if name not in GATES:
        raise KeyError(f"unknown gate {name!r}; known: {sorted(GATES)}")
    g = GATES[name](frame)
    return np.asarray(g, dtype=bool) & frame["date"].notna().to_numpy()


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    """One tradeable rule, in a form the holdout run can replay unchanged.

    `features` are (column, sign) pairs: sign +1 means a high value is preferred
    on the long side, -1 means a low one is. They are averaged as **within-
    session percentile ranks**, equally weighted. Equal weights because a fitted
    weighting is one more free parameter that cannot be defended out of sample,
    and H024 found the choice of pair mattered far more than their relative
    sizing.

    An empty `features` with `long_n = 0` means the rule takes **every** gated
    morning — the shape used by the timing and exit axes, where the claim is not
    about which candidate to pick.
    """
    name: str
    axis: str
    thesis: str
    features: tuple[tuple[str, int], ...] = ()
    long_n: int = 0
    short_n: int = 0
    per_sector: int = 0       # 0 = no constraint; k = at most k names per sector
    gate: str = "none"
    exit: ExitConfig = field(default_factory=lambda: ExitConfig(
        stop_atr=None, target_pct=None, trail_ema=None, time_stop=HOLD))

    @property
    def pool_wide(self) -> bool:
        return not self.features and self.long_n == 0

    def label(self) -> str:
        f = "+".join(f"{'' if s > 0 else '-'}{c}" for c, s in self.features) or "pool"
        sel = ("all" if self.pool_wide
               else f"L{self.long_n}" + (f"/S{self.short_n}" if self.short_n else "")
               + (f" <={self.per_sector}/sector" if self.per_sector else ""))
        return f"{self.name}: {f} {sel} gate={self.gate} [{self.exit.label()}]"

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return {"name": self.name, "axis": self.axis, "thesis": self.thesis,
                "features": [[c, s] for c, s in self.features],
                "long_n": self.long_n, "short_n": self.short_n,
                "per_sector": self.per_sector,
                "gate": self.gate, "exit": asdict(self.exit)}


def from_dict(d: dict) -> Rule:
    return Rule(name=d["name"], axis=d["axis"], thesis=d["thesis"],
                features=tuple((c, int(s)) for c, s in d["features"]),
                long_n=int(d["long_n"]), short_n=int(d["short_n"]),
                per_sector=int(d.get("per_sector", 0)),
                gate=d["gate"], exit=ExitConfig(**d["exit"]))


def composite(frame: pd.DataFrame, features: tuple[tuple[str, int], ...]
              ) -> pd.Series:
    """Mean of signed within-session percentile ranks.

    Ranking **within the session** is what makes the score a selection rule
    rather than a filter: it asks "which of today's candidates", which is the
    question a discretionary trader actually faces, and it is immune to the
    slow drift in any feature's level across a six-year sample.
    """
    r = pd.DataFrame({
        f"{c}{s}": frame.groupby("date")[c].rank(pct=True) * (1 if s > 0 else -1)
        for c, s in features})
    return r.mean(axis=1)


def sides(frame: pd.DataFrame, rule: Rule) -> tuple[np.ndarray, np.ndarray]:
    """(long mask, short mask) for one rule on one frame."""
    g = gate_mask(frame, rule.gate)
    zero = np.zeros(len(frame), bool)
    if rule.pool_wide:
        return g & frame["entry_px_adj"].notna().to_numpy(), zero
    d = frame[["date"]].copy()
    d["_score"] = composite(frame, rule.features).to_numpy()
    gg = g
    if rule.per_sector:
        # A diversification constraint, applied *before* the top-N cut: keep only
        # each sector's best k names that morning, then rank what is left. Doing
        # it the other way round — cut to N and then thin by sector — silently
        # trades fewer than N names on days the score concentrates, which is a
        # different rule with a different exposure.
        s2 = frame[["date", "sector"]].copy()
        s2["_score"] = d["_score"].to_numpy()
        s2.loc[~gg, "_score"] = np.nan
        r = s2.groupby(["date", "sector"])["_score"].rank(ascending=False,
                                                          method="first")
        gg = gg & (r <= rule.per_sector).to_numpy() & s2["_score"].notna().to_numpy()
    longs = (shotgun.top_n_per_day(d, "_score", rule.long_n, ascending=False, gate=gg)
             if rule.long_n else zero)
    shorts = (shotgun.top_n_per_day(d, "_score", rule.short_n, ascending=True, gate=gg)
              if rule.short_n else zero)
    return longs, shorts


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------

_SIM_CACHE: dict = {}


def sim_cached(paths: dict, cfg: ExitConfig) -> dict:
    """`shotgun.simulate` memoised on (paths identity, exit config).

    Every rule on an axis shares one exit, and the stress tests re-evaluate the
    same rule on a dozen masks. Simulating the same 70,000 x 31 array a hundred
    times is the whole runtime of this module; the results are deterministic, so
    caching them changes nothing but the clock.
    """
    from dataclasses import astuple
    key = (id(paths), astuple(cfg))
    hit = _SIM_CACHE.get(key)
    if hit is None:
        hit = shotgun.simulate(paths, cfg)
        # Bounded, because each entry is three arrays the length of the pool and
        # the exit sweep alone would otherwise hold 144 of them. The access
        # pattern is "one exit reused many times, then the next", so evicting
        # the oldest is enough.
        if len(_SIM_CACHE) >= 8:
            _SIM_CACHE.pop(next(iter(_SIM_CACHE)))
        _SIM_CACHE[key] = hit
    return hit


def book(frame: pd.DataFrame, paths: dict, sim_long: dict, sim_short: dict,
         longs: np.ndarray, shorts: np.ndarray, cost_pct: float = COST_PCT
         ) -> tuple[np.ndarray, np.ndarray]:
    """Daily equal-weighted return of the open book, marked to each close.

    The generalisation of `shotgun.daily_book` to a two-sided book. Two things
    are kept from it because they were the difference between a result and an
    artefact: every open position is marked to its **own** daily close rather
    than having its total P&L spread evenly over its holding days (that
    smoothing alone produced a Sharpe of 8.6), and the round-trip cost is
    charged half at entry and half at exit rather than once at the end.

    A short's daily return is the negation of the underlying's. Positions on
    both sides share one equal-weight denominator, so a 5-long/5-short book is
    ten positions of a tenth each and is dollar-neutral by construction.
    """
    sessions = np.sort(frame["date"].unique())
    pos = {t: i for i, t in enumerate(sessions)}
    cl, ent = paths["close"], paths["entry"]
    dates = frame["date"].to_numpy()
    pnl = np.zeros(len(sessions))
    wts = np.zeros(len(sessions))

    for side, mask, sim in ((1, longs, sim_long), (-1, shorts, sim_short)):
        if mask is None or not mask.any():
            continue
        for k in np.where(mask & np.isfinite(sim["ret_pct"]))[0]:
            h = max(int(sim["held"][k]), 1)
            i0 = pos.get(dates[k])
            if i0 is None:
                continue
            px = np.concatenate([[ent[k]], cl[k, 1:h + 1]])
            px = px[np.isfinite(px)]
            if len(px) < 2:
                continue
            r = (px[1:] / px[:-1] - 1) * side
            r[0] -= cost_pct / 200
            r[-1] -= cost_pct / 200
            end = min(i0 + len(r), len(sessions))
            pnl[i0:end] += r[:end - i0]
            wts[i0:end] += 1
    return np.divide(pnl, np.maximum(wts, 1)), wts


def market_series(frame: pd.DataFrame, curve: pd.Series) -> np.ndarray:
    """Daily equal-weighted market return, aligned to the frame's sessions."""
    sessions = np.sort(frame["date"].unique())
    cv = curve.reindex(sessions).to_numpy()
    return np.nan_to_num(np.expm1(np.diff(np.concatenate([[cv[0]], cv]))))


def span(live: np.ndarray) -> tuple[int, int] | None:
    """First and last session the book held anything."""
    if not live.any():
        return None
    return int(np.argmax(live)), int(len(live) - 1 - np.argmax(live[::-1]))


def span_stats(r: np.ndarray, wts: np.ndarray) -> dict:
    """Portfolio statistics over the calendar span, with cash days counted.

    `shotgun.book_stats` annualises over the sessions a book *holds* something,
    which is the right convention for a rule that is always invested and the
    wrong one for a rule that goes flat: a timing rule in cash 56% of the time
    would report the return it earned while deployed as though it had earned it
    all year. Here a flat session earns 0 and still counts against the clock, so
    a rule that sits out is charged for sitting out — and for an always-invested
    rule this is identical to the old convention.

    The span runs from the first live session to the last rather than over the
    whole frame, so a rule is not charged for the warm-up before its first trade
    or for the tail after its last.
    """
    live = wts > 0
    sp = span(live)
    if sp is None or live.sum() < 20:
        return {}
    i0, i1 = sp
    rr = np.where(live, r, 0.0)[i0:i1 + 1]
    eq = np.cumprod(1 + rr)
    yrs = len(rr) / 250
    return {"total_pct": round(float((eq[-1] - 1) * 100), 1),
            "cagr_pct": round(float(eq[-1] ** (1 / yrs) - 1) * 100, 2),
            "max_dd_pct": round(float((eq / np.maximum.accumulate(eq) - 1).min() * 100), 1),
            "sharpe": round(float(rr.mean() / rr.std() * np.sqrt(250)), 2),
            "deployed_pct": round(float(live[i0:i1 + 1].mean() * 100), 1),
            "mean_open": int(wts[live].mean()), "sessions": int(len(rr))}


def market_book(frame: pd.DataFrame, curve: pd.Series,
                live: np.ndarray | None = None) -> dict:
    """Buy-and-hold, over the same calendar span as the book beside it.

    Two things this fixes at once. A book live in 200 of 664 sessions compared
    against a market measured over all 664 is two different calendars — and for
    a purged block, a calendar six times longer than the block. And the market
    leg is invested on **every** session of the span, including the ones the
    strategy sat out, because that is what buy-and-hold does and the whole point
    of comparing against it is to ask whether sitting out was worth it.
    """
    mk = market_series(frame, curve)
    if live is None:
        return span_stats(mk, np.ones(len(mk)))
    sp = span(live)
    if sp is None:
        return {}
    i0, i1 = sp
    w = np.zeros(len(mk))
    w[i0:i1 + 1] = 1
    return span_stats(mk, w)


def evaluate(frame: pd.DataFrame, paths: dict, curve: pd.Series, rule: Rule,
             cost_pct: float = COST_PCT, mask: np.ndarray | None = None) -> dict:
    """Per-trade alpha and portfolio statistics for one rule.

    Two benchmarks, because they answer different questions and a rule can pass
    one while failing the other:

    - **vs the same-day pool**: did picking these candidates beat picking at
      random from the screen that morning? This is the selection question, and
      it is unaffected by what the market did. It is identically zero for a
      pool-wide rule, which takes the whole cross-section by construction.
    - **vs the market**: did the trade beat the equal-weighted market compounded
      over its own holding window? This is the question a person with money
      faces, and per H017 it is the only one a variable-horizon rule may be
      judged on, because raw returns reward long holds in a rising market.

    `mask` restricts the evaluation to a subset of sessions (a purged block, a
    regime) *after* selection, so the rule still picks from the whole
    cross-section it would have seen on the day.
    """
    longs, shorts = sides(frame, rule)
    if mask is not None:
        longs, shorts = longs & mask, shorts & mask
    return evaluate_sides(frame, paths, curve, longs, shorts, rule.exit,
                          cost_pct, name=rule.name, label=rule.label(),
                          axis=rule.axis)


def evaluate_sides(frame: pd.DataFrame, paths: dict, curve: pd.Series,
                   longs: np.ndarray, shorts: np.ndarray, exit: ExitConfig,
                   cost_pct: float = COST_PCT, name: str = "", label: str = "",
                   axis: str = "") -> dict:
    """The scoring half of `evaluate`, on masks rather than a rule.

    Split out so the family book — the union of several rules' positions — is
    measured by exactly the same code as its members, rather than by a second
    implementation that could disagree with the first in some small way nobody
    would notice.
    """
    sim_l = sim_cached(paths, replace(exit, direction=1))
    sim_s = sim_cached(paths, replace(exit, direction=-1))
    dates = frame["date"].to_numpy()

    # The pool's own return that session under the same exit, long side.
    rl = pd.Series(sim_l["ret_pct"])
    pool_mean = rl.groupby(pd.Series(dates)).transform("mean").to_numpy()
    exc_mkt_l = shotgun.attach_excess(paths, sim_l, curve, 1)
    exc_mkt_s = shotgun.attach_excess(paths, sim_s, curve, -1)

    y_mkt = np.concatenate([exc_mkt_l[longs], exc_mkt_s[shorts]])
    y_pool = np.concatenate([(sim_l["ret_pct"] - pool_mean)[longs],
                             (sim_s["ret_pct"] + pool_mean)[shorts]])
    y_raw = np.concatenate([sim_l["ret_pct"][longs], sim_s["ret_pct"][shorts]])
    d_all = np.concatenate([dates[longs], dates[shorts]])
    if len(d_all) == 0:
        return {"rule": label, "name": name, "axis": axis, "n": 0}

    a = shotgun.score(y_mkt, d_all)
    b = shotgun.score(y_pool, d_all)
    rr, ww = book(frame, paths, sim_l, sim_s, longs, shorts, cost_pct)
    bs = span_stats(rr, ww)
    mb = market_book(frame, curve, live=(ww > 0))
    held = np.concatenate([sim_l["held"][longs], sim_s["held"][shorts]])
    return {
        "rule": label, "name": name, "axis": axis,
        "n": int(len(d_all)), "n_long": int(longs.sum()), "n_short": int(shorts.sum()),
        "sessions": int(pd.Series(d_all).nunique()),
        "alpha_mkt_pct": a["mean"], "t_mkt": a["t"],
        "alpha_pool_pct": b["mean"], "t_pool": b["t"],
        "raw_pct": round(float(np.nanmean(y_raw)), 3),
        "hit_rate_pct": round(float(np.nanmean(y_mkt > 0) * 100), 1),
        "median_hold": int(np.median(held)) if len(held) else 0,
        "book": bs, "market": mb,
        "cagr_minus_mkt": (round(bs["cagr_pct"] - mb["cagr_pct"], 2)
                           if bs and mb else None),
        "total_minus_mkt": (round(bs["total_pct"] - mb["total_pct"], 1)
                            if bs and mb else None),
        "sharpe_minus_mkt": (round(bs["sharpe"] - mb["sharpe"], 2)
                             if bs and mb else None),
    }


def family_book(frame: pd.DataFrame, paths: dict, curve: pd.Series,
                rules: list[Rule], cost_pct: float = COST_PCT,
                name: str = "FAMILY_BOOK") -> dict:
    """The union of the members' positions, equal-weighted.

    A name two rules both pick is held **once**, not twice. Doubling it would
    be a defensible portfolio too, but it makes the family book partly a bet on
    agreement between the rules, and the family claim is about the rules being
    independently right rather than about their intersection.

    Every member must share one exit for this to be a single book; the frozen
    family does, and the assertion says so rather than silently mixing horizons.
    """
    exits = {replace(r.exit, direction=1) for r in rules}
    if len(exits) != 1:
        raise ValueError("family book needs one shared exit; got "
                         f"{[e.label() for e in exits]}")
    longs = np.zeros(len(frame), bool)
    shorts = np.zeros(len(frame), bool)
    for r in rules:
        l, s = sides(frame, r)
        longs |= l
        shorts |= s
    return evaluate_sides(frame, paths, curve, longs, shorts, rules[0].exit,
                          cost_pct, name=name,
                          label=f"union of {', '.join(r.name for r in rules)}",
                          axis="family")


def _f(v, spec: str, dash: str = "     -") -> str:
    """Format a number that may be absent. An empty cell prints as a dash.

    Regime and block splits routinely produce cells a rule never traded in, and
    a rule that trades in none of them should say so rather than crash a report
    two minutes from the end of an eleven-minute run.
    """
    return format(v, spec) if isinstance(v, (int, float)) else dash


def line(res: dict) -> str:
    b, m = res.get("book") or {}, res.get("market") or {}
    return (f"  {res['name']:<26s} n={res['n']:>6,}  "
            f"mkt {_f(res.get('alpha_mkt_pct'), '+7.3f')}% (t={res.get('t_mkt')!s:>5})  "
            f"pool {_f(res.get('alpha_pool_pct'), '+7.3f')}% (t={res.get('t_pool')!s:>5})  "
            f"CAGR {_f(b.get('cagr_pct'), '+6.2f')}% "
            f"(mkt {_f(m.get('cagr_pct'), '+6.2f')}%)  "
            f"DD {_f(b.get('max_dd_pct'), '6.1f')}%  "
            f"SR {_f(b.get('sharpe'), '5.2f')}")


# --------------------------------------------------------------------------
# the search, declared before it is run
# --------------------------------------------------------------------------
#
# Each axis is a *thesis with a fixed sign*, not a bag of features to be tried
# in both directions. "The weakest candidate in the screen outperforms" is a
# hypothesis; "either the weakest or the strongest outperforms" is a coin toss
# with two chances, and searching it doubles the denominator while halving what
# a survivor means. The sign is therefore part of the axis definition and is
# not swept.
#
# The grid is small on purpose. Phase 2.9's ~1,500 configurations bought a
# maximum, and the only defence against a maximum is a small, honestly counted
# denominator and an out-of-sample test.

DEFAULT_EXIT = ExitConfig(stop_atr=None, target_pct=None, trail_ema=None,
                          time_stop=HOLD, direction=1)

AXES: dict[str, dict] = {
    "B_pullback": {
        "thesis": ("Inside the screen, the candidate that has given the most "
                   "back is the one to take. Phase 2.8's surviving contrast "
                   "(H019/H021) said winners sat further *below* their "
                   "short-term averages, and H022 rejected the trending-market "
                   "premise with the sign backwards. This is that reading of "
                   "the pool made into a selection rule."),
        "features": [("px_vs_ema_fast", -1), ("px_vs_ema_mid", -1),
                     ("ret_20d", -1), ("ret_60d", -1),
                     ("prev_close_vs_high_20_pct", -1),
                     ("prev_close_vs_high_50_pct", -1)],
        "long_n": [5, 10, 20],
    },
    "C_relative_strength": {
        "thesis": ("Rank by strength relative to the market and the sector "
                   "rather than by the stock's own price history. A different "
                   "information source from H024: `dist_52w_high` is where the "
                   "stock is against its own past, RS is where it is against "
                   "everything else."),
        "features": [("rs_20d_vs_mkt", 1), ("rs_60d_vs_mkt", 1),
                     ("rs_20d_vs_sec", 1), ("sec_rs_20d_vs_mkt", 1),
                     ("sector_breadth", 1), ("sector_uptrend_index", 1)],
        "long_n": [5, 10, 20],
    },
    "D_base_quality": {
        "thesis": ("Rank by how tight and well-formed the base is — the "
                   "uncle's stated volatility-contraction screen used as a "
                   "*ranking* instead of a gate. H024 showed the screen and a "
                   "ranking interact; this asks whether the screen's own "
                   "quantities are the thing to rank on."),
        "features": [("bb_width_pctile", -1), ("atr_ratio_pctile", -1),
                     ("base_depth_pctile", -1), ("contraction_steps", 1),
                     ("n_small_bodies_5", 1), ("base_range_20_pct", -1)],
        "long_n": [5, 10, 20],
    },
}

# The two axis winners the search produced, named so the later axes can reuse
# them without re-deriving. Recorded here rather than in a notebook because
# anything the holdout replays has to be readable from the source.
SCORE_A = (("dist_52w_high", 1), ("deliv_pct", 1))            # H024, Phase 2.9
SCORE_C = (("rs_60d_vs_mkt", 1), ("sector_breadth", 1))       # axis C winner
SCORE_D = (("base_depth_pctile", -1), ("base_range_20_pct", -1))  # axis D winner

# Axis G: neither price location nor trend — rank on what kind of *instrument*
# it is. Less liquid, more volatile, lower-priced, in the direction the classic
# premia point. If the screen's return is an illiquidity premium in disguise,
# this is the axis that finds out, and it is the one whose success would be the
# least interesting news about the strategy.
#
# `size_tier_rank` is deliberately NOT here, and the reason generalises.
# Size tiers come from NSE's *current* index constituent lists (AGENTS.md), so
# a 2021 row carries 2026's index membership — and index membership is assigned
# on market cap, which is to say on the very returns the rule is being scored
# on. Ranking on it in the holdout would mean ranking small names by whether
# they were still small five years later. The first version of this axis did
# ranked on it and won with it; `tests/test_family.py` caught it before the
# holdout was opened, which is the fourth lookahead this project has found
# inside something that did not look like a price (H015, the `median_vol_20`
# denominator, the `time_above_open_frac` dwell time).
#
# Sector labels come from the same snapshot and are used by axis C through
# `sector_breadth`. That is a weaker version of the same problem and it is kept,
# with the distinction stated rather than assumed: a sector label is a
# classification that does not move with the stock's return, while an index-tier
# rank is a ranking that does.
G_FEATURES = [("median_tv_20_cr", -1), ("atr_pct", 1), ("close_raw", -1)]

# Axis H: the same information, a different portfolio. One name per sector caps
# the concentration that every top-N rule quietly takes on — on a day when one
# sector sweeps the score, H024 buys five bets on one theme and calls it five
# positions. This axis is distinct in construction, not in what it knows, and
# the overlap matrix reports exactly how much it shares with its parent.
H_SCORES = {"A": SCORE_A, "C": SCORE_C, "D": SCORE_D}

# Axis E: no cross-sectional selection at all. The claim is about *when* to hold
# the screen, not which part of it — a timing structure, and the only axis whose
# answer could be "the screen is fine, you are trading it at the wrong times".
E_GATES = ["mkt_off_high_3", "mkt_off_high_6", "mkt_at_high", "mkt_below_ema50",
           "mkt_above_ema50", "mkt_high_vol", "mkt_low_vol", "mkt_trending_up",
           "mkt_chop"]

# Axis F: no selection either, and no timing. The claim is that the exit carries
# whatever is there — which is the largest unexplained block in the pool (27.7%
# of mornings are stopped out and then move 3%+, median MFE +7.53%).
F_EXITS: list[ExitConfig] = [
    ExitConfig(stop_atr=s, target_pct=t, trail_ema=tr,
               trail_from=("target" if t is not None else "entry"),
               time_stop=h, direction=1)
    for s in (None, 1.0, 2.0, 3.0)
    for t in (None, 15.0)
    for tr in (None, 10, 20)
    for h in (10, 20, 30)
]


def axis_grid(axis: str) -> list[Rule]:
    """Every rule an axis will try, enumerated before anything is run."""
    import itertools
    if axis in AXES:
        spec = AXES[axis]
        return [Rule(name=f"{axis}:{a[0]}+{b[0]}@{n}", axis=axis,
                     thesis=spec["thesis"], features=(a, b), long_n=n,
                     exit=DEFAULT_EXIT)
                for a, b in itertools.combinations(
                    [tuple(f) for f in spec["features"]], 2)
                for n in spec["long_n"]]
    if axis == "G_instrument_type":
        return [Rule(name=f"G_instrument_type:{a[0]}+{b[0]}@{n}",
                     axis="G_instrument_type",
                     thesis=("Rank by what kind of instrument it is — smaller, "
                             "less liquid, more volatile, lower-priced — "
                             "rather than by anything it has done."),
                     features=(a, b), long_n=n, exit=DEFAULT_EXIT)
                for a, b in itertools.combinations(G_FEATURES, 2)
                for n in (5, 10, 20)]
    if axis == "H_sector_capped":
        return [Rule(name=f"H_sector_capped:{k}@{n}", axis="H_sector_capped",
                     thesis=("An existing score with a one-name-per-sector cap: "
                             "distinct in portfolio construction rather than in "
                             "information."),
                     features=sc, long_n=n, per_sector=1, exit=DEFAULT_EXIT)
                for k, sc in H_SCORES.items() for n in (5, 10, 20)]
    if axis == "E_regime_timing":
        return [Rule(name=f"E_regime_timing:{g}", axis="E_regime_timing",
                     thesis=("Hold the whole screen, but only in a stated "
                             "market state. No cross-sectional selection."),
                     gate=g, exit=DEFAULT_EXIT) for g in E_GATES]
    if axis == "F_exit_structure":
        return [Rule(name=f"F_exit_structure:{e.label()}", axis="F_exit_structure",
                     thesis=("Hold the whole screen and let the exit do the "
                             "work. No selection, no timing."),
                     exit=e) for e in F_EXITS]
    raise KeyError(axis)


ALL_AXES = list(AXES) + ["E_regime_timing", "F_exit_structure",
                         "G_instrument_type", "H_sector_capped"]

# The objective, fixed before the search runs. Portfolio Sharpe over the
# exploration window, subject to a positive market-excess expectancy that
# clears a clustered t of 2. Sharpe rather than CAGR because the same yardstick
# has to serve a concentrated long book and a market-neutral one, and CAGR
# against a long-only index would reject a neutral book for being neutral. It is
# also the quantity the holdout bar is written in, so the search and the test
# are measured on one ruler.
MIN_T_SEARCH = 2.0


def search(frame: pd.DataFrame, paths: dict, curve: pd.Series,
           axes: list[str] | None = None, verbose: bool = True
           ) -> tuple[dict, list[dict]]:
    """Run every axis's grid; return (best per axis, all results)."""
    best, everything = {}, []
    for axis in (axes or ALL_AXES):
        grid = axis_grid(axis)
        rows = []
        for rule in grid:
            res = evaluate(frame, paths, curve, rule)
            if res.get("n", 0) < 50 or not res.get("book"):
                continue
            res["_rule"] = rule
            rows.append(res)
        everything.extend(rows)
        ok = [r for r in rows
              if r["alpha_mkt_pct"] > 0 and r["t_mkt"] >= MIN_T_SEARCH]
        pick = max(ok, key=lambda r: (r["book"]["sharpe"], r["alpha_mkt_pct"])) if ok else None
        best[axis] = pick
        if verbose:
            print(f"\n{axis}: {len(grid)} configs tried, "
                  f"{len(ok)} with positive alpha at t>={MIN_T_SEARCH}")
            if pick:
                print(line(pick))
            else:
                print("  nothing in this axis cleared the bar")
    return best, everything


# --------------------------------------------------------------------------
# distinctness: measured, not asserted
# --------------------------------------------------------------------------

def overlap_matrix(frame: pd.DataFrame, rules: list[Rule]) -> pd.DataFrame:
    """Jaccard overlap of the symbol-days each pair of rules actually trades.

    "Structurally distinct" is a claim about mechanism, and a claim about
    mechanism is worthless if the two mechanisms end up buying the same five
    stocks. Two rules that overlap 80% are one candidate with two descriptions,
    and freezing both would inflate a family-level pass into five independent
    confirmations of one thing.
    """
    sel = {r.name: sides(frame, r)[0] for r in rules}
    names = list(sel)
    m = pd.DataFrame(index=names, columns=names, dtype=float)
    for a in names:
        for b in names:
            x, y = sel[a], sel[b]
            u = (x | y).sum()
            m.loc[a, b] = round(float((x & y).sum() / u * 100), 1) if u else np.nan
    return m


def book_correlation(frame: pd.DataFrame, paths: dict, rules: list[Rule],
                     cost_pct: float = COST_PCT) -> pd.DataFrame:
    """Correlation of the daily book returns, on sessions where both are live."""
    series = {}
    for r in rules:
        longs, shorts = sides(frame, r)
        rr, ww = book(frame, paths, sim_cached(paths, replace(r.exit, direction=1)),
                      sim_cached(paths, replace(r.exit, direction=-1)),
                      longs, shorts, cost_pct)
        series[r.name] = np.where(ww > 0, rr, np.nan)
    return pd.DataFrame(series).corr().round(2)


def picks_profile(frame: pd.DataFrame, rule: Rule) -> dict:
    """What the rule actually buys, in units a person can sanity-check.

    Liquidity is here because a ranking that selects the least-traded names in
    the screen is not obviously tradeable at the 0.40% round-trip cost the book
    charges, and no t-statistic will say so.
    """
    longs, _ = sides(frame, rule)
    d = frame[longs]
    if d.empty:
        return {}
    return {
        "median_turnover_cr": round(float(d["median_tv_20_cr"].median()), 2),
        "p10_turnover_cr": round(float(d["median_tv_20_cr"].quantile(0.10)), 2),
        "median_price": round(float(d["close_raw"].median()), 1),
        "median_atr_pct": round(float(d["atr_pct"].median()), 2),
        "outside_top_500_pct": round(float((d["size_tier_rank"] > 500).mean() * 100), 1),
        "median_dist_52w_high": round(float(d["dist_52w_high"].median()), 1),
        "distinct_symbols": int(d["symbol"].nunique()),
        "top_sector_share_pct": round(float(d["sector"].value_counts(normalize=True).iloc[0] * 100), 1),
    }


# --------------------------------------------------------------------------
# purged temporal blocks and regime splits
# --------------------------------------------------------------------------

def purged_blocks(frame: pd.DataFrame, n_blocks: int = N_BLOCKS,
                  purge: int = HOLD) -> np.ndarray:
    """Block id per row; -1 for rows dropped by the purge.

    A trade held 30 sessions overlaps the next 30 sessions of trades, so two
    blocks that abut each other share information and "six independent periods"
    would be a fiction. The last `purge` sessions of every block are therefore
    dropped, which costs about a quarter of the sample and buys blocks whose
    holding windows do not intersect. Purging the *end* of each block rather
    than the start is what makes the containment exact: an entry in the final
    kept session settles on the last session of its own block.
    """
    sessions = np.sort(frame["date"].unique())
    edges = np.linspace(0, len(sessions), n_blocks + 1).astype(int)
    lut = {}
    for b in range(n_blocks):
        keep = sessions[edges[b]:max(edges[b], edges[b + 1] - purge)]
        for s in keep:
            lut[s] = b
    return frame["date"].map(lambda s: lut.get(s, -1)).to_numpy()


REGIME_SPLITS = ["mkt_above_ema50", "mkt_below_ema50", "mkt_high_vol",
                 "mkt_low_vol", "mkt_trending_up", "mkt_chop"]


def stress(frame: pd.DataFrame, paths: dict, curve: pd.Series, rule: Rule,
           n_blocks: int = N_BLOCKS, verbose: bool = True) -> dict:
    """Per-block, leave-one-block-out and per-regime alpha for one rule."""
    blocks = purged_blocks(frame, n_blocks)
    sessions = np.sort(frame["date"].unique())
    out = {"n_blocks": n_blocks, "purge_sessions": HOLD, "blocks": [], "loo": [],
           "regimes": {}}
    for b in range(n_blocks):
        m = blocks == b
        r = evaluate(frame, paths, curve, rule, mask=m)
        dts = frame.loc[m, "date"]
        out["blocks"].append({
            "block": b, "from": str(dts.min().date()), "to": str(dts.max().date()),
            "n": r.get("n", 0), "alpha_mkt_pct": r.get("alpha_mkt_pct"),
            "t_mkt": r.get("t_mkt"), "alpha_pool_pct": r.get("alpha_pool_pct"),
            "total_minus_mkt": r.get("total_minus_mkt"),
            "sharpe_minus_mkt": r.get("sharpe_minus_mkt")})
        r2 = evaluate(frame, paths, curve, rule, mask=(blocks >= 0) & (blocks != b))
        out["loo"].append({"dropped": b, "alpha_mkt_pct": r2.get("alpha_mkt_pct"),
                           "t_mkt": r2.get("t_mkt")})
    for g in REGIME_SPLITS:
        m = gate_mask(frame, g)
        r = evaluate(frame, paths, curve, rule, mask=m)
        out["regimes"][g] = {"n": r.get("n", 0), "sessions": r.get("sessions", 0),
                             "alpha_mkt_pct": r.get("alpha_mkt_pct"),
                             "t_mkt": r.get("t_mkt")}
    pos = [b["alpha_mkt_pct"] for b in out["blocks"] if b["alpha_mkt_pct"] is not None]
    out["blocks_positive"] = int(sum(a > 0 for a in pos))
    out["loo_all_positive"] = all((l["alpha_mkt_pct"] or 0) > 0 for l in out["loo"])
    # A half the rule never trades in is not evidence against it. A gated rule
    # that only holds when the market is under its 50-EMA has an empty cell
    # above it by construction, and scoring that as a failure would reject the
    # timing axis for being a timing axis rather than for being wrong.
    halves = [out["regimes"][k] for k in ("mkt_above_ema50", "mkt_below_ema50")]
    traded = [h for h in halves if h["n"] > 0]
    out["market_halves_traded"] = len(traded)
    out["both_market_halves_positive"] = bool(traded) and all(
        (h["alpha_mkt_pct"] or 0) > 0 for h in traded)
    if verbose:
        print(f"\n  {rule.name}")
        for b in out["blocks"]:
            print(f"    block {b['block']} {b['from']}..{b['to']} n={b['n']:>5,} "
                  f"alpha {_f(b['alpha_mkt_pct'], '+7.3f')}% (t={b['t_mkt']!s:>5})  "
                  f"total-mkt {_f(b['total_minus_mkt'], '+6.1f')}pp  "
                  f"SR-mkt {_f(b['sharpe_minus_mkt'], '+5.2f')}")
        print(f"    blocks positive {out['blocks_positive']}/{n_blocks}   "
              f"LOO all positive {out['loo_all_positive']}   "
              f"both market halves {out['both_market_halves_positive']}")
        for g, v in out["regimes"].items():
            print(f"      {g:<18s} n={v['n']:>6,} "
                  f"alpha {_f(v.get('alpha_mkt_pct'), '+7.3f')}% "
                  f"(t={v.get('t_mkt')})")
    return out


# The stress bar, fixed before any block was looked at. A rule that clears three
# of these four and fails one is *not* frozen: the point of a stress test that
# can only ever be run in sample is that it has to be allowed to kill things.
STRESS_MIN_BLOCKS_POSITIVE = 4      # of N_BLOCKS
STRESS_REQUIRE_LOO = True           # positive with any one block removed
STRESS_REQUIRE_BOTH_HALVES = True   # market above and below its own 50-EMA
STRESS_MIN_T = 2.0                  # clustered, whole exploration window


def stress_verdict(res: dict, st: dict) -> tuple[bool, list[str]]:
    fails = []
    if st["blocks_positive"] < STRESS_MIN_BLOCKS_POSITIVE:
        fails.append(f"only {st['blocks_positive']}/{st['n_blocks']} blocks positive")
    if STRESS_REQUIRE_LOO and not st["loo_all_positive"]:
        fails.append("a single block carries it (leave-one-out turns negative)")
    if STRESS_REQUIRE_BOTH_HALVES and not st["both_market_halves_positive"]:
        fails.append("negative in one half of the market's own trend")
    if (res.get("t_mkt") or 0) < STRESS_MIN_T:
        fails.append(f"clustered t {res['t_mkt']} below {STRESS_MIN_T}")
    return (not fails), fails


def cost_sensitivity(frame: pd.DataFrame, paths: dict, rule: Rule,
                     costs: tuple[float, ...] = (0.20, 0.40, 1.00, 2.00)) -> dict:
    """Portfolio CAGR and Sharpe at several round-trip costs.

    0.40% is the house assumption everywhere else in this project. It is a
    reasonable number for a liquid NSE name and an optimistic one for the
    bottom of the screen by turnover, so a rule that only works at 0.40% is
    worth knowing about *before* it is frozen rather than after it is traded.
    """
    longs, shorts = sides(frame, rule)
    sl = sim_cached(paths, replace(rule.exit, direction=1))
    ss = sim_cached(paths, replace(rule.exit, direction=-1))
    out = {}
    for c in costs:
        rr, ww = book(frame, paths, sl, ss, longs, shorts, c)
        bs = span_stats(rr, ww)
        out[f"{c:.2f}"] = {"cagr_pct": bs.get("cagr_pct"), "sharpe": bs.get("sharpe")}
    return out


def permutation_null(frame: pd.DataFrame, paths: dict, rule: Rule,
                     n_perm: int = 200, seed: int = 0) -> dict:
    """Within-session shuffle of the score, holding everything else fixed.

    The null is "this morning's candidates were ranked at random", which is the
    only null that isolates the ranking: shuffling across dates would also
    destroy the session composition and could be rejected by anything at all
    (H016). Pool-wide rules have no ranking to shuffle and return an empty dict
    rather than a meaningless number.
    """
    if rule.pool_wide:
        return {}
    sl = sim_cached(paths, replace(rule.exit, direction=1))
    dates = frame["date"].to_numpy()
    rl = pd.Series(sl["ret_pct"])
    pool_mean = rl.groupby(pd.Series(dates)).transform("mean").to_numpy()
    y = sl["ret_pct"] - pool_mean

    g = gate_mask(frame, rule.gate)
    base = composite(frame, rule.features).to_numpy()
    idx = frame.groupby("date").indices
    rng = np.random.default_rng(seed)
    f2 = frame[["date"]].copy()
    means = []
    for _ in range(n_perm):
        sc = base.copy()
        for ix in idx.values():
            if len(ix) > 1:
                sc[ix] = sc[rng.permutation(ix)]
        f2["_s"] = sc
        m = shotgun.top_n_per_day(f2, "_s", rule.long_n, ascending=False, gate=g)
        means.append(float(np.nanmean(y[m])) if m.any() else np.nan)
    means = np.array(means, dtype=float)
    obs = float(np.nanmean(y[sides(frame, rule)[0]]))
    return {"n_perm": n_perm, "observed": round(obs, 3),
            "null_p95": round(float(np.nanpercentile(means, 95)), 3),
            "null_max": round(float(np.nanmax(means)), 3),
            "beats_pct": round(float((obs > means).mean() * 100), 1)}


# --------------------------------------------------------------------------
# freezing, and the pass criterion — written before the holdout is opened
# --------------------------------------------------------------------------

FROZEN_PATH = config.METADATA_DIR / "family_frozen.json"
REPORT_PATH = config.METADATA_DIR / "family.json"
HOLDOUT_PATH = config.METADATA_DIR / "family_holdout.json"

# THE BAR. Every number in it is fixed here, in the source, before the 2020-2023
# window is read. Deciding a bar after seeing a result is not a test, and this
# project has exactly one clean out-of-sample window to spend.
#
# Per member, all three must hold on the holdout:
#   1. per-trade excess over the market (alpha is r-m long, r+m short) is
#      positive with a session-clustered t of at least 2.0;
#   2. the portfolio's Sharpe at 0.40% round-trip cost exceeds the
#      equal-weighted market's over the same calendar span;
#   3. the alpha is at least a third of what it was on the exploration window.
#
# (2) is Sharpe and not CAGR, which is a deliberate change from the bar sketched
# in PLAN.md, made before the run and for a stated reason: the family has to be
# judged on one ruler, and CAGR against a long-only index is not a ruler a
# market-neutral or partially-invested book can be measured with. (3) exists
# because a large sample can make a 0.05% edge significant, and a rule that
# retains a twentieth of its effect has not replicated in any useful sense.
#
# Family verdict:
#   PASS    - the union book clears (1) and (2), and at least
#             `min_members_passing` members pass.
#   PARTIAL - the union book clears (1) and (2) but fewer than 2 members do.
#   FAIL    - anything else. On a FAIL the selection family is dropped. The
#             holdout is spent; no re-tuned variant may be tested on it.
PASS_CRITERION = {
    "member": {"alpha_gt": 0.0, "min_clustered_t": 2.0,
               "sharpe_above_market": True, "min_alpha_retention": 1 / 3},
    "family": {"union_book_must_pass": True, "min_members_passing": 2},
    "cost_pct_round_trip": COST_PCT,
    "prose": ("Per member: positive market-excess expectancy at clustered "
              "t>=2, portfolio Sharpe above the market's over the same "
              "calendar span at 0.40% round-trip cost, and at least a third of "
              "the exploration-window alpha retained. Family PASS requires the "
              "union book to clear the first two and at least "
              "`min_members_passing` members to pass; PARTIAL if the union "
              "book clears them alone; FAIL otherwise, and a FAIL drops the "
              "family without re-tuning."),
}


def rules_hash(rules: list[Rule]) -> str:
    """A fingerprint of the frozen definitions, so a silent edit cannot hide."""
    import hashlib
    blob = json.dumps([r.to_dict() for r in rules], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def freeze(payload: dict, path=FROZEN_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n-> froze {len(payload['members'])} family members and "
          f"{len(payload['information_only'])} information-only rules to "
          f"{path.relative_to(config.PROJECT_ROOT)}")


def load_frozen(path=FROZEN_PATH) -> dict:
    if not path.exists():
        raise RuntimeError(
            f"{path} does not exist. The holdout may only be opened against a "
            f"frozen family: run `python -m src.cli family` first.")
    return json.loads(path.read_text())


def member_verdict(hold: dict, expl_alpha: float, crit: dict) -> tuple[bool, list[str]]:
    c = crit["member"]
    fails = []
    if not (hold["alpha_mkt_pct"] > c["alpha_gt"]):
        fails.append(f"alpha {hold['alpha_mkt_pct']:+.3f}% not positive")
    if hold["t_mkt"] < c["min_clustered_t"]:
        fails.append(f"clustered t {hold['t_mkt']} below {c['min_clustered_t']}")
    if c["sharpe_above_market"] and (hold.get("sharpe_minus_mkt") or -1) <= 0:
        fails.append(f"Sharpe {hold['book'].get('sharpe')} not above the market's "
                     f"{hold['market'].get('sharpe')}")
    need = c["min_alpha_retention"] * expl_alpha
    if hold["alpha_mkt_pct"] < need:
        fails.append(f"alpha {hold['alpha_mkt_pct']:+.3f}% below the "
                     f"{c['min_alpha_retention']:.2f} retention floor {need:+.3f}%")
    return (not fails), fails


# The in-sample gate a rule must clear before it is worth spending holdout on:
# the same bar the holdout will apply, minus the retention clause (which has
# nothing to compare against yet). A rule that cannot beat the market on the
# window it was fitted to will not start doing so on unseen data, and carrying
# it into the family would only dilute the family-level criterion.
def freeze_gate(res: dict) -> tuple[bool, list[str]]:
    fails = []
    if not (res.get("alpha_mkt_pct", -1) > 0):
        fails.append("alpha not positive")
    if res.get("t_mkt", 0) < PASS_CRITERION["member"]["min_clustered_t"]:
        fails.append(f"clustered t {res.get('t_mkt')} below 2.0")
    if (res.get("sharpe_minus_mkt") or -1) <= 0:
        fails.append(f"Sharpe {res['book'].get('sharpe')} not above the market's "
                     f"{res['market'].get('sharpe')}")
    return (not fails), fails


# The incumbent, re-expressed on the daily entry. H024 was found at a t=180s
# tick entry; it measured the opening-print entry at 26.4% CAGR against 26.8%,
# and this module drops the tick panel for the reasons in the module docstring.
# The definition is otherwise unchanged: same two features, same top 5, same
# 30-session hold, no stop.
INCUMBENT = Rule(
    name="A_momentum_location", axis="A_incumbent",
    thesis=("H024 (Phase 2.9): rank the screened candidates by proximity to "
            "the 52-week high and by delivery percentage, take the top five, "
            "hold 30 sessions with no stop."),
    features=SCORE_A, long_n=5, exit=DEFAULT_EXIT)


def report(n_perm: int = 200, axes: list[str] | None = None,
           do_freeze: bool = True, verbose: bool = True) -> dict:
    """Search, stress-test, and freeze — everything before the holdout.

    The order is the argument. Search first and count the configurations
    honestly; keep only the per-axis winner so the family cannot be five
    neighbours of one rule; kill anything the purged blocks say is carried by a
    single period; and only then write the definitions down, with the bar
    attached to them.
    """
    frame = explore_frame(verbose=verbose)
    paths = shotgun.build_paths(frame, horizon=HOLD, verbose=verbose)
    curve = shotgun.market_curve()

    if verbose:
        print(f"\n{'='*74}\nSEARCH — exploration window only, "
              f"{sum(len(axis_grid(a)) for a in (axes or ALL_AXES))} configurations "
              f"over {len(axes or ALL_AXES)} axes\n{'='*74}")
    best, everything = search(frame, paths, curve, axes=axes, verbose=verbose)

    incumbent_res = evaluate(frame, paths, curve, INCUMBENT)
    incumbent_res["_rule"] = INCUMBENT
    picked = [incumbent_res] + [r for r in best.values() if r]

    if verbose:
        print(f"\n{'='*74}\nSTRESS — {N_BLOCKS} purged blocks "
              f"({HOLD}-session purge) and six regime splits\n{'='*74}")
    members, info_only = [], []
    detail = {}
    for res in picked:
        rule = res["_rule"]
        gate_ok, gate_fails = freeze_gate(res)
        st = stress(frame, paths, curve, rule, verbose=verbose)
        stress_ok, stress_fails = stress_verdict(res, st)
        pn = permutation_null(frame, paths, rule, n_perm=n_perm)
        entry = {"rule": rule.to_dict(), "exploration": _clean(res),
                 "stress": st, "permutation": pn,
                 "picks": picks_profile(frame, rule),
                 "cost_sensitivity": cost_sensitivity(frame, paths, rule),
                 "in_sample_gate": {"passed": gate_ok, "failures": gate_fails},
                 "stress_test": {"passed": stress_ok, "failures": stress_fails}}
        detail[rule.name] = entry
        (members if (gate_ok and stress_ok) else info_only).append(rule)
        if verbose:
            print(f"    -> {'FAMILY MEMBER' if (gate_ok and stress_ok) else 'information only'}"
                  f"  ({', '.join(gate_fails + stress_fails) or 'clears both bars'})")

    # Every axis that produced nothing still gets its best config carried to the
    # holdout as an information-only replay. A search that only ever looks at
    # its winners cannot tell whether the in-sample screen predicts anything;
    # these rules are the control group for that question, and they are barred
    # by construction from improving the verdict.
    for axis in (axes or ALL_AXES):
        if best.get(axis) is None:
            rows = [r for r in everything if r["axis"] == axis and r.get("book")]
            if rows:
                r = max(rows, key=lambda x: (x["book"]["sharpe"], x["alpha_mkt_pct"]))
                info_only.append(r["_rule"])
                detail[r["_rule"].name] = {
                    "rule": r["_rule"].to_dict(), "exploration": _clean(r),
                    "note": "best of an axis where nothing cleared the search bar"}

    fam = family_book(frame, paths, curve, members, name="FAMILY_BOOK")
    if verbose:
        print(f"\n{'='*74}\nFAMILY — union of {len(members)} members"
              f"\n{'='*74}")
        print(line(fam))
        print("\n  selection overlap (% Jaccard):")
        print(overlap_matrix(frame, members).to_string().replace("\n", "\n    "))
        print("\n  daily book correlation:")
        print(book_correlation(frame, paths, members).to_string().replace("\n", "\n    "))

    payload = {
        "STATUS": ("EXPLORATORY / DATA-GENERATED. Every number here comes from "
                   "the window it was searched on. The 2020-2023 holdout is "
                   "untouched at the time of writing."),
        "exploration_window": [str(EXPLORE_START.date()), str(EXPLORE_END.date())],
        "holdout_window": [str(d.date()) for d in holdout_window()],
        "entry": "date D's adjusted opening print; features strictly from D-1",
        "screen": ScreenConfig().to_dict(),
        "cost_pct_round_trip": COST_PCT, "hold_sessions": HOLD,
        "search": {"axes": {a: len(axis_grid(a)) for a in (axes or ALL_AXES)},
                   "configurations": sum(len(axis_grid(a)) for a in (axes or ALL_AXES)),
                   "objective": ("portfolio Sharpe subject to positive market "
                                 "alpha at clustered t>=2"),
                   "kept_per_axis": 1},
        "members": [r.to_dict() for r in members],
        "information_only": [r.to_dict() for r in info_only],
        "information_only_note": ("Replayed on the holdout for what they say "
                                  "about the in-sample screen. They cannot "
                                  "improve the family verdict."),
        "family_book": _clean(fam),
        "detail": detail,
        "pass_criterion": PASS_CRITERION,
        "rules_hash": rules_hash(members),
    }
    if do_freeze:
        freeze(payload)
    return payload


def _clean(res: dict) -> dict:
    return {k: v for k, v in res.items() if not k.startswith("_")}


# --------------------------------------------------------------------------
# the holdout, opened once
# --------------------------------------------------------------------------

def holdout(verbose: bool = True, path=HOLDOUT_PATH) -> dict:
    """Replay the frozen family on 2020-2023. This is the confirmatory test.

    Three guards, because everything this project has built rests on this run
    being clean:

    - the frozen definitions are re-hashed and compared against the hash stored
      when they were frozen, so an edit between freezing and running is loud;
    - the frame is guarded to the holdout window, and separately asserted to end
      before the exploration window opens — the last entry is purged by `HOLD`
      sessions so no holdout trade is settled on prices from the searched years;
    - if a result already exists it must carry the same hash. Re-running the
      identical definitions is deterministic and harmless; re-running *changed*
      ones is the failure mode this whole arrangement exists to prevent, and it
      raises.
    """
    frozen = load_frozen()
    members = [from_dict(d) for d in frozen["members"]]
    info = [from_dict(d) for d in frozen["information_only"]]
    h = rules_hash(members)
    if h != frozen.get("rules_hash"):
        raise RuntimeError(
            f"the frozen file's rules no longer hash to what was recorded "
            f"({h} vs {frozen.get('rules_hash')}). Something was edited after "
            f"freezing; the holdout must not be run against it.")
    if path.exists():
        prev = json.loads(path.read_text())
        if prev.get("rules_hash") != h:
            raise RuntimeError(
                f"{path.name} already holds a holdout result for a *different* "
                f"family ({prev.get('rules_hash')}). The 2020-2023 window has "
                f"been spent. Testing a re-tuned family on it would turn the "
                f"only confirmatory dataset in this project into another "
                f"exploratory one.")
        if verbose:
            print("  (a result for these exact definitions already exists; "
                  "the replay is deterministic)")

    start, end = holdout_window()
    if verbose:
        print(f"\n{'='*74}\nHOLDOUT — {start.date()} .. {end.date()}, opened once"
              f"\n{'='*74}")
    frame = build_frame(start, end, verbose=verbose)
    window_guard(frame, start, end, "holdout frame")
    if frame["date"].max() >= EXPLORE_START:
        raise WindowBreach("holdout frame reaches into the exploration window")
    paths = shotgun.build_paths(frame, horizon=HOLD, verbose=verbose)
    curve = shotgun.market_curve()

    expl = {k: v["exploration"] for k, v in frozen["detail"].items()}
    out = {"holdout_window": [str(start.date()), str(end.date())],
           "rules_hash": h, "pass_criterion": frozen["pass_criterion"],
           "market": market_book(frame, curve), "members": {},
           "information_only": {}}

    n_pass = 0
    if verbose:
        print("\n  family members:")
    for r in members:
        res = evaluate(frame, paths, curve, r)
        a_expl = expl.get(r.name, {}).get("alpha_mkt_pct", 0.0)
        ok, fails = member_verdict(res, a_expl, frozen["pass_criterion"])
        n_pass += bool(ok)
        out["members"][r.name] = {
            "holdout": _clean(res), "exploration_alpha_pct": a_expl,
            "alpha_retention": (round(res["alpha_mkt_pct"] / a_expl, 2)
                                if a_expl else None),
            "picks": picks_profile(frame, r), "passed": ok, "failures": fails}
        if verbose:
            print(line(res))
            print(f"    -> {'PASS' if ok else 'FAIL'}"
                  f"{'' if ok else ': ' + '; '.join(fails)}")

    fam = family_book(frame, paths, curve, members)
    fam_ok = (fam["alpha_mkt_pct"] > 0
              and fam["t_mkt"] >= frozen["pass_criterion"]["member"]["min_clustered_t"]
              and (fam.get("sharpe_minus_mkt") or -1) > 0)
    out["family_book"] = {"holdout": _clean(fam),
                          "exploration": frozen.get("family_book"),
                          "passed": fam_ok}

    if verbose:
        print("\n  information-only replays (cannot change the verdict):")
    for r in info:
        res = evaluate(frame, paths, curve, r)
        out["information_only"][r.name] = _clean(res)
        if verbose:
            print(line(res))

    need = frozen["pass_criterion"]["family"]["min_members_passing"]
    verdict = ("PASS" if (fam_ok and n_pass >= need)
               else "PARTIAL" if fam_ok else "FAIL")
    out["members_passing"] = n_pass
    out["verdict"] = verdict
    out["verdict_note"] = {
        "PASS": ("The family replicates out of sample. Selection inside the "
                 "screen carries information that was not fitted to this data."),
        "PARTIAL": ("The union book replicates but fewer than the required "
                    "number of individual rules do. The family effect is "
                    "supported; no single rule is established."),
        "FAIL": ("The family does not replicate. Per the criterion frozen "
                 "before this run, it is dropped rather than re-tuned, and the "
                 "2020-2023 window is spent."),
    }[verdict]

    if verbose:
        print(f"\n{'='*74}")
        print(f"  family book: {line(fam).strip()}")
        print(f"  members passing: {n_pass}/{len(members)} (need {need})")
        print(f"  VERDICT: {verdict} — {out['verdict_note']}")
        print(f"{'='*74}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n-> wrote {path.relative_to(config.PROJECT_ROOT)}")
    return out
