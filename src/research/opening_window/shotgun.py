"""A deliberately wide, deliberately overfitting search for *any* positive expectancy.

WHAT THIS IS, AND THE HONESTY IT REQUIRES
Every previous phase was built to avoid fooling itself. This one is built to
find something, on the user's explicit instruction: try a lot of things, do not
worry about overfitting, and if nothing on the training window is profitable the
strategy gets dropped. That is a legitimate decision procedure — there is no
point protecting a hypothesis from out-of-sample failure if it cannot clear
in-sample profitability first — but it inverts the usual burden, so the results
carry a different label:

**Nothing in this module is evidence. It is a screen for whether evidence is
worth looking for.** A positive number here means "keep going", not "this
works". The 2020-2023 holdout is still fenced off and still untouched.

WHY A NEW SIMULATOR
`payoff.py` walks each trade in a Python loop. That is right for one careful
answer and useless for six hundred: a full sweep over exits x directions x
filters is a few hundred thousand simulations. This module precomputes the
forward price path once as dense arrays and then evaluates any exit rule as
numpy operations over them, which turns a sweep from hours into seconds. The
cost is that the exits it can express are simpler than `payoff.PayoffConfig` —
see `simulate` for exactly what is and is not modelled.

THE THREE LEVERS, IN THE ORDER THEY ARE LIKELY TO MATTER

1. **The exit.** Phase 2.8 found that 27.7% of all mornings are stopped out and
   *then* the stock moves 3%+ (median MFE +7.53%). That is more than one morning
   in four where the selection was fine and the stop was the problem. If any
   lever moves expectancy, this is the one.
2. **Selection, not filtering.** Every test so far asked "does this filter have
   positive expectancy across all the mornings that pass it". That is not the
   strategy. The strategy looks at a morning's candidates and trades **one**.
   Ranking the cross-section and taking the top few is a different question with
   a different answer, and it has never been asked here.
3. **Direction.** Phase 2.8's contrasts all pointed the same way: the mornings
   that worked were *below* their averages, not breaking out above them. If the
   pool has any structure it may be a fade, and the long-only framing would have
   hidden it. Both directions are run on everything.

WHAT IS HELD FIXED, BECAUSE IT IS NOT NEGOTIABLE EVEN HERE
- The fence. `explore.fence()` raises on any row outside 2023-08-21 .. 2026-08-18.
- Causality at `t`. Entries, stops and every feature come from the same causal
  panel Phase 2.8 used; nothing from after the decision point enters a filter.
- The benchmark. Expectancy is judged on **excess** over the equal-weighted
  market compounded across each trade's own holding window. H017 showed that raw
  returns improve monotonically as stops widen purely because longer holds
  collect more market drift — a sweep judged on raw returns would find a
  beautiful, entirely spurious answer, and this module runs exactly that sweep.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from ...core import config
from ...research_data import repository
from . import discovery, explore

MAX_H = 30


# --------------------------------------------------------------------------
# dense forward paths
# --------------------------------------------------------------------------

def build_paths(frame: pd.DataFrame, horizon: int = MAX_H,
                verbose: bool = True) -> dict:
    """Open/high/low/close plus trailing EMAs for D0..D+H, as dense arrays.

    The entry day is resolved exactly as `payoff.simulate` and
    `discovery.forward_paths` do: an extreme already printed inside the opening
    window is unreachable after the entry, so it is masked to +/-inf rather than
    credited. Skipping that step inflates every favourable-excursion statistic
    at once and is the H004 error in another costume.
    """
    bars = repository.daily_bars(
        columns=["symbol", "date", "open", "high", "low", "close"])
    bars = bars.sort_values(["symbol", "date"]).reset_index(drop=True)
    for span in (10, 20):
        bars[f"ema{span}"] = bars.groupby("symbol", sort=False)["close"].transform(
            lambda s, sp=span: s.ewm(span=sp, adjust=False).mean())

    arrays, index = {}, {}
    cols = ["open", "high", "low", "close", "ema10", "ema20"]
    for sym, g in bars.groupby("symbol", sort=False):
        arrays[sym] = tuple(g[c].to_numpy(dtype=float) for c in cols)
        index[sym] = pd.Series(np.arange(len(g)), index=g["date"].to_numpy())

    n, H = len(frame), horizon
    out = {c: np.full((n, H + 1), np.nan) for c in cols}
    n_sess = np.zeros(n, dtype=int)
    syms = frame["symbol"].to_numpy()
    dates = frame["date"].to_numpy()
    for k in range(n):
        a = arrays.get(syms[k])
        if a is None:
            continue
        pos = index[syms[k]].get(dates[k], None)
        if pos is None:
            continue
        i0 = int(pos)
        end = min(i0 + H, len(a[0]) - 1)
        n_sess[k] = end - i0
        m = end - i0 + 1
        for ci, c in enumerate(cols):
            out[c][k, :m] = a[ci][i0:end + 1]

    rl = frame["running_low_t_adj"].to_numpy(dtype=float)
    rh = frame["running_high_t_adj"].to_numpy(dtype=float)
    # Unreachable entry-day extremes.
    out["high"][:, 0] = np.where(out["high"][:, 0] > rh + 1e-9, out["high"][:, 0], -np.inf)
    out["low"][:, 0] = np.where(out["low"][:, 0] < rl - 1e-9, out["low"][:, 0], np.inf)
    # The entry day's "open" for gap-through purposes is the entry itself: you
    # are already in at the entry price, so a gap cannot occur on day 0.
    out["open"][:, 0] = frame["entry_px_adj"].to_numpy(dtype=float)

    out["entry"] = frame["entry_px_adj"].to_numpy(dtype=float)
    out["atr_pct"] = frame["atr_pct"].to_numpy(dtype=float)
    out["n_sess"] = n_sess
    out["date"] = frame["date"].to_numpy()
    out["horizon"] = H
    if verbose:
        print(f"  paths: {n:,} trades x {H} forward sessions, "
              f"{int((n_sess >= H).sum()):,} complete")
    return out


# --------------------------------------------------------------------------
# the exit rule, vectorised
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ExitConfig:
    """An exit rule expressible as array operations.

    `stop_atr` / `target_atr` are multiples of the stock's own ATR, which is the
    only scale on which one rule means the same thing across a 1.5% ATR name and
    a 6% one. `target_pct` overrides `target_atr` when set, so the uncle's stated
    flat +15% can be run alongside volatility-scaled variants.

    **What is not modelled, deliberately.** The EMA trail exits the remainder at
    the first close below the EMA, filled at the *next* open (the same rule
    `payoff.py` uses — a close below the trail is a signal, not a fill). Partial
    re-entries, breakeven-stop moves after the scale-out, and pyramiding are not
    modelled at all. If a config wins here it must be re-run through
    `payoff.simulate` before it is believed.
    """
    stop_atr: float | None = 1.0
    target_atr: float | None = None
    target_pct: float | None = 15.0
    scale_out: float = 0.5
    trail_ema: int | None = 10
    # WHERE the trail starts, and it is not a detail. The stated rule trails
    # only the *remainder* after the scale-out, so the trail cannot exit a
    # position that never reached the target. Trailing from entry instead is a
    # far tighter rule — it exits 47% of trades with a median hold of 2 sessions
    # against 5 — and validating against `payoff.simulate` with the wrong one
    # produced a 0.74 correlation and an 0.08pp expectancy gap. Both are worth
    # sweeping; conflating them is not.
    trail_from: str = "target"      # "target" (stated rule) or "entry"
    time_stop: int = 20
    direction: int = 1              # +1 long, -1 short

    def label(self) -> str:
        t = ("none" if (self.target_atr is None and self.target_pct is None)
             else (f"{self.target_pct}%" if self.target_pct else f"{self.target_atr}atr"))
        tr = f"{self.trail_ema}@{self.trail_from}" if self.trail_ema else "none"
        return (f"{'L' if self.direction > 0 else 'S'} "
                f"stop={self.stop_atr if self.stop_atr else 'none'}atr "
                f"tgt={t} trail={tr} T={self.time_stop}")


def simulate(paths: dict, cfg: ExitConfig) -> dict:
    """Return per-trade net return %, holding length and exit reason.

    Ordering inside a session is resolved **pessimistically**: if both the stop
    and the target are touched on the same session, the stop is taken. H006
    measured that ambiguity at 0.02% of expectancy, so this is a formality — but
    it is the conservative formality, and a sweep this wide would otherwise be
    free to pick configs that win only on the optimistic reading.

    **Shorts are handled by mirroring the price axis**, not by negating the
    answer at the end. Every price becomes `-price` and the entry `-entry`, so
    "adverse" is down and "favourable" is up in both directions and one set of
    comparisons serves both. The P&L is then `(exit - entry) / |entry|`, which
    is correct in the mirrored space for either sign — writing it as
    `exit / entry - 1` is *not*, and silently returns the long P&L for a short.
    """
    H = min(cfg.time_stop, paths["horizon"])
    d = cfg.direction
    e = paths["entry"]
    atr = np.nan_to_num(paths["atr_pct"], nan=3.0)

    hi = paths["high"][:, :H + 1]
    lo = paths["low"][:, :H + 1]
    cl = paths["close"][:, :H + 1]
    op = paths["open"][:, :H + 1]
    n, W = hi.shape
    idx = np.arange(W)[None, :]
    live = idx <= paths["n_sess"][:, None]

    # Mirror for shorts. `fav` is the direction that makes money.
    fav_hi = hi if d > 0 else -lo
    adv_lo = lo if d > 0 else -hi
    ent = e * d
    px_cl = cl * d
    px_op = op * d
    unit = np.abs(e)

    stop_px = (ent - unit * (cfg.stop_atr * atr) / 100.0
               if cfg.stop_atr is not None else np.full(n, -np.inf))
    if cfg.target_pct is not None:
        tgt_frac = cfg.target_pct / 100.0
    elif cfg.target_atr is not None:
        tgt_frac = (cfg.target_atr * atr) / 100.0
    else:
        tgt_frac = None
    tgt_px = (ent + unit * tgt_frac) if tgt_frac is not None else np.full(n, np.inf)

    BIG = W + 10
    stop_hit = live & (adv_lo <= stop_px[:, None])
    tgt_hit = live & (fav_hi >= tgt_px[:, None])
    s_stop = np.where(stop_hit.any(1), stop_hit.argmax(1), BIG)
    s_tgt = np.where(tgt_hit.any(1), tgt_hit.argmax(1), BIG)

    # Trail: first close beyond the EMA, filled at the NEXT open. A close below
    # the trail is a signal, not a fill; exiting at the signal close hands the
    # strategy a price it could not have got (`payoff.py` makes the same choice).
    if cfg.trail_ema:
        ema_s = paths[f"ema{cfg.trail_ema}"][:, :W] * d
        tr = live & (px_cl < ema_s)
        tr[:, 0] = False
        s_trail = np.where(tr.any(1), np.minimum(tr.argmax(1) + 1, W - 1), BIG)
    else:
        s_trail = np.full(n, BIG)

    last = np.minimum(paths["n_sess"], H)
    r = np.arange(n)

    def _pnl(price_at):
        return (price_at - ent) / unit * 100.0

    # Gap-through: a session opening beyond the stop fills at that open. Without
    # this a stop sweep is really a sweep over an instrument that never gaps,
    # and wide stops look far better than they are.
    si = np.clip(s_stop, 0, W - 1)
    fill = np.minimum(px_op[r, si], stop_px)
    ret_stop = _pnl(fill)
    ret_trail = _pnl(px_cl[r, np.clip(np.minimum(s_trail, last), 0, W - 1)])
    ret_time = _pnl(px_cl[r, last])

    # Under the stated rule the trail arms only after the scale-out, so it
    # cannot exit a position that never reached the target.
    trail_live_pre = cfg.trail_ema is not None and cfg.trail_from == "entry"
    s_trail_pre = s_trail if trail_live_pre else np.full(n, BIG)

    tgt_first = (s_tgt < s_stop) & (s_tgt <= s_trail_pre) & (s_tgt <= last)
    stop_first = (~tgt_first) & (s_stop <= np.minimum(s_trail_pre, last))
    trail_first = (~tgt_first) & (~stop_first) & (s_trail_pre <= last)

    ret_trail_pre = _pnl(px_cl[r, np.clip(np.minimum(s_trail_pre, last), 0, W - 1)])
    ret_tgt = _pnl(tgt_px)
    # After the scale-out the remainder runs to the trail or the time stop. The
    # original stop is not re-applied — the stated rule lifts it to breakeven,
    # and charging the runner the full original stop again would be wrong in the
    # other direction. Noted as a simplification, not a claim.
    # The remainder is trailed from the target session onward, so a trail signal
    # that fired *before* the target is not available to it.
    s_trail_post = np.where(s_trail > s_tgt, s_trail, BIG)
    ret_trail_post = _pnl(px_cl[r, np.clip(np.minimum(s_trail_post, last), 0, W - 1)])
    after = np.where(s_trail_post <= last, ret_trail_post, ret_time)
    combined = cfg.scale_out * ret_tgt + (1 - cfg.scale_out) * after

    ret = np.where(tgt_first, combined,
                   np.where(stop_first, ret_stop,
                            np.where(trail_first, ret_trail_pre, ret_time)))
    held = np.where(tgt_first, np.minimum(np.minimum(s_trail_post, last), last),
                    np.where(stop_first, np.minimum(s_stop, last),
                             np.minimum(s_trail_pre, last)))
    reason = np.where(tgt_first, "target",
                      np.where(stop_first, "stop",
                               np.where(trail_first, "trail", "time")))
    ok = paths["n_sess"] > 0
    return {"ret_pct": np.where(ok, ret, np.nan),
            "held": np.clip(held, 0, None).astype(int), "reason": reason}


# --------------------------------------------------------------------------
# benchmark and scoring
# --------------------------------------------------------------------------

def market_curve() -> pd.Series:
    """Cumulative log return of the equal-weighted market, indexed by session."""
    from ...research_data.pipelines import context
    _, mkt = context.load()
    m = mkt.set_index("date")["mkt_index"]
    return np.log(m)


def attach_excess(paths: dict, sim: dict, curve: pd.Series,
                  direction: int = 1) -> np.ndarray:
    """Excess over the market compounded across each trade's own holding window.

    The non-negotiable from H017: a variable-horizon rule judged on raw returns
    rewards itself for holding longer in a rising market. Every number this
    module reports is net of the market over the identical sessions.

    **The sign of the benchmark follows the position, not the report.** A long
    carries roughly +1 market beta and a short roughly -1, so alpha is
    `r - m` for a long and `r + m` for a short. Subtracting the market from a
    short would charge it for the market twice and quietly rank shorts by how
    badly the market did — in a single rising market like 2023-2026 that is
    enough to invert a whole sweep.
    """
    pos = pd.Series(np.arange(len(curve)), index=curve.index)
    start = pd.Series(paths["date"]).map(pos).to_numpy()
    ok = ~np.isnan(start)
    si = np.where(ok, np.nan_to_num(start), 0).astype(int)
    ei = np.clip(si + sim["held"], 0, len(curve) - 1)
    cv = curve.to_numpy()
    bench = (np.expm1(cv[ei] - cv[si])) * 100
    bench = np.where(ok, bench, np.nan)
    return sim["ret_pct"] - np.sign(direction) * bench


def score(excess: np.ndarray, dates: np.ndarray, mask: np.ndarray | None = None
          ) -> dict:
    """Expectancy per trade with session-clustered inference.

    Clustered because mornings on the same session are not independent (H016);
    the naive statistic is carried alongside so the size of the difference stays
    visible rather than being asserted once in a docstring.
    """
    y = pd.Series(excess if mask is None else excess[mask])
    d = pd.Series(dates if mask is None else dates[mask])
    s = explore.cluster_stats(y, d)
    return s


# --------------------------------------------------------------------------
# selection: the question that has never been asked
# --------------------------------------------------------------------------

def top_n_per_day(frame: pd.DataFrame, rank_col: str, n: int,
                  ascending: bool = False, gate: np.ndarray | None = None
                  ) -> np.ndarray:
    """Boolean mask keeping only the best `n` candidates per session.

    This is the shape of the actual strategy and no previous phase has tested
    it. A filter with zero average edge across everything that passes it can
    still be a usable *ranking*, because a ranking is only ever asked to put the
    best few at the top — and conversely a ranking can look strong at the top
    and have no average effect at all. The two questions are not the same one.
    """
    d = frame[["date", rank_col]].copy()
    if gate is not None:
        d.loc[~gate, rank_col] = np.nan
    r = d.groupby("date")[rank_col].rank(ascending=ascending, method="first")
    return (r <= n).to_numpy() & d[rank_col].notna().to_numpy()


# --------------------------------------------------------------------------
# the rule that came out of the sweep, and the report that reproduces it
# --------------------------------------------------------------------------

FROZEN_PATH = config.METADATA_DIR / "shotgun_frozen.json"
REPORT_PATH = config.METADATA_DIR / "shotgun.json"

# Two daily, as-of features, ranked within the session and averaged with equal
# weight. Equal weight on purpose: a fitted weighting is one more thing that
# cannot be defended out of sample, and the sweep found the pair matters far
# more than their relative sizing.
SCORE_FEATURES = ("dist_52w_high", "deliv_pct")


def score_frame(frame: pd.DataFrame,
                features: tuple[str, ...] = SCORE_FEATURES) -> pd.Series:
    """The composite: mean of within-session percentile ranks."""
    r = pd.DataFrame({c: frame.groupby("date")[c].rank(pct=True) for c in features})
    return r.mean(axis=1)


def daily_book(frame: pd.DataFrame, paths: dict, mask: np.ndarray,
               cfg: ExitConfig, cost_pct: float) -> tuple[np.ndarray, np.ndarray]:
    """Daily equal-weighted return of the open book, marked to each close.

    Spreading a trade's total P&L evenly across its holding days — the obvious
    shortcut — smooths the series into a Sharpe of 8.6. That is not a result,
    it is the smoothing. Every open position is marked to its own daily close
    here, and the round-trip cost is charged half at entry and half at exit.
    """
    sim = simulate(paths, cfg)
    sessions = np.sort(frame["date"].unique())
    pos = {t: i for i, t in enumerate(sessions)}
    cl, ent = paths["close"], paths["entry"]
    pnl = np.zeros(len(sessions))
    wts = np.zeros(len(sessions))
    dates = frame["date"].to_numpy()
    for k in np.where(mask & np.isfinite(sim["ret_pct"]))[0]:
        h = max(int(sim["held"][k]), 1)
        i0 = pos.get(dates[k])
        if i0 is None:
            continue
        px = np.concatenate([[ent[k]], cl[k, 1:h + 1]])
        px = px[np.isfinite(px)]
        if len(px) < 2:
            continue
        r = px[1:] / px[:-1] - 1
        r[0] -= cost_pct / 200
        r[-1] -= cost_pct / 200
        end = min(i0 + len(r), len(sessions))
        pnl[i0:end] += r[:end - i0]
        wts[i0:end] += 1
    return np.divide(pnl, np.maximum(wts, 1)), wts


def book_stats(r: np.ndarray, wts: np.ndarray) -> dict:
    live = wts > 0
    if live.sum() < 20:
        return {}
    eq = np.cumprod(1 + r[live])
    yrs = live.sum() / 250
    return {"total_pct": round(float((eq[-1] - 1) * 100), 1),
            "cagr_pct": round(float(eq[-1] ** (1 / yrs) - 1) * 100, 2),
            "max_dd_pct": round(float((eq / np.maximum.accumulate(eq) - 1).min() * 100), 1),
            "sharpe": round(float(r[live].mean() / r[live].std() * np.sqrt(250)), 2),
            "mean_open": int(wts[live].mean()), "sessions": int(live.sum())}


def freeze(payload: dict, path=FROZEN_PATH) -> None:
    """Write the rule out in a form the holdout run can replay unchanged."""
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n-> froze the rule to {path.relative_to(config.PROJECT_ROOT)}")


def report(t: int = 180, top_n: int = 5, time_stop: int = 30,
           cost_pct: float = 0.40, n_perm: int = 400, verbose: bool = True) -> dict:
    """Reproduce the H024 result end to end, with every check that qualifies it.

    Order matters: the headline first, then the three things that would make it
    fake — is it beta, is it search, does the screen matter — and then the entry
    check that says the tick pipeline is not involved.
    """
    from . import discovery as dc

    frame = dc.load_frame(t, verbose=verbose).reset_index(drop=True)
    explore.fence(frame, "shotgun frame")
    frame["score"] = score_frame(frame)
    paths = build_paths(frame, horizon=MAX_H, verbose=verbose)
    curve = market_curve()
    dates = frame["date"].to_numpy()
    cfg = ExitConfig(stop_atr=None, target_pct=None, trail_ema=None,
                     time_stop=time_stop, direction=1)
    sim = simulate(paths, cfg)
    mask = top_n_per_day(frame, "score", top_n)

    r = pd.Series(sim["ret_pct"])
    pool_exc = (r - r.groupby(pd.Series(dates)).transform("mean")).to_numpy()
    mkt_exc = attach_excess(paths, sim, curve, cfg.direction)
    a, b = score(mkt_exc, dates, mask), score(pool_exc, dates, mask)

    out = {"EXPLORATORY": ("Searched on the same window it is measured on, "
                           "across ~1,500 configurations, on explicit "
                           "instruction to overfit. The 2020-2023 holdout is "
                           "untouched and this is not confirmed."),
           "t_offset_s": t, "top_n": top_n, "time_stop": time_stop,
           "score_features": list(SCORE_FEATURES),
           "window": [str(frame["date"].min().date()), str(frame["date"].max().date())],
           "per_trade": {"n": a["n"], "vs_market_pct": a["mean"], "t_market": a["t"],
                         "vs_pool_pct": b["mean"], "t_pool": b["t"],
                         "raw_pct": round(float(np.nanmean(sim["ret_pct"][mask])), 3)}}
    if verbose:
        print(f"\n== top {top_n}/day, no stop, {time_stop}-session hold ==")
        print(f"  n={a['n']:,}  vs market {a['mean']:+.3f}% (t={a['t']})  "
              f"vs pool {b['mean']:+.3f}% (t={b['t']})  raw {out['per_trade']['raw_pct']:+.3f}%")

    # --- portfolio, against the no-selection baseline --------------------
    books = {}
    for label, m in (("all_candidates", np.ones(len(frame), bool)),
                     (f"top_{top_n}", mask)):
        rr, ww = daily_book(frame, paths, m, cfg, cost_pct)
        books[label] = book_stats(rr, ww)
    sessions = np.sort(frame["date"].unique())
    mk = np.nan_to_num(np.expm1(np.diff(np.concatenate(
        [[curve.reindex(sessions).to_numpy()[0]], curve.reindex(sessions).to_numpy()]))))
    books["market"] = book_stats(mk, np.ones(len(sessions)))
    out["portfolio"] = {"cost_pct_round_trip": cost_pct, "books": books}
    if verbose:
        print(f"\n  portfolio at {cost_pct}% round-trip cost:")
        for k, v in books.items():
            if v:
                print(f"    {k:16s} CAGR {v['cagr_pct']:+6.2f}%  "
                      f"maxDD {v['max_dd_pct']:6.1f}%  Sharpe {v['sharpe']:5.2f}")

    # --- is it search? the within-session shuffle of the score -----------
    rng = np.random.default_rng(0)
    grp = frame.groupby("date").indices
    means = []
    for _ in range(n_perm):
        sc = frame["score"].to_numpy().copy()
        for idx in grp.values():
            if len(idx) > 1:
                sc[idx] = sc[rng.permutation(idx)]
        f2 = frame[["date"]].copy()
        f2["s"] = sc
        rk = f2.groupby("date")["s"].rank(ascending=False, method="first")
        means.append(score(pool_exc, dates, (rk <= top_n).to_numpy())["mean"])
    means = np.array(means, dtype=float)
    out["permutation"] = {
        "n_perm": n_perm, "null_p95": round(float(np.percentile(means, 95)), 3),
        "null_max": round(float(np.nanmax(means)), 3),
        "observed": b["mean"],
        "beats_pct_of_shuffles": round(float((b["mean"] > means).mean() * 100), 1)}
    if verbose:
        p = out["permutation"]
        print(f"\n  permutation null ({n_perm} within-session shuffles of the score):")
        print(f"    p95 {p['null_p95']:+.3f}%  max {p['null_max']:+.3f}%  "
              f"observed {p['observed']:+.3f}%  beats {p['beats_pct_of_shuffles']}%")
    return out
