"""The strategy's actual payoff, bracketed — not a fixed-horizon return.

WHY THIS EXISTS
Everything up to here asked "if I buy at 09:20, what is the excess return at
D+5". That is not this strategy's payoff. The stated rule is

    enter → stop below the running low → +15-20% target → sell half
          → stop to breakeven → trail the rest on the 10-EMA

and those are different functions of the same price path. They can disagree in
*sign* on the same trades: if most setups drift to -3% by D+5 but the stop takes
them out at -1%, and a minority reach +18%, fill the target, then give it back
by D+5, the fixed-horizon label says the strategy loses while the traded rule
makes money. Every negative result in H001, H002, H009 and H013 is subject to
that, and none of them is a verdict on the strategy as traded. See H017.

WHY THIS PRODUCES A BRACKET RATHER THAN A NUMBER
A daily bar records a high and a low and not their order. On a session where
both the stop and the target were touched, the outcome is genuinely
undetermined by the data — the same bar is a winner if the target filled first
and a loser if the stop did. So the simulation runs twice, resolving every
ambiguity first in the trade's favour and then against it, and reports both. The
truth lies between.

That width is the whole point. **If the bracket is narrow, the question is
settled without the full-session intraday pull. If it is wide, the width is
exactly what the pull would buy** — and H006 has been the standing justification
for that pull without anyone measuring how much it is worth.

THE ENTRY DAY, WHICH IS NOT AS UNUSABLE AS IT LOOKS
The entry day's daily high and low include 09:15-09:20, before the position
exists. Pairing those with a 09:20 entry is exactly the H004 error, which is why
`labelling.py` offers clean `mfe_*` from D+1 and contaminated `*_incl_d0` twins.
But dropping the entry day understates stop-outs badly — a stop 2% below entry
is very often hit the same afternoon — and that biases the payoff upward.

The 1-second panel closes this exactly. `low_D <= low_t` always, because the
window is part of the day. So:

- `low_D < low_t` → the day's low came **after** entry; the post-entry low is
  `low_D`, and this is certain, not assumed;
- `low_D == low_t` → the low happened **inside** the window, so price never
  traded below `low_t` after entry; and since `stop < low_t` by construction,
  the stop certainly was **not** hit on the entry day.

Symmetrically for the high and the target. The entry-day afternoon is therefore
fully usable for touch detection, with no ambiguity introduced and none assumed
away. This is a strict improvement on the `*_incl_d0` twins.

GAP-THROUGH, WITHOUT WHICH THE STOP IS FICTION
A stop is not a fill. A session that opens below the stop fills at the open, and
on this pool that is where much of the loss actually lives. Every level here —
initial stop, target, breakeven stop — is checked against the session's open
first and filled there when the open has already passed it.

WHAT THIS IS NOT
Not a backtest. There is no position sizing, no capital constraint, no
sequencing across overlapping trades, no costs, and no slippage beyond the gap
logic. It answers one question: on these trades, does the traded payoff disagree
with the fixed-horizon label, and by how much.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ...core import config

# Exit reasons, in the order the simulator can produce them.
STOP = "stop"
STOP_GAP = "stop_gap"
TARGET_THEN_TRAIL = "target_then_trail"
TARGET_THEN_BREAKEVEN = "target_then_breakeven"
TRAIL = "trail"
TIMEOUT = "timeout"
OPEN_AT_END = "still_open"


@dataclass(frozen=True)
class PayoffConfig:
    """The stated rule, made executable. Every field is the uncle's, not tuned.

    `max_sessions` is the one number with no source in the brief. It exists
    because a trailed position must terminate for the statistic to be defined,
    and trades still open at the cap are reported separately rather than being
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

    `labelling._benchmark` gives fixed-horizon forward returns, which is the
    wrong shape here: these trades run for however long the rule keeps them, so
    the benchmark has to be compounded over each trade's own holding window.
    """
    b = bars.sort_values(["symbol", "date"])
    prev = b.groupby("symbol", sort=False)["close"].shift(1)
    r = (b["close"] / prev - 1.0)
    r = r.where(r.abs() < 0.6)          # guard against bad prints, as elsewhere
    g = pd.DataFrame({"date": b["date"], "r": r}).groupby("date")["r"]
    out = g.mean()
    return out.where(g.count() >= min_symbols)


def _symbol_arrays(bars: pd.DataFrame, cfg: PayoffConfig) -> dict:
    """Per-symbol date-aligned OHLC and trail EMA, as numpy for the walk-forward."""
    b = bars.sort_values(["symbol", "date"]).reset_index(drop=True)
    b["ema_trail"] = (b.groupby("symbol", sort=False)["close"]
                      .transform(lambda s: s.ewm(span=cfg.trail_ema, adjust=False).mean()))
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


def _simulate_one(a: dict, i0: int, entry: float, stop: float,
                  d0_low: float, d0_high: float,
                  cfg: PayoffConfig, optimistic: bool) -> tuple:
    """Walk one trade forward. `i0` is the entry day's index in the symbol's array.

    `d0_low` / `d0_high` are the **post-entry** extremes of the entry day, already
    resolved against the opening window by the caller: +inf / -inf mean "the
    extreme happened before entry and is therefore unreachable", which is a
    certainty from the tick data rather than an assumption.

    `optimistic` resolves the one thing daily bars cannot say — whether the high
    or the low came first on a session that touched both.
    """
    target = entry * (1 + cfg.target_pct / 100.0)
    n = len(a["close"])
    filled = 0.0            # fraction of the position already exited
    proceeds = 0.0          # sum of fraction * exit price
    half = cfg.scale_out_frac

    scaled_out = False      # target has filled; remainder trails
    be_stop = entry         # breakeven stop, armed the session after the scale-out
    pending_trail_exit = False

    last = min(i0 + cfg.max_sessions, n - 1)
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
                if not (np.isnan(lo) or np.isinf(lo)):
                    pass        # breakeven arms next session; see docstring
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
            # --- remainder: breakeven stop, then the 10-EMA trail ---
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
                if cfg.trail_exec_next_open:
                    pending_trail_exit = True
                else:
                    return (proceeds + (1.0 - filled) * c, i - i0,
                            TARGET_THEN_TRAIL, i, True)

    # Ran past the cap, or off the end of the symbol's history.
    reason = TIMEOUT if last == i0 + cfg.max_sessions else OPEN_AT_END
    return (proceeds + (1.0 - filled) * a["close"][last], last - i0, reason,
            last, scaled_out)


def simulate(trades: pd.DataFrame, bars: pd.DataFrame,
             cfg: PayoffConfig | None = None, optimistic: bool = False,
             verbose: bool = True) -> pd.DataFrame:
    """Run the rule over every trade. One row in, one row out.

    `trades` needs `symbol`, `date`, `entry_px_adj`, `stop_px_adj`, and the
    opening-window extremes `running_low_t` / `running_high_t` on the same
    adjusted basis, so the entry day can be resolved exactly.
    """
    cfg = cfg or PayoffConfig()
    arrays = _symbol_arrays(bars, cfg)
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

        # The entry-day resolution described in the module docstring: an extreme
        # that was already set inside the opening window is unreachable.
        d0_low = a["low"][i0] if a["low"][i0] < row.running_low_t - 1e-9 else np.inf
        d0_high = a["high"][i0] if a["high"][i0] > row.running_high_t + 1e-9 else -np.inf

        px, h, why, end_i, tgt = _simulate_one(
            a, i0, float(row.entry_px_adj), float(row.stop_px_adj),
            d0_low, d0_high, cfg, optimistic)
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
                     cfg: PayoffConfig | None = None) -> pd.DataFrame:
    """Compound the equal-weighted market over each trade's own holding window.

    A variable-horizon strategy cannot be judged against a fixed-horizon
    benchmark: a rule that happens to hold winners for thirty sessions and
    losers for two would look brilliant against a flat five-day comparison in a
    rising market, purely from the holding periods.
    """
    cfg = cfg or PayoffConfig()
    mkt = daily_market_return(bars)
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


def bracket(trades: pd.DataFrame, bars: pd.DataFrame,
            cfg: PayoffConfig | None = None, verbose: bool = True) -> dict:
    """Both orderings, and the width between them.

    The width is the answer to "what would the intraday pull buy": it is the
    part of the expectancy that the data on hand genuinely cannot determine.
    """
    cfg = cfg or PayoffConfig()
    pes = attach_benchmark(simulate(trades, bars, cfg, optimistic=False,
                                    verbose=verbose), bars, cfg)
    opt = attach_benchmark(simulate(trades, bars, cfg, optimistic=True,
                                    verbose=verbose), bars, cfg)

    def _stats(d: pd.DataFrame) -> dict:
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

    both = int(((pes["exit_reason"] == STOP) & (opt["exit_reason"] != STOP)).sum())
    return {
        "pessimistic": _stats(pes),
        "optimistic": _stats(opt),
        "bracket_width_pct": round(_stats(opt)["mean_pct"] - _stats(pes)["mean_pct"], 4),
        "trades_whose_outcome_the_data_cannot_resolve": both,
        "share_unresolved_pct": round(both / max(len(pes), 1) * 100, 2),
        "config": {k: getattr(cfg, k) for k in
                   ("target_pct", "scale_out_frac", "trail_ema", "max_sessions")},
    }, pes, opt


def compare_to_fixed_horizon(pes: pd.DataFrame, opt: pd.DataFrame,
                             horizon: int = 5) -> pd.DataFrame:
    """The H017 question, in one table: do the two labels disagree, and where.

    Reports the fixed-horizon excess return and the payoff excess return on the
    **identical** trades, so any difference is the label and not the sample.
    """
    from .explore import cluster_stats
    col = f"excess_ret_{horizon}d_pct"
    rows = []
    for name, d in (("fixed_horizon", pes), ("payoff_pessimistic", pes),
                    ("payoff_optimistic", opt)):
        y = d[col] if name == "fixed_horizon" else d["payoff_excess_pct"]
        s = cluster_stats(y, d["date"])
        s["label"] = name
        rows.append(s)
    return pd.DataFrame(rows)[["label", "n", "n_dates", "mean", "median",
                               "hit_pct", "t", "naive_t"]]
