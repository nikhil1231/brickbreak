"""Market regime, breakout location and relative strength — the three families
the existing panels cannot see, and the reverse-discovery phase cannot do without.

WHY THESE THREE AND NOT THIRTY
The standing instruction for this phase is *not* to add generic indicators one
at a time. These are not that. The reverse-discovery question is "what
distinguishes a breakout that works from a superficially identical one that
fails", and three of the families in that question have no representation
anywhere in the pipeline:

- **Where the price is relative to what it has to break.** `screen_metrics` has
  `dist_52w_high` and nothing else about location. A breakout is defined by a
  level; without the level there is no breakout, only a gap and some volume.
- **What the market is doing.** Every result so far is measured against an
  equal-weighted same-session benchmark, which removes the market's *level* and
  says nothing about its *state*. "Breakouts work in trending markets and fail
  in chop" is a first-order claim about this strategy family and it cannot even
  be stated without a regime variable.
- **Relative strength.** `ret_20d` says the stock rose. Whether it rose more
  than its sector and its market is a different fact, and it is the one the
  breakout literature is actually about.

Everything else the phase needs (contraction, trend, gap, opening behaviour)
already exists and is reused rather than re-derived.

THE CAUSALITY RULE, WHICH IS THE WHOLE POINT
Every trailing statistic here ends at **D-1**, computed as a rolling window over
the symbol's own previous sessions and then shifted one session. Date D's
**opening print** is used where the feature is explicitly about the open (it is
on the tape at 09:15:00, before any entry — the one date-D price a morning rule
may use, per `asof.KNOWN_AT_OPEN`). Nothing else from date D enters.

This is enforced by `tests/test_context.py`, which appends later sessions to a
symbol's history and requires every feature on date D to be bit-identical. That
test exists because the identical bug shipped twice already: once in the screen
(H015) and once in `behaviour.time_above_open_frac`.

THE DENOMINATOR TRAP, AGAIN
`behaviour.py` normalised opening volume by `median_vol_20` read off the
*unlagged* metrics panel — a 20-session median that includes date D's own
full-day volume. A lookahead inside a denominator is the easiest kind to miss
because the feature it contaminates does not look like a price feature at all.
Fixed 2026-08-20; noted here because the same shape of error is available to
every ratio in this module and every one of them uses a shifted denominator.

WHAT A "BREAKOUT LEVEL" IS HERE, AND WHAT IT IS NOT
The level is the highest high over the `lookback` sessions ending D-1. That is a
crude proxy for a chart level a person would draw, and it is deliberately crude:
a swing-pivot detector has free parameters (how many bars either side, what
counts as a touch) and this phase has no budget for tuning any of them. Two
lookbacks are carried (20 and 50 sessions) precisely so that a finding which
exists at one and not the other is visible as fragile rather than reported as
real. `n_touches_*` counts how often the level was approached, which is the
nearest thing to "how much supply sits there" that daily bars can say.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ...core import config

CONTEXT_PATH = config.NORMALIZED_DIR / "daily_context.parquet"
MARKET_PATH = config.NORMALIZED_DIR / "market_regime.parquet"


@dataclass(frozen=True)
class ContextConfig:
    """Windows, not thresholds. Nothing here is a strategy parameter.

    `touch_tol_pct` is the one quantity in price units: how close a session's
    high has to come to the level to count as having tested it. 1% is a round
    number, and `discovery.py` re-runs the affected findings at 0.5% and 2% via
    its nudge check rather than this being assumed away.
    """
    breakout_lookbacks: tuple[int, ...] = (20, 50)
    touch_tol_pct: float = 1.0
    mkt_min_symbols: int = 50
    mkt_trend_window: int = 20
    mkt_slow_window: int = 60
    ret_guard: float = 0.6          # daily returns beyond this are bad prints
    # The investable benchmark's rebalance clock and round-trip cost. See
    # `market_regime`'s note on the rebalancing premium.
    bench_rebal_sessions: int = 20
    bench_cost_pct_round_trip: float = 0.40


# --------------------------------------------------------------------------
# market regime
# --------------------------------------------------------------------------

def _daily_returns(bars: pd.DataFrame, cfg: ContextConfig) -> pd.DataFrame:
    """Per-symbol simple daily returns on adjusted closes, bad prints removed.

    The guard is the same one `payoff.daily_market_return` uses. It is not
    cosmetic: a single unadjusted 10x print in a 1,600-name equal-weighted mean
    moves the index by 0.6% on its own and would define a "regime".
    """
    b = bars.sort_values(["symbol", "date"])
    prev = b.groupby("symbol", sort=False)["close"].shift(1)
    r = b["close"] / prev - 1.0
    return pd.DataFrame({
        "symbol": b["symbol"].to_numpy(),
        "date": b["date"].to_numpy(),
        "ret": r.where(r.abs() < cfg.ret_guard).to_numpy(),
        "close": b["close"].to_numpy(),
    })


def _investable_index(r: pd.DataFrame, sessions: pd.Index,
                      cfg: ContextConfig) -> np.ndarray:
    """Equal-weighted, but actually holdable: weights are set on a fixed clock
    and then **left alone** to drift with returns until the next rebalance, with
    one round trip charged at each rebalance at the rate a book under test pays.

    This exists so a portfolio claim can quote a hurdle nobody can object to,
    not because `mkt_index` was found wanting. It was not: see `market_regime`,
    where the two are decomposed and differ by 0.14-0.16pp of CAGR and 0.00
    Sharpe. Do not describe the difference as a rebalancing premium — measured,
    the rebalancing term runs the other way.
    """
    wide = (r.pivot_table(index="date", columns="symbol", values="ret",
                          aggfunc="last")
             .reindex(sessions)
             .to_numpy(dtype="float64"))
    n_d, n_s = wide.shape
    reb = max(1, cfg.bench_rebal_sessions)
    cost = cfg.bench_cost_pct_round_trip / 100.0
    w = np.zeros(n_s)
    out = np.empty(n_d)
    level = 1.0
    for i in range(n_d):
        ret = np.nan_to_num(wide[i])
        level *= 1.0 + float(np.dot(w, ret))
        if i % reb == 0:
            live = np.isfinite(wide[i])
            if live.sum() >= cfg.mkt_min_symbols:
                neww = np.where(live, 1.0 / live.sum(), 0.0)
                level *= 1.0 - np.abs(neww - w).sum() * cost / 2.0
                w = neww
        else:
            w = w * (1.0 + ret)
            s = w.sum()
            if s > 0:
                w = w / s
        out[i] = level
    return out


def market_regime(bars: pd.DataFrame, cfg: ContextConfig | None = None
                  ) -> pd.DataFrame:
    """One row per session describing the market as of the **previous** close.

    Every column is shifted one session at the end, so the row dated D carries
    what was knowable on the morning of D. The shift happens once, in one place,
    rather than window-by-window, because a per-window shift is exactly the kind
    of thing that gets it right four times and wrong the fifth.

    `mkt_trend_eff` is the trending-vs-sideways measure and the reason this
    function exists: the net move over the summed absolute daily moves. An index
    that rose 6% in twenty straight small steps scores near 1; one that rose 6%
    by way of two 10% round trips scores near 0. Both have the same 20-day
    return, and the claim "breakouts need a trending market" is a claim about
    this number, not about that one.
    """
    cfg = cfg or ContextConfig()
    r = _daily_returns(bars, cfg)
    g = r.groupby("date")["ret"]
    mkt = pd.DataFrame({"mkt_ret": g.mean(), "n_priced": g.count()})
    # A session with too few priced names has an unknown market return, not a
    # flat one. Left NaN, and everything downstream inherits the NaN.
    mkt.loc[mkt["n_priced"] < cfg.mkt_min_symbols, "mkt_ret"] = np.nan
    mkt = mkt.sort_index()

    lr = np.log1p(mkt["mkt_ret"])
    mkt["mkt_index"] = np.exp(lr.cumsum())

    # IS `mkt_index` AN UNFAIR HURDLE? MEASURED: NO. (2026-08-29)
    #
    # `mkt_index` compounds the cross-sectional MEAN daily return, which is an
    # equal-weighted portfolio rebalanced every session at zero cost. Nobody can
    # hold that, so the suspicion is natural: it should harvest a rebalancing
    # premium and quietly overstate the hurdle every rule in the ledger had to
    # clear. The suspicion was checked and it is wrong. Decomposed on both
    # panels, changing one thing at a time, CAGR:
    #
    #                                          legacy 95-19   modern 20-26
    #   A  nightly universe, nightly EW reset       7.77%         21.55%
    #   B  20d universe, nightly EW reset           7.82%         22.03%   universe    -0.05 / -0.48
    #   C  20d universe, weights drift              8.40%         22.29%   rebalancing -0.58 / -0.26
    #   D  C + 40bps round trip  (investable)       7.63%         21.39%   cost        +0.77 / +0.89
    #
    #   free minus investable: +0.14pp / +0.16pp CAGR, and +0.00 Sharpe both.
    #
    # The rebalancing term has the WRONG SIGN for the story -- letting weights
    # drift earns MORE than resetting nightly, so daily rebalancing costs this
    # cross-section money rather than manufacturing it -- and the cost term
    # cancels it. `mkt_index` is a fair hurdle to within 16 bps a year.
    #
    # Two traps found while establishing that, both worth more than the result:
    #
    #   * A liquidity screen built from session D's turnover and then used to
    #     average session D's returns is a SELECTION LOOKAHEAD: turnover is only
    #     known at the close. It inflated a scratch benchmark from 21.6% to
    #     25.9% CAGR and nearly produced a reported "benchmark defect" that does
    #     not exist. `_investable_index` and every mask here use prior-session
    #     liquidity for exactly this reason.
    #   * Comparing "rebalance nightly" against "rebalance nightly" is not a
    #     measurement. The first attempt varied a universe-refresh parameter
    #     that made the drift branch unreachable and read a clean +0.00pp.
    #
    # `mkt_index_investable` is kept as the hurdle a portfolio claim should
    # quote -- it is holdable and it pays what a book pays -- but it is now a
    # documented near-equivalent, not a correction. `mkt_index` stays exactly as
    # it was, so the recorded ledger remains reproducible.
    #
    # Separately and still true: a PER-TRADE excess must use the cohort's
    # buy-and-hold mean over the identical window. `labelling._benchmark`
    # already does; `shotgun.attach_excess` compounds `mkt_index` instead, which
    # is the same object measured above and therefore also near-fair.
    mkt["mkt_index_investable"] = _investable_index(r, mkt.index, cfg)

    w, sw = cfg.mkt_trend_window, cfg.mkt_slow_window

    mkt["mkt_ret_5d"] = (np.exp(lr.rolling(5).sum()) - 1) * 100
    mkt["mkt_ret_20d"] = (np.exp(lr.rolling(w).sum()) - 1) * 100
    mkt["mkt_ret_60d"] = (np.exp(lr.rolling(sw).sum()) - 1) * 100
    mkt["mkt_vol_20d"] = mkt["mkt_ret"].rolling(w).std() * np.sqrt(252) * 100

    # Trending vs sideways: |net| / total travelled over the same window.
    net = lr.rolling(w).sum().abs()
    travel = lr.abs().rolling(w).sum()
    mkt["mkt_trend_eff"] = net / travel.where(travel > 0)
    mkt["mkt_up"] = np.sign(lr.rolling(w).sum())

    ema = mkt["mkt_index"].ewm(span=50, adjust=False).mean()
    mkt["mkt_vs_ema50_pct"] = (mkt["mkt_index"] / ema - 1) * 100
    roll_max = mkt["mkt_index"].rolling(sw, min_periods=20).max()
    mkt["mkt_dd_from_60d_high_pct"] = (mkt["mkt_index"] / roll_max - 1) * 100

    # Breadth: share of names above their own 50-session EMA. Computed on the
    # panel rather than borrowed from `screen_metrics_asof`, whose columns are
    # already lagged — borrowing them and then shifting again would lag twice.
    r = r.sort_values(["symbol", "date"])
    ema_s = r.groupby("symbol", sort=False)["close"].transform(
        lambda s: s.ewm(span=50, adjust=False).mean())
    above = (r["close"] > ema_s)
    br = above.groupby(r["date"]).mean() * 100
    mkt["mkt_breadth_pct"] = br.reindex(mkt.index)

    # The single shift that makes the whole frame as-of. `mkt_ret` itself is
    # dropped rather than shifted: a lagged "today's market return" is a
    # confusing name for yesterday's, and nothing needs it.
    cols = [c for c in mkt.columns if c not in ("n_priced", "mkt_ret")]
    out = mkt[cols].shift(1)
    out["n_priced"] = mkt["n_priced"]
    out = out.reset_index()
    out["mkt_regime"] = _regime_label(out)
    return out


def _regime_label(m: pd.DataFrame, trend_eff_cut: float = 0.35,
                  ret_cut: float = 1.0) -> pd.Series:
    """Four named market states, from two numbers with round cut-points.

    The cut-points are round because they are labels for reading, not
    thresholds being fitted: `discovery.py` reports every regime result against
    the continuous `mkt_trend_eff` as well, and a finding that exists only under
    one labelling is reported as such.
    """
    up = m["mkt_ret_20d"] > ret_cut
    down = m["mkt_ret_20d"] < -ret_cut
    trendy = m["mkt_trend_eff"] > trend_eff_cut
    out = pd.Series("sideways", index=m.index, dtype=object)
    out[up & trendy] = "trending_up"
    out[down & trendy] = "trending_down"
    out[~trendy] = "chop"
    out[m["mkt_ret_20d"].isna()] = "unknown"
    return pd.Categorical(
        out, categories=["trending_up", "trending_down", "chop", "sideways",
                         "unknown"])


# --------------------------------------------------------------------------
# breakout location
# --------------------------------------------------------------------------

def _rolling_prior(g: pd.DataFrame, n: int, cfg: ContextConfig) -> pd.DataFrame:
    """Level features over the `n` sessions ending D-1, for one symbol.

    `shift(1)` is applied to the *rolling result*, so the window is D-n .. D-1
    and date D contributes nothing. Doing it the other way round — shifting the
    input then rolling — gives the same answer here but stops doing so the
    moment a window is changed, so it is done the way that stays correct.
    """
    high, low, close = g["high"], g["low"], g["close"]
    prior_high = high.rolling(n, min_periods=max(5, n // 2)).max().shift(1)
    prior_low = low.rolling(n, min_periods=max(5, n // 2)).min().shift(1)

    # Sessions since the level was set. Done with a strided view rather than
    # `rolling(...).apply(...)`: the apply form is ~200x slower here and this
    # runs over 3.3M rows twice, which is the difference between a command
    # somebody runs and one they work around.
    def _age(s: pd.Series) -> pd.Series:
        a = s.to_numpy(dtype=float)
        out = np.full(len(a), np.nan)
        mp = max(5, n // 2)
        if len(a) >= mp:
            # Expanding prefix, up to the first full window.
            for i in range(mp - 1, min(n - 1, len(a))):
                w = a[: i + 1]
                out[i] = float(len(w) - 1 - np.argmax(w))
            if len(a) >= n:
                win = np.lib.stride_tricks.sliding_window_view(a, n)
                out[n - 1:] = (n - 1) - win.argmax(axis=1)
        return pd.Series(out, index=s.index).shift(1)

    tol = 1 - cfg.touch_tol_pct / 100.0
    out = pd.DataFrame(index=g.index)
    out[f"prior_high_{n}"] = prior_high
    out[f"prior_low_{n}"] = prior_low
    out[f"base_range_{n}_pct"] = (prior_high / prior_low - 1) * 100
    out[f"days_since_high_{n}"] = _age(high)
    # How often the level was tested: sessions whose high came within the
    # tolerance of the eventual window maximum. A level touched six times is a
    # different object from one printed once and left alone.
    near = (high >= high.rolling(n, min_periods=max(5, n // 2)).max() * tol)
    out[f"n_touches_{n}"] = near.rolling(n, min_periods=max(5, n // 2)).sum().shift(1)
    out[f"prev_close_vs_high_{n}_pct"] = (close.shift(1) / prior_high - 1) * 100
    return out


def breakout_location(bars: pd.DataFrame, cfg: ContextConfig | None = None
                      ) -> pd.DataFrame:
    """Where date D's opening print sits relative to the levels behind it.

    The opening print is date D's, deliberately and by the same licence the
    screen's `gap_pct` uses: it is the 09:15:00 call-auction price, on the tape
    before any entry. Every level it is compared against is built from sessions
    strictly before D.
    """
    cfg = cfg or ContextConfig()
    b = bars.sort_values(["symbol", "date"]).reset_index(drop=True)
    parts = [b[["symbol", "date", "open"]]]
    for n in cfg.breakout_lookbacks:
        parts.append(b.groupby("symbol", sort=False, group_keys=False)[
            ["high", "low", "close"]].apply(_rolling_prior, n=n, cfg=cfg))
    d = pd.concat(parts, axis=1)

    for n in cfg.breakout_lookbacks:
        ph = d[f"prior_high_{n}"].where(d[f"prior_high_{n}"] > 0)
        d[f"open_vs_high_{n}_pct"] = (d["open"] / ph - 1) * 100
        # The binary a chart reader would call "it gapped through the level".
        d[f"open_above_high_{n}"] = d["open"] > d[f"prior_high_{n}"]
        pl = d[f"prior_low_{n}"].where(d[f"prior_low_{n}"] > 0)
        rng = (d[f"prior_high_{n}"] - d[f"prior_low_{n}"])
        # Where in its own base the stock opened: 1 = at the base high, 0 = at
        # the base low. The single most direct statement of breakout location.
        d[f"open_base_pos_{n}"] = ((d["open"] - d[f"prior_low_{n}"])
                                   / rng.where(rng > 0))
        d[f"base_low_dist_{n}_pct"] = (d["open"] / pl - 1) * 100
    return d.drop(columns=["open"])


# --------------------------------------------------------------------------
# relative strength
# --------------------------------------------------------------------------

def relative_strength(metrics: pd.DataFrame, mkt: pd.DataFrame,
                      sector: pd.DataFrame, cfg: ContextConfig | None = None
                      ) -> pd.DataFrame:
    """Stock against market, stock against sector, sector against market.

    `metrics` is the **as-of** metrics panel, so `ret_20d` already ends at D-1;
    `mkt` is shifted by `market_regime`. Both sides of every difference
    therefore end on the same session, which is the only way the difference
    means anything.
    """
    cfg = cfg or ContextConfig()
    sec = sector.sort_values(["sector", "date"]).copy()
    lr = np.log1p(sec["mean_ret"].where(sec["mean_ret"].abs() < cfg.ret_guard))
    g = lr.groupby(sec["sector"], sort=False)
    sec["sec_ret_20d"] = (np.exp(g.transform(
        lambda s: s.rolling(cfg.mkt_trend_window).sum())) - 1) * 100
    sec["sec_ret_60d"] = (np.exp(g.transform(
        lambda s: s.rolling(cfg.mkt_slow_window).sum())) - 1) * 100
    # As-of, same rule as everywhere: the sector's trailing return through D-1.
    sec[["sec_ret_20d", "sec_ret_60d"]] = sec.groupby("sector", sort=False)[
        ["sec_ret_20d", "sec_ret_60d"]].shift(1)

    d = metrics.merge(mkt[["date", "mkt_ret_20d", "mkt_ret_60d"]],
                      on="date", how="left")
    d = d.merge(sec[["sector", "date", "sec_ret_20d", "sec_ret_60d"]],
                on=["sector", "date"], how="left")
    d["rs_20d_vs_mkt"] = d["ret_20d"] - d["mkt_ret_20d"]
    d["rs_60d_vs_mkt"] = d["ret_60d"] - d["mkt_ret_60d"]
    d["rs_20d_vs_sec"] = d["ret_20d"] - d["sec_ret_20d"]
    d["sec_rs_20d_vs_mkt"] = d["sec_ret_20d"] - d["mkt_ret_20d"]
    keep = ["symbol", "date", "sec_ret_20d", "sec_ret_60d", "rs_20d_vs_mkt",
            "rs_60d_vs_mkt", "rs_20d_vs_sec", "sec_rs_20d_vs_mkt"]
    return d[keep]


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def build(cfg: ContextConfig | None = None, save: bool = True,
          verbose: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Both frames: per-session market regime, and per-symbol-day context."""
    cfg = cfg or ContextConfig()
    from . import daily_panel

    bars = pd.read_parquet(config.NORMALIZED_DIR / "daily_bars_adj.parquet",
                           columns=["symbol", "date", "open", "high", "low",
                                    "close"])
    mkt = market_regime(bars, cfg)
    loc = breakout_location(bars, cfg)

    metrics = daily_panel.load(asof_open=True)
    sector = pd.read_parquet(config.NORMALIZED_DIR / "sector_series.parquet")
    rs = relative_strength(
        metrics[["symbol", "date", "sector", "ret_20d", "ret_60d"]], mkt,
        sector, cfg)

    ctx = loc.merge(rs, on=["symbol", "date"], how="left")
    if save:
        config.NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
        ctx.to_parquet(CONTEXT_PATH, index=False)
        mkt.to_parquet(MARKET_PATH, index=False)
    if verbose:
        n = mkt["mkt_regime"].value_counts()
        print(f"  market regime: {len(mkt):,} sessions  "
              + "  ".join(f"{k}={v:,}" for k, v in n.items() if v))
        print(f"  daily context: {len(ctx):,} symbol-days, "
              f"{ctx['symbol'].nunique():,} symbols "
              f"-> {CONTEXT_PATH.relative_to(config.PROJECT_ROOT)}")
    return ctx, mkt


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not CONTEXT_PATH.exists() or not MARKET_PATH.exists():
        raise RuntimeError("daily_context.parquet missing. "
                           "Run: python -m src.cli context")
    return pd.read_parquet(CONTEXT_PATH), pd.read_parquet(MARKET_PATH)
