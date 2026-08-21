"""Bracketed trade simulation on daily bars — entry, stop, target, trail.

Extracted from the opening-window family's `payoff.py`, which built it to
answer a question that is not specific to that family at all: **a fixed-horizon
label is not a strategy's payoff**, and the two can disagree in *sign* on the
same trades. If most setups drift to -3% by D+5 but a stop takes them out at
-1%, while a minority reach +18% and give it back, the fixed-horizon label says
the strategy loses while the traded rule makes money.

That matters more under the discretionary mission than it did before. A
discretionary decision may name its own entry, stop and horizon; scoring it only
at D+5 would discard exactly the part the decider was asked to supply.

WHY THIS PRODUCES A BRACKET RATHER THAN A NUMBER
A daily bar records a high and a low and not their order. On a session that
touched both the stop and the target the outcome is genuinely undetermined by
the data, so the simulation runs twice — resolving every ambiguity first in the
trade's favour, then against it — and reports both. The truth lies between, and
the width is the part the data cannot settle.

THE ENTRY DAY, WHICH IS EXACT IN ALL THREE CASES
The entry day's daily high and low span moments both before and after the
position exists, and pairing the whole bar with a mid-session entry is the H004
error. But which part is reachable is not a matter of assumption — it follows
from when the entry happened:

- ``entry_timing="open"`` — filled at date D's opening print, so the entire
  session after it is post-entry. Both extremes are reachable. Exact.
- ``entry_timing="close"`` — filled at date D's close, so none of date D is
  post-entry. Neither extreme is reachable. Exact.
- ``entry_timing="intraday_window"`` — filled at some ``t`` inside the session,
  which needs ``running_low_t`` / ``running_high_t``: the extremes from the
  session open through ``t``. Then ``low_D < running_low_t`` proves the day's
  low came *after* entry and is reachable, while ``low_D == running_low_t``
  proves price never traded below ``running_low_t`` after entry — and since
  ``stop < running_low_t`` by construction, the stop certainly was not hit.
  Exact, and the reason the family carried the 1-second panel.

Dropping the entry day entirely — the obvious safe-looking move — is *not*
neutral: a stop 2% below entry is very often hit the same afternoon, so
discarding date D biases the payoff upward.

GAP-THROUGH, WITHOUT WHICH THE STOP IS FICTION
A stop is not a fill. A session opening below the stop fills at the open, and
that is where much of the loss actually lives. Every level — initial stop,
target, breakeven stop — is checked against the session's open first and filled
there when the open has already passed it.

WHAT THIS IS NOT
Not a backtest. No position sizing, no capital constraint, no sequencing across
overlapping trades, no costs, no slippage beyond the gap logic. Use
`alpha_eval.backtest.canonical_backtest` for the portfolio question. This
answers one thing: on these trades, what did the traded rule actually pay?
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Exit reasons, in the order the simulator can produce them.
STOP = "stop"
STOP_GAP = "stop_gap"
TARGET_THEN_TRAIL = "target_then_trail"
TARGET_THEN_BREAKEVEN = "target_then_breakeven"
TRAIL = "trail"
TIMEOUT = "timeout"
OPEN_AT_END = "still_open"

ENTRY_TIMINGS = ("open", "close", "intraday_window")


@dataclass(frozen=True)
class BracketRule:
    """A scale-out-and-trail exit rule, made executable.

    `max_sessions` is the one number with no external source. It exists because
    a trailed position must terminate for the statistic to be defined, and
    trades still open at the cap are reported separately rather than being
    marked-to-market as though they had closed.
    """
    target_pct: float = 15.0
    scale_out_frac: float = 0.5
    trail_ema: int = 10
    max_sessions: int = 60
    # A close below the trail is a signal, not a fill: the earliest a reaction
    # can execute is the next session's open. Exiting at the signal close would
    # quietly hand the strategy a price it could not have got.
    trail_exec_next_open: bool = True


def daily_market_return(bars: pd.DataFrame, min_symbols: int = 50) -> pd.Series:
    """Equal-weighted market return per session, for variable-horizon benchmarking.

    Fixed-horizon forward returns are the wrong shape here: these trades run for
    however long the rule keeps them, so the benchmark has to be compounded over
    each trade's own holding window.
    """
    b = bars.sort_values(["symbol", "date"])
    prev = b.groupby("symbol", sort=False)["close"].shift(1)
    r = (b["close"] / prev - 1.0)
    r = r.where(r.abs() < 0.6)          # guard against bad prints, as elsewhere
    g = pd.DataFrame({"date": b["date"], "r": r}).groupby("date")["r"]
    out = g.mean()
    return out.where(g.count() >= min_symbols)


def _symbol_arrays(bars: pd.DataFrame, rule: BracketRule) -> dict:
    """Per-symbol date-aligned OHLC and trail EMA, as numpy for the walk-forward."""
    b = bars.sort_values(["symbol", "date"]).reset_index(drop=True)
    b["ema_trail"] = (b.groupby("symbol", sort=False)["close"]
                      .transform(lambda s: s.ewm(span=rule.trail_ema, adjust=False).mean()))
    out = {}
    for sym, g in b.groupby("symbol", sort=False):
        out[sym] = {
            "date": g["date"].to_numpy(),
            "open": g["open"].to_numpy(dtype=float),
            "high": g["high"].to_numpy(dtype=float),
            "low": g["low"].to_numpy(dtype=float),
            "close": g["close"].to_numpy(dtype=float),
            "ema": g["ema_trail"].to_numpy(dtype=float),
        }
    return out


def _entry_day_extremes(a: dict, i0: int, row, entry_timing: str
                        ) -> tuple[float, float]:
    """Which of the entry day's extremes the position could actually have met.

    Returns ``(d0_low, d0_high)`` where ``+inf`` / ``-inf`` mean "unreachable —
    the extreme was set before the position existed". See the module docstring:
    every branch here is a certainty, not an assumption.
    """
    if entry_timing == "open":
        # Filled on the opening print; the rest of the session is post-entry.
        return a["low"][i0], a["high"][i0]
    if entry_timing == "close":
        # Filled on the close; nothing of date D is reachable.
        return np.inf, -np.inf
    # intraday_window: resolved against the extremes through the entry moment.
    run_lo = getattr(row, "running_low_t", np.nan)
    run_hi = getattr(row, "running_high_t", np.nan)
    if not (np.isfinite(run_lo) and np.isfinite(run_hi)):
        raise ValueError(
            "entry_timing='intraday_window' needs finite running_low_t and "
            "running_high_t on every trade — they are what make the entry day "
            "exact. Use entry_timing='open' or 'close' when there is no "
            "intraday window.")
    d0_low = a["low"][i0] if a["low"][i0] < run_lo - 1e-9 else np.inf
    d0_high = a["high"][i0] if a["high"][i0] > run_hi + 1e-9 else -np.inf
    return d0_low, d0_high


def _simulate_one(a: dict, i0: int, entry: float, stop: float,
                  d0_low: float, d0_high: float,
                  rule: BracketRule, optimistic: bool) -> tuple:
    """Walk one trade forward. `i0` is the entry day's index in the symbol's array.

    `d0_low` / `d0_high` are the **post-entry** extremes of the entry day, already
    resolved by `_entry_day_extremes`: +inf / -inf mean "the extreme happened
    before entry and is therefore unreachable".

    `optimistic` resolves the one thing daily bars cannot say — whether the high
    or the low came first on a session that touched both.
    """
    target = entry * (1 + rule.target_pct / 100.0)
    n = len(a["close"])
    filled = 0.0            # fraction of the position already exited
    proceeds = 0.0          # sum of fraction * exit price
    half = rule.scale_out_frac

    scaled_out = False      # target has filled; remainder trails
    be_stop = entry         # breakeven stop, armed the session after the scale-out
    pending_trail_exit = False

    last = min(i0 + rule.max_sessions, n - 1)
    # Whether the target ever filled is a fact about the trade, not about how it
    # ended. Folding it into `exit_reason` loses it on any trade still open at
    # the cap, which is exactly where a big winner would be.
    for i in range(i0, last + 1):
        o, h, l, c, e = (a["open"][i], a["high"][i], a["low"][i],
                         a["close"][i], a["ema"][i])
        if i == i0:
            # Entry day: only the post-entry portion is reachable, and the
            # position cannot be exited on the open it was entered after.
            lo, hi = d0_low, d0_high
            o = np.nan
        else:
            lo, hi = l, h

        if not scaled_out:
            # --- gap through a level: the fill is the open, not the level ---
            if not np.isnan(o) and o <= stop:
                return (proceeds + (1.0 - filled) * o, i - i0, STOP_GAP, i, scaled_out)
            if not np.isnan(o) and o >= target:
                proceeds += half * o
                filled += half
                scaled_out = True
                continue

            hit_stop = (not np.isinf(lo)) and lo <= stop
            hit_target = (not np.isinf(hi)) and hi >= target
            if hit_stop and hit_target:
                # The one thing the data cannot resolve. Bracket it.
                if optimistic:
                    proceeds += half * target
                    filled += half
                    scaled_out = True
                    continue
                return (proceeds + (1.0 - filled) * stop, i - i0, STOP, i, scaled_out)
            if hit_stop:
                return (proceeds + (1.0 - filled) * stop, i - i0, STOP, i, scaled_out)
            if hit_target:
                proceeds += half * target
                filled += half
                scaled_out = True
                continue
        else:
            # --- remainder: breakeven stop, then the trail ---
            if pending_trail_exit and not np.isnan(o):
                return (proceeds + (1.0 - filled) * o, i - i0,
                        TARGET_THEN_TRAIL, i, True)
            if not np.isnan(o) and o <= be_stop:
                return (proceeds + (1.0 - filled) * o, i - i0,
                        TARGET_THEN_BREAKEVEN, i, True)
            if (not np.isinf(lo)) and lo <= be_stop:
                return (proceeds + (1.0 - filled) * be_stop, i - i0,
                        TARGET_THEN_BREAKEVEN, i, True)
            if not np.isnan(e) and c < e:
                if rule.trail_exec_next_open:
                    pending_trail_exit = True
                else:
                    return (proceeds + (1.0 - filled) * c, i - i0,
                            TARGET_THEN_TRAIL, i, True)

    # Ran past the cap, or off the end of the symbol's history.
    reason = TIMEOUT if last == i0 + rule.max_sessions else OPEN_AT_END
    return (proceeds + (1.0 - filled) * a["close"][last], last - i0, reason,
            last, scaled_out)


def simulate(trades: pd.DataFrame, bars: pd.DataFrame,
             rule: BracketRule | None = None, optimistic: bool = False,
             entry_timing: str = "open", verbose: bool = False) -> pd.DataFrame:
    """Run the rule over every trade. One row in, one row out.

    Parameters
    ----------
    trades : DataFrame
        Needs `symbol`, `date`, `entry_px_adj`, `stop_px_adj`. When
        `entry_timing="intraday_window"` it also needs `running_low_t` and
        `running_high_t` on the same adjusted basis.
    entry_timing : {"open", "close", "intraday_window"}
        When on date D the fill happened. Determines which of the entry day's
        extremes the position could have met — exactly, in every case.
    """
    if entry_timing not in ENTRY_TIMINGS:
        raise ValueError(
            f"entry_timing must be one of {ENTRY_TIMINGS}, got {entry_timing!r}")
    rule = rule or BracketRule()
    arrays = _symbol_arrays(bars, rule)
    idx = {s: pd.Series(np.arange(len(a["date"])), index=a["date"])
           for s, a in arrays.items()}

    rets, held, reasons, ends, hit = [], [], [], [], []
    for row in trades.itertuples(index=False):
        a = arrays.get(row.symbol)
        if a is None or row.symbol not in idx:
            rets.append(np.nan); held.append(-1); reasons.append("no_bars")
            ends.append(-1); hit.append(False)
            continue
        pos = idx[row.symbol].get(row.date, None)
        if pos is None or not np.isfinite(row.entry_px_adj) or row.entry_px_adj <= 0:
            rets.append(np.nan); held.append(-1); reasons.append("no_entry")
            ends.append(-1); hit.append(False)
            continue
        i0 = int(pos)

        d0_low, d0_high = _entry_day_extremes(a, i0, row, entry_timing)

        px, h, why, end_i, tgt = _simulate_one(
            a, i0, float(row.entry_px_adj), float(row.stop_px_adj),
            d0_low, d0_high, rule, optimistic)
        rets.append((px / row.entry_px_adj - 1.0) * 100.0)
        held.append(h); reasons.append(why); ends.append(end_i); hit.append(tgt)

    out = trades.copy()
    out["payoff_ret_pct"] = rets
    out["sessions_held"] = held
    out["exit_reason"] = reasons
    out["target_filled"] = hit
    out["_end_idx"] = ends
    out["ordering"] = "optimistic" if optimistic else "pessimistic"
    if verbose:
        ok = out["payoff_ret_pct"].notna()
        print(f"  {'optimistic' if optimistic else 'pessimistic'}: "
              f"{int(ok.sum()):,} trades, mean {out.loc[ok, 'payoff_ret_pct'].mean():+.3f}%, "
              f"median {out.loc[ok, 'payoff_ret_pct'].median():+.3f}%")
    return out


def attach_benchmark(sim: pd.DataFrame, bars: pd.DataFrame,
                     rule: BracketRule | None = None,
                     min_symbols: int = 50) -> pd.DataFrame:
    """Compound the equal-weighted market over each trade's own holding window.

    A variable-horizon strategy cannot be judged against a fixed-horizon
    benchmark: a rule that happens to hold winners for thirty sessions and
    losers for two would look brilliant against a flat five-day comparison in a
    rising market, purely from the holding periods.
    """
    mkt = daily_market_return(bars, min_symbols=min_symbols)
    # A session with too few priced names has an UNKNOWN market return, not a
    # flat one. Filling it with zero here would quietly credit the strategy with
    # beating a market that simply was not measured, so those sessions are
    # counted and any trade whose holding window contains one is left NaN.
    bad = mkt.isna()
    cum = np.log1p(mkt.fillna(0.0)).cumsum()
    bad_cum = bad.cumsum()
    dates = cum.index.to_numpy()
    cumv, badv = cum.to_numpy(), bad_cum.to_numpy()

    pos = pd.Series(np.arange(len(dates)), index=cum.index)
    start = sim["date"].map(pos)
    # The benchmark runs over the same sessions the trade was open.
    end = (start + sim["sessions_held"]).clip(upper=len(dates) - 1)
    ok = start.notna() & (sim["sessions_held"] >= 0)
    b = np.full(len(sim), np.nan)
    si = start[ok].to_numpy(dtype=int)
    ei = end[ok].to_numpy(dtype=int)
    vals = np.expm1(cumv[ei] - cumv[si]) * 100.0
    vals[badv[ei] - badv[si] > 0] = np.nan
    b[ok.to_numpy()] = vals
    out = sim.copy()
    out["bench_over_hold_pct"] = b
    out["payoff_excess_pct"] = out["payoff_ret_pct"] - out["bench_over_hold_pct"]
    return out


def _bracket_stats(d: pd.DataFrame) -> dict:
    r = d["payoff_ret_pct"].dropna()
    x = d["payoff_excess_pct"].dropna()
    return {
        "n": int(len(r)),
        "mean_pct": round(float(r.mean()), 4),
        "median_pct": round(float(r.median()), 4),
        "hit_rate_pct": round(float((r > 0).mean() * 100), 2),
        "mean_excess_pct": round(float(x.mean()), 4),
        "median_sessions_held": float(d.loc[r.index, "sessions_held"].median()),
        "target_filled_pct": round(float(d["target_filled"].mean() * 100), 2),
        "exit_mix_pct": {k: round(v * 100, 2) for k, v in
                         d["exit_reason"].value_counts(normalize=True).items()},
    }


def bracket(trades: pd.DataFrame, bars: pd.DataFrame,
            rule: BracketRule | None = None, entry_timing: str = "open",
            min_symbols: int = 50, verbose: bool = False
            ) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Both orderings, and the width between them.

    The width is the part of the expectancy that the data on hand genuinely
    cannot determine — and therefore what higher-resolution data would buy.
    """
    rule = rule or BracketRule()
    pes = attach_benchmark(simulate(trades, bars, rule, optimistic=False,
                                    entry_timing=entry_timing, verbose=verbose),
                           bars, rule, min_symbols=min_symbols)
    opt = attach_benchmark(simulate(trades, bars, rule, optimistic=True,
                                    entry_timing=entry_timing, verbose=verbose),
                           bars, rule, min_symbols=min_symbols)

    both = int(((pes["exit_reason"] == STOP) & (opt["exit_reason"] != STOP)).sum())
    return {
        "pessimistic": _bracket_stats(pes),
        "optimistic": _bracket_stats(opt),
        "bracket_width_pct": round(_bracket_stats(opt)["mean_pct"]
                                   - _bracket_stats(pes)["mean_pct"], 4),
        "trades_whose_outcome_the_data_cannot_resolve": both,
        "share_unresolved_pct": round(both / max(len(pes), 1) * 100, 2),
        "entry_timing": entry_timing,
        "rule": {k: getattr(rule, k) for k in
                 ("target_pct", "scale_out_frac", "trail_ema", "max_sessions")},
    }, pes, opt
