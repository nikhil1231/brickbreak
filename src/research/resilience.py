"""Resilience during broad-market declines: does holding up predict what comes next?

WHAT IS BEING ASKED (H034)
Identify broad-market down periods **causally** — using only what a person could
have known on the morning in question — then, inside each sector, rank liquid
stocks by how well they held up relative to what their beta and their sector
would have predicted. Test whether a higher resilience rank buys higher
subsequent returns at 1/5/10/20 sessions, in raw, market-excess and
sector-excess terms.

This is a different family from everything in Phases 0-3. It uses no tick data,
no opening window and no screen. It is a daily cross-sectional signal over the
liquid universe, and it is being run as **exploratory alpha research**, not as a
strategy.

THE THREE THINGS THAT MAKE THIS EASY TO GET WRONG

1. **"A decline" is normally identified with hindsight.** Everybody knows where
   the March-2025 bottom was, and a resilience study anchored on it is scoring
   stocks over a window whose end was chosen because the market turned. Here a
   decline is *only ever* a statement about the **trailing** window: at date D
   the window is D-K .. D-1, and the question "was that a decline?" is answered
   from the market's return over exactly those sessions. Nothing about D or
   later enters the definition. The trough is never located.

2. **Resilience is a hair's breadth from short-horizon relative momentum.** The
   window return of a stock minus beta times the window return of the market is
   the residual of a recent-return regression — and recent relative return is a
   well-known signal in its own right, with a well-known sign at short horizons
   (reversal) and the other sign at intermediate ones (momentum). A positive
   result here is worth nothing until it has been shown to be more than
   "the stock that fell least is the stock with the best 20-day RS". `H036`
   is that control and it is run every time.

3. **The beta used to adjust must not come from the window being adjusted.**
   Estimating beta on the decline itself makes the residual mechanically
   orthogonal to the market move and mechanically small; worse, a stock whose
   beta *rose* during the decline gets a residual that mostly measures the beta
   estimate. Betas here are fitted on `beta_window` sessions ending **before**
   the decline window starts, so the adjustment is a genuine prediction of what
   the stock should have done.

TWO ADDITIONAL TRAPS THIS PROJECT HAS ALREADY PAID FOR

- **A snapshot attribute is a lookahead.** `sector` comes from NSE's *current*
  index-membership files, and requiring a stock to have one silently restricts
  the universe to names that were still index members in 2026. That is the same
  defect that `size_tier_rank` was caught on. It is handled by running the
  primary test on the **whole liquid universe with market-beta adjustment
  only** — no sector label needed — and treating the within-sector version as
  the robustness variant, with the selection stated rather than assumed away.
- **Liquidity is not a snapshot here.** `median_tv_20_cr` is the trailing
  20-session median turnover off `screen_metrics_asof`, i.e. already lagged. It
  is used both to define "liquid" and to build the large-cap market proxy, so
  neither depends on what a name became later.

WHY THE MARKET IS EQUAL-WEIGHTED, AND WHY THERE ARE TWO OF THEM
`market_regime.mkt_index` is the equal-weighted mean daily return of every
priced name — roughly 2,800 of them, which is overwhelmingly a small-cap index
and is *not* what "the broad market fell" usually means. A second proxy is
built from the 100 most-traded names by trailing turnover, rebalanced daily,
which is a causal stand-in for a large-cap index. Every headline number is
reported against both; a finding that exists under one and not the other is
fragile and is reported as such.

WHAT "REBOUND-CONDITIONAL" MEANS AND WHY IT IS NOT TRADEABLE
The last question — is the effect stronger when the market subsequently
rebounds — conditions on the future by construction. It is a statement about
the mechanism (are the resilient names simply higher-beta-into-the-recovery?),
not a rule anybody can run. Every rebound-conditional number in here is tagged
`NON_CAUSAL` and must never be quoted as an expectancy.
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from ..core import config
from ..research_data import repository

RET_GUARD = 0.6          # daily moves beyond this are bad prints, not returns
OUT_PATH = config.METADATA_DIR / "resilience.json"


@dataclass(frozen=True)
class ResilienceConfig:
    """Windows and universe bounds. Nothing here is a fitted threshold.

    The decline windows are 10 and 20 sessions because those are the round
    numbers for "a couple of weeks" and "a month", and carrying both means a
    result that exists at one and not the other shows up as fragile instead of
    being reported as real. `beta_window` is 120 sessions — about six months —
    ending `beta_gap` sessions before the decline window opens, so the fit and
    the thing it predicts never overlap.
    """
    decline_windows: tuple[int, ...] = (10, 20)
    beta_window: int = 120
    beta_min_obs: int = 60
    beta_gap: int = 1            # sessions between the beta fit and the window
    beta_clip: tuple[float, float] = (0.0, 3.0)
    horizons: tuple[int, ...] = (1, 5, 10, 20)
    min_turnover_cr: float = 10.0
    min_price: float = 20.0
    min_names_per_day: int = 100
    min_sector_members: int = 8
    n_quantiles: int = 10        # deciles pooled; quintiles used within sector
    largecap_n: int = 100
    # A named decline, for readability and for the rebound split. Reported
    # alongside a *continuous* stratification by trailing-market-return quintile
    # so that no result depends on where this line is drawn.
    decline_cut_pct: float = -3.0


# --------------------------------------------------------------------------
# the panel, in matrix form
# --------------------------------------------------------------------------

@dataclass
class Panel:
    """Dates x symbols matrices. Everything downstream is array arithmetic.

    Held as a wide frame rather than the long panel because every quantity here
    — rolling betas, cross-sectional ranks, equal-weighted benchmarks — is a
    row-wise or column-wise operation on the same grid, and the long form makes
    each of them a groupby that has to be got right separately.
    """
    dates: pd.DatetimeIndex
    symbols: pd.Index
    close: np.ndarray             # adjusted close
    open: np.ndarray              # adjusted open
    logret: np.ndarray            # guarded daily log return
    turnover: np.ndarray          # trailing 20-session median turnover, Rs cr
    sector: np.ndarray            # per-symbol label, object


def load_panel(cfg: ResilienceConfig | None = None) -> tuple[Panel, np.ndarray]:
    """Build the wide panel from the adjusted daily bars and the as-of metrics.

    Series is restricted to EQ and ETFs are dropped, both by symbol rather than
    by row: a name that spent part of its life in BE would otherwise contribute
    a series with holes in it, and a hole in a return series is a fake return
    the moment anything sums across it.
    """
    cfg = cfg or ResilienceConfig()
    bars = repository.daily_bars(
        columns=["symbol", "date", "series", "open", "close", "close_raw"])
    meta = repository.screen_metrics(
        columns=["symbol", "date", "sector", "is_etf", "median_tv_20_cr"])

    etfs = set(meta.loc[meta["is_etf"].fillna(False), "symbol"].unique())
    bars = bars[(bars["series"] == "EQ") & (~bars["symbol"].isin(etfs))]

    dates = pd.DatetimeIndex(sorted(bars["date"].unique()))
    symbols = pd.Index(sorted(bars["symbol"].unique()))

    def wide(df: pd.DataFrame, col: str) -> np.ndarray:
        p = df.pivot_table(index="date", columns="symbol", values=col,
                           aggfunc="last")
        return p.reindex(index=dates, columns=symbols).to_numpy(dtype="float64")

    close = wide(bars, "close")
    open_ = wide(bars, "open")
    close_raw = wide(bars, "close_raw")

    # Guarded log returns. A 10x unadjusted print is not a return; left NaN so
    # that every window sum it would have entered is NaN too.
    with np.errstate(invalid="ignore", divide="ignore"):
        simple = close[1:] / close[:-1] - 1.0
    simple = np.where(np.abs(simple) < RET_GUARD, simple, np.nan)
    logret = np.full_like(close, np.nan)
    logret[1:] = np.log1p(simple)

    meta = meta[meta["symbol"].isin(set(symbols))]
    turnover = wide(meta, "median_tv_20_cr")
    sec = (meta.sort_values("date").groupby("symbol")["sector"].last()
           .reindex(symbols).fillna("UNCLASSIFIED").to_numpy())

    # Price floor uses the *raw* close: what a share actually cost is a fact
    # about tradeability, and the adjusted series restates it.
    close_raw = np.where(np.isfinite(close_raw), close_raw, np.nan)
    return Panel(dates=dates, symbols=symbols, close=close, open=open_,
                 logret=logret, turnover=turnover, sector=sec), close_raw


# --------------------------------------------------------------------------
# market proxies
# --------------------------------------------------------------------------

def market_returns(p: Panel, cfg: ResilienceConfig) -> dict[str, np.ndarray]:
    """Two equal-weighted market log-return series, both causal.

    `broad` is every priced EQ name, which is the definition `market_regime`
    already uses and is small-cap dominated. `large` is the 100 highest
    trailing-turnover names on the day, rebalanced daily — the closest thing to
    a large-cap index that can be built without an index-membership file, and
    unlike one it carries no knowledge of what a name became later.
    """
    # A session with nothing priced yields an all-NaN slice; that is a session
    # with an unknown market return, not an error, and it is voided two lines
    # down by the same count that the warning would be about.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        broad = np.nanmean(p.logret, axis=1)
    broad[np.sum(np.isfinite(p.logret), axis=1) < cfg.min_names_per_day] = np.nan

    # Rank on the trailing turnover known that morning; select, then read the
    # day's return. Selecting on anything from date D would put the day's
    # movers in the day's index.
    tv = p.turnover.copy()
    tv[~np.isfinite(tv)] = -np.inf
    n = min(cfg.largecap_n, tv.shape[1])
    top = np.argpartition(-tv, n - 1, axis=1)[:, :n]
    mask = np.zeros_like(p.logret, dtype=bool)
    np.put_along_axis(mask, top, True, axis=1)
    mask &= np.isfinite(p.turnover)
    lr = np.where(mask, p.logret, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        large = np.nanmean(lr, axis=1)
    large[np.sum(np.isfinite(lr), axis=1) < n // 2] = np.nan
    return {"broad": broad, "large": large}


# --------------------------------------------------------------------------
# rolling pieces
# --------------------------------------------------------------------------

def _roll_sum(a: np.ndarray, n: int, min_frac: float = 0.8) -> np.ndarray:
    """Rolling sum over rows, NaN-tolerant, NaN where too little is present."""
    f = pd.DataFrame(a)
    s = f.rolling(n, min_periods=int(np.ceil(n * min_frac))).sum().to_numpy()
    return s


def window_return(p: Panel, k: int) -> np.ndarray:
    """Cumulative log return over the k sessions ending D-1, per (date, symbol).

    Built from the guarded daily returns rather than a close-to-close ratio so
    that one bad print voids the window instead of silently defining it.
    """
    return np.roll(_roll_sum(p.logret, k), 1, axis=0) * _nan_head(p.logret, 1)


def _nan_head(a: np.ndarray, n: int) -> np.ndarray:
    """Multiplier that voids the first n rows — `np.roll` wraps, and a wrapped
    row would put the end of the sample at the start of it."""
    m = np.ones(a.shape[0])
    m[:n] = np.nan
    return m[:, None]


def rolling_beta(p: Panel, mkt: np.ndarray, cfg: ResilienceConfig,
                 offset: int) -> np.ndarray:
    """OLS beta of each stock on the market over `beta_window` sessions ending
    `offset` sessions before date D.

    `offset = k + beta_gap` puts the whole fit strictly before the decline
    window, which is the point: a beta fitted on the decline is a description of
    the decline, and subtracting it removes the very thing being measured.

    Pairwise-complete by construction — a day on which either series is missing
    contributes to neither the sums nor the count — because dropping it from one
    and not the other biases the covariance toward zero.
    """
    b = cfg.beta_window
    x = mkt[:, None] * np.ones((1, p.logret.shape[1]))
    y = p.logret
    ok = np.isfinite(x) & np.isfinite(y)
    xf = np.where(ok, x, 0.0)
    yf = np.where(ok, y, 0.0)

    n = _roll_sum(ok.astype(float), b, min_frac=0.0)
    sx = _roll_sum(xf, b, min_frac=0.0)
    sy = _roll_sum(yf, b, min_frac=0.0)
    sxx = _roll_sum(xf * xf, b, min_frac=0.0)
    sxy = _roll_sum(xf * yf, b, min_frac=0.0)

    den = n * sxx - sx * sx
    with np.errstate(invalid="ignore", divide="ignore"):
        beta = (n * sxy - sx * sy) / den
    beta[(n < cfg.beta_min_obs) | (den <= 0)] = np.nan
    beta = np.clip(beta, *cfg.beta_clip)
    return np.roll(beta, offset, axis=0) * _nan_head(beta, offset)


# --------------------------------------------------------------------------
# forward outcomes
# --------------------------------------------------------------------------

def forward_returns(p: Panel, h: int) -> tuple[np.ndarray, np.ndarray]:
    """Two forward simple returns for a h-session hold starting at date D.

    `entry_open` buys date D's opening print — the one date-D price knowable
    before the decision has to be acted on — and sells the close of the h-th
    session. `skip_day` buys date D's *close* instead and sells h sessions
    later; the pair exists because a one-day reversal signal measured from the
    open picks up the bid-ask bounce and the overnight gap, and if the whole
    effect disappears when the first day is skipped then that is what it was.
    """
    T = p.close.shape[0]
    exit_open_entry = np.full_like(p.close, np.nan)
    exit_skip = np.full_like(p.close, np.nan)
    j = h - 1
    if T - j > 0:
        exit_open_entry[:T - j] = p.close[j:]
    if T - h > 0:
        exit_skip[:T - h] = p.close[h:]
    with np.errstate(invalid="ignore", divide="ignore"):
        r_open = exit_open_entry / p.open - 1.0
        r_skip = exit_skip / p.close - 1.0
    guard = h * RET_GUARD + RET_GUARD
    r_open = np.where(np.abs(r_open) < guard, r_open, np.nan)
    r_skip = np.where(np.abs(r_skip) < guard, r_skip, np.nan)
    return r_open * 100.0, r_skip * 100.0


# --------------------------------------------------------------------------
# the observation frame
# --------------------------------------------------------------------------

def build(cfg: ResilienceConfig | None = None, k: int = 20,
          mkt_key: str = "broad", verbose: bool = True,
          panel: tuple[Panel, np.ndarray] | None = None) -> pd.DataFrame:
    """One row per (eligible symbol, date) with resilience, controls, outcomes.

    Eligibility is decided entirely on trailing quantities: turnover, price, a
    complete decline window and a fitted beta. No row is admitted or excluded on
    anything dated D or later, which is what makes the decline stratification
    below a statement about what was knowable rather than about what happened.
    """
    cfg = cfg or ResilienceConfig()
    # `panel` is injectable so the lookahead test can build a synthetic grid,
    # append later sessions to it and require every signal on date D to be
    # bit-identical. That test is the whole reason this argument exists.
    p, close_raw = panel if panel is not None else load_panel(cfg)
    mkts = market_returns(p, cfg)
    mkt = mkts[mkt_key]

    r_win = window_return(p, k)
    rm_win = np.roll(_roll_sum(mkt[:, None], k), 1, axis=0)[:, 0] * _nan_head(
        mkt[:, None], 1)[:, 0]
    beta = rolling_beta(p, mkt, cfg, offset=k + cfg.beta_gap)

    # The residual. Log space for the window (returns compound), converted to
    # percent for reading.
    resid = (r_win - beta * rm_win[:, None]) * 100.0
    raw_win = r_win * 100.0

    # Pre-window momentum: the control that decides whether any of this is more
    # than recent relative strength. Measured over the 60 sessions ending where
    # the decline window opens, so it and the resilience score share no session.
    mom_pre = (np.roll(_roll_sum(p.logret, 60), k + 1, axis=0)
               * _nan_head(p.logret, k + 1)) * 100.0
    mom_pre_mkt = (np.roll(_roll_sum(mkt[:, None], 60), k + 1, axis=0)[:, 0]
                   * _nan_head(mkt[:, None], k + 1)[:, 0]) * 100.0
    mom_pre_rel = mom_pre - mom_pre_mkt[:, None]

    # Trailing volatility over the same pre-window sessions the beta is fitted
    # on. The control for "beaten-down names are simply volatile names": a
    # cross-section sorted on a drawdown is also sorted on volatility, and the
    # two make the same prediction about what bounces.
    var_pre = _roll_sum(p.logret ** 2, cfg.beta_window, min_frac=0.5)
    cnt_pre = _roll_sum(np.isfinite(p.logret).astype(float), cfg.beta_window,
                        min_frac=0.5)
    with np.errstate(invalid="ignore", divide="ignore"):
        vol_pre = np.sqrt(var_pre / cnt_pre) * np.sqrt(252) * 100.0
    off = k + cfg.beta_gap
    vol_pre = np.roll(vol_pre, off, axis=0) * _nan_head(vol_pre, off)

    tv_prev = p.turnover
    px_prev = np.roll(close_raw, 1, axis=0) * _nan_head(close_raw, 1)

    eligible = (
        np.isfinite(resid) & np.isfinite(beta) & np.isfinite(p.open)
        & (p.open > 0) & np.isfinite(tv_prev) & (tv_prev >= cfg.min_turnover_cr)
        & np.isfinite(px_prev) & (px_prev >= cfg.min_price)
    )
    ti, si = np.nonzero(eligible)
    if verbose:
        print(f"  eligible rows: {len(ti):,} over {len(np.unique(ti)):,} sessions")

    d = pd.DataFrame({
        "date": p.dates.to_numpy()[ti],
        "symbol": p.symbols.to_numpy()[si],
        "sector": p.sector[si],
        "resid_pct": resid[ti, si],
        "raw_win_pct": raw_win[ti, si],
        "beta": beta[ti, si],
        "mom_pre_rel_pct": mom_pre_rel[ti, si],
        "turnover_cr": tv_prev[ti, si],
        "vol_pre_pct": vol_pre[ti, si],
        "mkt_win_pct": (rm_win * 100.0)[ti],
    })
    for h in cfg.horizons:
        r_open, r_skip = forward_returns(p, h)
        d[f"fwd_{h}"] = r_open[ti, si]
        d[f"fwdskip_{h}"] = r_skip[ti, si]

    d = _attach_benchmarks(d, cfg)
    d = _attach_ranks(d, cfg)
    d.attrs["k"] = k
    d.attrs["mkt_key"] = mkt_key
    return d


def _attach_benchmarks(d: pd.DataFrame, cfg: ResilienceConfig) -> pd.DataFrame:
    """Market and sector excess returns, both equal-weighted over the *eligible*
    universe rather than over everything that traded.

    The benchmark has to be the set the signal picks from. Scoring a long-short
    inside the liquid universe against an index of 2,800 microcaps measures the
    size tilt of the universe, not the ranking.
    """
    for h in cfg.horizons:
        for pre in ("fwd", "fwdskip"):
            col = f"{pre}_{h}"
            mkt = d.groupby("date")[col].transform("mean")
            sec = d.groupby(["date", "sector"], observed=True)[col].transform("mean")
            n_sec = d.groupby(["date", "sector"], observed=True)[col].transform("count")
            d[f"{pre}_xs_mkt_{h}"] = d[col] - mkt
            d[f"{pre}_xs_sec_{h}"] = (d[col] - sec).where(
                n_sec >= cfg.min_sector_members)
            # Beta-adjusted: the check on whether "resilient" is just "low beta
            # in a market that went back up".
            d[f"{pre}_xs_beta_{h}"] = d[col] - d["beta"] * mkt
    return d


def _rank_pct(s: pd.Series) -> pd.Series:
    return s.rank(pct=True, method="average")


def _attach_ranks(d: pd.DataFrame, cfg: ResilienceConfig) -> pd.DataFrame:
    """Cross-sectional ranks. Three of them, and the differences matter.

    `dec_all` ranks the whole day's liquid universe on the market-adjusted
    residual — the primary, because it needs no sector label and therefore no
    index-membership snapshot. `dec_secneu` ranks on the residual after
    subtracting the sector's own median residual that day, which is the
    sector-neutral version of the same thing. `q_sector` is the literal reading
    of the question — quintiles *inside* each sector — and is thinner by
    construction, which is why it is quintiles and not deciles.
    """
    g = d.groupby("date")["resid_pct"]
    d["pct_all"] = g.transform(_rank_pct)
    d["dec_all"] = np.ceil(d["pct_all"] * cfg.n_quantiles).clip(1, cfg.n_quantiles)

    sec_med = d.groupby(["date", "sector"], observed=True)["resid_pct"].transform("median")
    n_sec = d.groupby(["date", "sector"], observed=True)["resid_pct"].transform("count")
    d["resid_secneu_pct"] = (d["resid_pct"] - sec_med).where(
        (n_sec >= cfg.min_sector_members) & (d["sector"] != "UNCLASSIFIED"))
    gs = d.groupby("date")["resid_secneu_pct"]
    d["pct_secneu"] = gs.transform(_rank_pct)
    d["dec_secneu"] = np.ceil(d["pct_secneu"] * cfg.n_quantiles).clip(1, cfg.n_quantiles)

    within = d.groupby(["date", "sector"], observed=True)["resid_pct"].transform(_rank_pct)
    d["q_sector"] = np.ceil(within.where(
        (n_sec >= cfg.min_sector_members) & (d["sector"] != "UNCLASSIFIED")) * 5
    ).clip(1, 5)

    # The naive comparison: rank on the plain window return with no beta or
    # sector adjustment at all. If this does the same job, the adjustment is
    # decoration.
    d["dec_raw"] = np.ceil(d.groupby("date")["raw_win_pct"].transform(_rank_pct)
                           * cfg.n_quantiles).clip(1, cfg.n_quantiles)
    return d


# --------------------------------------------------------------------------
# decline stratification
# --------------------------------------------------------------------------

def stratify(d: pd.DataFrame, cfg: ResilienceConfig) -> pd.DataFrame:
    """Label each session by what the market had *already* done, two ways.

    `mkt_quintile` is the continuous version — sessions cut at quintiles of the
    trailing market window return over the sample — and it is the primary,
    because it shows the whole shape of the relationship instead of one side of
    a line somebody drew. `is_decline` is the named binary at a round cut, kept
    for readability and because the rebound split needs a subset to split.
    """
    per_date = d.groupby("date")["mkt_win_pct"].first()
    q = pd.qcut(per_date, 5, labels=[1, 2, 3, 4, 5]).astype(int)
    d = d.merge(q.rename("mkt_quintile"), left_on="date", right_index=True,
                how="left")
    d["is_decline"] = d["mkt_win_pct"] < cfg.decline_cut_pct
    return d


# --------------------------------------------------------------------------
# inference
# --------------------------------------------------------------------------

def nw_tstat(x: pd.Series, lag: int) -> dict:
    """Mean of a daily portfolio series with a Newey-West standard error.

    The portfolio is re-formed every session and held `h` of them, so
    consecutive daily observations share `h-1` days of the same trade. Treating
    them as independent overstates the t by roughly sqrt(h) — the same class of
    mistake as H016, arriving through the time axis instead of the
    cross-section. `lag = h` is the standard choice for an h-period overlap.
    """
    x = x.dropna()
    n = len(x)
    if n < 10:
        return {"n": int(n), "mean": float("nan"), "t": float("nan")}
    e = (x - x.mean()).to_numpy()
    s = float(e @ e) / n
    for L in range(1, min(lag, n - 1) + 1):
        w = 1.0 - L / (lag + 1.0)
        s += 2.0 * w * float(e[L:] @ e[:-L]) / n
    s = max(s, 1e-18)
    se = np.sqrt(s / n)
    return {"n": int(n), "mean": float(x.mean()), "t": float(x.mean() / se),
            "naive_t": float(x.mean() / (x.std(ddof=1) / np.sqrt(n)))}


def _spearman(x: pd.Series, y: pd.Series) -> float:
    """Spearman as rank-then-Pearson. Written out because scipy is not a
    dependency of this project and adding one for a rank correlation is a poor
    trade; average ranks on ties make this identical to the scipy result."""
    if len(x) < 3:
        return float("nan")
    xr, yr = x.rank(), y.rank()
    sx, sy = xr.std(ddof=0), yr.std(ddof=0)
    if sx == 0 or sy == 0:
        return float("nan")
    return float(((xr - xr.mean()) * (yr - yr.mean())).mean() / (sx * sy))


def quantile_table(d: pd.DataFrame, rank_col: str, y_col: str,
                   n_q: int) -> pd.DataFrame:
    """Mean outcome per rank bucket, plus the per-date equal-weighted mean.

    Two means, and they are not the same number: the pooled mean weights a
    session with 700 eligible names 700 times as heavily as one with 400, which
    is not how a portfolio experiences the sample. The per-date mean is the one
    quoted; the pooled one is kept so the difference is visible.
    """
    g = d.groupby(rank_col, observed=True)[y_col]
    per_date = (d.groupby([rank_col, "date"], observed=True)[y_col].mean()
                .groupby(level=0).mean())
    out = pd.DataFrame({
        "n": g.count(), "pooled_mean": g.mean(), "mean": per_date,
    })
    return out.reindex(range(1, n_q + 1)).dropna(how="all")


def monotonicity(tbl: pd.DataFrame) -> dict:
    """How ordered the bucket means actually are.

    A long-short spread can be large with the eight buckets in between in any
    order at all, which is what an outlier bucket looks like. Spearman over the
    bucket means and a count of adjacent inversions separate "the signal is a
    ranking" from "two extreme cells disagree".
    """
    m = tbl["mean"].dropna()
    if len(m) < 3:
        return {"spearman": float("nan"), "inversions": None}
    rho = _spearman(pd.Series(m.index, index=m.index, dtype=float), m)
    diffs = np.diff(m.to_numpy())
    return {"spearman": rho,
            "inversions": int((diffs < 0).sum()),
            "n_steps": int(len(diffs)),
            "top_minus_bottom": float(m.iloc[-1] - m.iloc[0])}


def long_short(d: pd.DataFrame, rank_col: str, y_col: str, n_q: int,
               lag: int) -> dict:
    """Per-session top-minus-bottom bucket spread, Newey-West across sessions."""
    top = d[d[rank_col] == n_q].groupby("date")[y_col].mean()
    bot = d[d[rank_col] == 1].groupby("date")[y_col].mean()
    s = (top - bot).dropna()
    out = nw_tstat(s, lag)
    out["mean_top"] = float(top.mean())
    out["mean_bottom"] = float(bot.mean())
    return out


def rank_ic(d: pd.DataFrame, score_col: str, y_col: str, lag: int) -> dict:
    """Average per-session Spearman between the score and the outcome.

    Reported beside the decile spread because they fail differently: the IC is
    driven by the whole cross-section and is robust to a single wild bucket,
    while the spread is what a top-and-bottom book would actually earn.
    """
    def _ic(g: pd.DataFrame) -> float:
        x, y = g[score_col], g[y_col]
        m = x.notna() & y.notna()
        if m.sum() < 30:
            return np.nan
        return _spearman(x[m], y[m])
    ics = d.groupby("date")[[score_col, y_col]].apply(_ic)
    out = nw_tstat(ics, lag)
    out["hit_rate_positive"] = float((ics.dropna() > 0).mean())
    return out


# --------------------------------------------------------------------------
# the fence, and the driver
# --------------------------------------------------------------------------

def exploration_only(d: pd.DataFrame) -> pd.DataFrame:
    """Cut the observation frame down to the exploration window and prove it.

    The rows *before* 2023-08-21 are needed as inputs — a beta wants 120
    sessions and a 52-week statistic wants 250 — but no row dated before the
    fence may be scored, ranked or reported. Same split `explore.py` enforces,
    reached the same way `explore.attach_outcomes` reaches it: fence the frame
    of observations, read the full history behind it.

    Reading the 2020-2023 window is therefore an explicit act — you have to not
    call this — which is the point. It is also, since H033, a **spent** holdout:
    it has been opened once against a different family, so a result found there
    is weaker than a clean out-of-sample test and must be labelled as such.
    """
    from . import explore
    out = d[(d["date"] >= explore.EXPLORE_START)
            & (d["date"] <= explore.EXPLORE_END)].copy()
    explore.fence(out, "resilience frame")
    return out


def summarise(d: pd.DataFrame, cfg: ResilienceConfig, k: int, mkt_key: str
              ) -> dict:
    """Every headline number, in one dict, for `data/metadata/resilience.json`.

    Written to disk rather than printed because the write-up quotes them and a
    number in a write-up that cannot be traced back to a run is a number
    nobody can check.
    """
    res: dict = {"k": k, "market": mkt_key, "config": asdict(cfg),
                 "n_rows": int(len(d)), "n_sessions": int(d["date"].nunique()),
                 "date_min": str(d["date"].min().date()),
                 "date_max": str(d["date"].max().date()),
                 "strata": {}, "decline": {}}
    for q in sorted(d["mkt_quintile"].dropna().unique()):
        s = d[d["mkt_quintile"] == q]
        cell = {"n_sessions": int(s["date"].nunique()),
                "trailing_mkt_pct": [float(s["mkt_win_pct"].min()),
                                     float(s["mkt_win_pct"].max())]}
        for h in cfg.horizons:
            y = f"fwd_xs_mkt_{h}"
            ls = long_short(s, "dec_all", y, cfg.n_quantiles, lag=h)
            mono = monotonicity(quantile_table(s, "dec_all", y, cfg.n_quantiles))
            cell[f"h{h}"] = {"ls": ls["mean"], "t": ls["t"],
                             "spearman": mono["spearman"]}
        res["strata"][int(q)] = cell

    dec = d[d["mkt_quintile"] == 1]
    for h in cfg.horizons:
        block = {}
        for rank, y in (("dec_all", f"fwd_xs_mkt_{h}"),
                        ("dec_all", f"fwd_xs_beta_{h}"),
                        ("dec_all", f"fwdskip_xs_mkt_{h}"),
                        ("dec_secneu", f"fwd_xs_sec_{h}"),
                        ("q_sector", f"fwd_xs_sec_{h}"),
                        ("dec_raw", f"fwd_xs_mkt_{h}")):
            n_q = 5 if rank == "q_sector" else cfg.n_quantiles
            tbl = quantile_table(dec, rank, y, n_q)
            ls = long_short(dec, rank, y, n_q, lag=h)
            block[f"{rank}|{y}"] = {
                "buckets": [float(v) for v in tbl["mean"]],
                "ls": ls["mean"], "t": ls["t"], "n_sessions": ls["n"],
                **monotonicity(tbl)}
        block["rank_ic"] = rank_ic(dec, "resid_pct", f"fwd_xs_mkt_{h}", lag=h)
        res["decline"][f"h{h}"] = block
    return res


def run(cfg: ResilienceConfig | None = None, verbose: bool = True) -> dict:
    """Build every configuration, summarise it, write the JSON. H034/H035/H036."""
    cfg = cfg or ResilienceConfig()
    out = {}
    for k in cfg.decline_windows:
        for mkt_key in ("broad", "large"):
            d = exploration_only(stratify(
                build(cfg, k=k, mkt_key=mkt_key, verbose=verbose), cfg))
            out[f"k{k}_{mkt_key}"] = summarise(d, cfg, k, mkt_key)
            if verbose:
                dec = out[f"k{k}_{mkt_key}"]["decline"]["h5"]["dec_all|fwd_xs_mkt_5"]
                print(f"  k={k} {mkt_key}: decline-stratum h=5 "
                      f"LS={dec['ls']:+.3f}% t={dec['t']:+.2f}")
    OUT_PATH.write_text(json.dumps(out, indent=2, default=float))
    if verbose:
        print(f"  wrote {OUT_PATH}")
    return out


if __name__ == "__main__":       # pragma: no cover
    run()


# --------------------------------------------------------------------------
# H036: separating "held up better than beta predicted" from "fell less"
# --------------------------------------------------------------------------

def orthogonal_score(d: pd.DataFrame, level: bool = True) -> pd.Series:
    """The part of the resilience residual that the raw drawdown cannot explain.

    Fitted cross-sectionally, one regression per session, because that is the
    comparison being made: among the names available on this morning, is
    "held up better than its beta predicted" saying anything beyond "fell less"?

    **There is an algebraic answer and the empirical one should match it.**
    Within a single date, `resid_i = r_i - beta_i * r_mkt` and `r_mkt` is a
    constant. Projecting that on `r_i` leaves `-r_mkt` times the part of
    `beta_i` that `r_i` does not explain. So the orthogonalised score *is*
    beta — residualised against the drawdown and, since `r_mkt < 0` in a
    decline, with the sign flipped. `analysis.orthogonal_is_beta` checks that
    correspondence rather than asserting it, because an identity that holds on
    paper and not in the frame means something else is going on.

    `level=False` runs the same projection on cross-sectional percentile ranks,
    which breaks the identity but is robust to the tail of the drawdown
    distribution. Both are reported; a conclusion that needs one and not the
    other is not a conclusion.
    """
    out = pd.Series(np.nan, index=d.index, name="orth")
    # Written as an explicit loop rather than `groupby.apply`: apply returning a
    # Series the same length as its group is ambiguous to pandas, which
    # broadcasts it into a frame when there is only one group. That happens on a
    # degenerate cross-section, which is exactly the case a caller is least
    # likely to notice.
    for _, g in d.groupby("date", sort=False):
        y, x = g["resid_pct"], g["raw_win_pct"]
        if not level:
            y, x = y.rank(pct=True), x.rank(pct=True)
        m = y.notna() & x.notna()
        if int(m.sum()) < 30 or x[m].std() == 0:
            continue
        X = np.column_stack([np.ones(int(m.sum())), x[m].to_numpy()])
        b = np.linalg.lstsq(X, y[m].to_numpy(), rcond=None)[0]
        out.loc[g.index[m.to_numpy()]] = y[m].to_numpy() - X @ b
    return out


# --------------------------------------------------------------------------
# the frozen test — written before the 2020-2023 window is opened
# --------------------------------------------------------------------------

FROZEN_PATH = config.METADATA_DIR / "resilience_frozen.json"
SEMI_STALE_PATH = config.METADATA_DIR / "resilience_semi_stale.json"

# The window. It starts where the panel first supports a full score (a 120-
# session beta fit plus a 10-session decline window, off a 2020-01-01 archive)
# and stops `max(horizons)` sessions before the exploration window opens, so no
# trade in this test settles on a price from the window that generated the
# hypothesis. The COVID crash itself is *not* in it — there is no history in
# front of it to fit a beta on — and the write-up must say so rather than
# implying this window contains the biggest decline in the archive.
SEMI_STALE_END = pd.Timestamp("2023-07-21")

PASS_CRITERION = {
    "what_is_being_tested": (
        "H037: the reversal gradient found in H034 — inside a causally "
        "identified decline the LEAST resilient decile outperforms — replicates "
        "on 2020-04 -> 2023-07. Note the sign: the original hypothesis (H034) is "
        "already rejected; this tests the thing that replaced it."
    ),
    "primary": {
        "config": "k=10, market=broad, rank=dec_all, outcome=fwd_xs_mkt",
        "stratum": "bottom quintile of the trailing 10-session market return, "
                   "quintiles computed inside the 2020-2023 window itself",
        "horizons": [5, 10],
        "pass": "both spreads negative AND at least one with Newey-West |t| >= 2",
        "partial": "both spreads negative but neither reaches |t| >= 2",
        "fail": "anything else",
    },
    "gradient": {
        "requirement": "the spread in the deepest depth bin (trailing 10-session "
                       "market return below -6%) is more negative than in the "
                       "-3%..-1% bin, at h=5 and h=10",
        "role": "a second necessary condition for PASS; a spread without the "
                "depth gradient is not the finding H034 reported",
    },
    "recorded_but_not_gating": [
        "the H038 decomposition: drawdown-orthogonal-to-beta should keep the "
        "negative gradient, beta-orthogonal-to-drawdown the positive one",
        "the within-sector quintile rank-IC on sector-excess returns",
        "the cost-adjusted long-only decile-1 excess at 0.40% round trip",
        "the k=20 and large-cap-market variants",
    ],
    "why_this_window_is_weaker_than_a_holdout": (
        "2020-2023 was opened once already, against the opening-window family "
        "(H033). Nothing about that family's result informs a cross-sectional "
        "reversal signal, but the window is no longer virgin and the result "
        "must be labelled SEMI-STALE, never 'out of sample'."
    ),
    "run_once": True,
}


def _spec_hash(payload: dict) -> str:
    """A fingerprint of the frozen spec, so an edit between freezing and running
    cannot hide. Same device as `family._rules_hash`, same reason."""
    import hashlib
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def freeze(path=FROZEN_PATH) -> dict:
    """Write the spec and the pass criterion down before the window is opened.

    Everything the replay needs is in here: the config, the score definitions,
    the stratum rule, the horizons and the bar. If any of it has to be decided
    after the result is seen, the test was never a test.
    """
    cfg = ResilienceConfig()
    spec = {
        "config": asdict(cfg),
        "scores": {
            "resid_pct": "window log return minus pre-window OLS beta times the "
                         "market's window log return, in percent",
            "raw_win_pct": "window log return, in percent",
            "orth_beta": "resid_pct projected off raw_win_pct within the "
                         "session; algebraically equal to -r_mkt times beta "
                         "residualised on the drawdown",
            "orth_draw": "raw_win_pct projected off resid_pct within the session",
        },
        "window": {"end": str(SEMI_STALE_END.date()),
                   "purge_sessions": max(cfg.horizons),
                   "note": "starts wherever the panel first supports a full score"},
        "pass_criterion": PASS_CRITERION,
        "frozen_at": "2026-08-20",
        "hypotheses": ["H034", "H035", "H036", "H037", "H038"],
    }
    spec["spec_hash"] = _spec_hash(spec)
    path.write_text(json.dumps(spec, indent=2, default=str))
    return spec


def semi_stale_window(d: pd.DataFrame) -> pd.DataFrame:
    """Everything from the start of the panel to the purged 2023 cut."""
    return d[d["date"] <= SEMI_STALE_END].copy()


def _depth_bins(d: pd.DataFrame) -> pd.Series:
    """Round, pre-declared depth bands on the trailing market window return."""
    return pd.cut(d["mkt_win_pct"], [-np.inf, -6, -3, -1, 1, np.inf],
                  labels=["<-6", "-6..-3", "-3..-1", "-1..1", ">1"])


def semi_stale(verbose: bool = True, path=SEMI_STALE_PATH) -> dict:
    """Replay the frozen spec once on 2020-04 -> 2023-07. **SEMI-STALE, not OOS.**

    The window was opened once before, against the opening-window family
    (H033). Nothing that test learned bears on a cross-sectional reversal
    signal, so this is worth more than another pass over 2023-2026 — but it is
    not a virgin holdout and the verdict must never be quoted as one.

    The frozen spec is re-hashed and compared before anything is read, so an
    edit made after freezing and before running is loud rather than silent.
    """
    frozen = json.loads(FROZEN_PATH.read_text())
    stored = frozen.pop("spec_hash")
    if _spec_hash(frozen) != stored:
        raise RuntimeError(
            f"the frozen spec no longer hashes to what was recorded "
            f"({_spec_hash(frozen)} vs {stored}). Something was edited between "
            f"freezing and running; the test is void.")
    frozen["spec_hash"] = stored
    cfg = ResilienceConfig(**{**asdict(ResilienceConfig()),
                             **{k: tuple(v) if isinstance(v, list) else v
                                for k, v in frozen["config"].items()}})

    out: dict = {"spec_hash": stored, "label": "SEMI-STALE",
                 "pass_criterion": frozen["pass_criterion"], "runs": {}}
    for k in cfg.decline_windows:
        for mkt_key in ("broad", "large"):
            d = semi_stale_window(stratify(
                build(cfg, k=k, mkt_key=mkt_key, verbose=False), cfg))
            # Strata are recut inside this window: importing a boundary from
            # 2023-2026 would import a number that came out of the exploration.
            per = d.groupby("date")["mkt_win_pct"].first()
            q = pd.qcut(per, 5, labels=[1, 2, 3, 4, 5]).astype(int)
            d["mkt_quintile"] = d["date"].map(q)
            d["depth"] = _depth_bins(d)
            out["runs"][f"k{k}_{mkt_key}"] = _semi_stale_block(d, cfg, k, mkt_key)
    out["verdict"], out["why"] = _semi_stale_verdict(out)
    path.write_text(json.dumps(out, indent=2, default=float))
    if verbose:
        print(f"\n  VERDICT: {out['verdict']}\n  {out['why']}\n  wrote {path}")
    return out


def _semi_stale_block(d: pd.DataFrame, cfg: ResilienceConfig, k: int,
                      mkt_key: str) -> dict:
    dec = d[d["mkt_quintile"] == 1]
    blk = {"k": k, "market": mkt_key,
           "date_min": str(d["date"].min().date()),
           "date_max": str(d["date"].max().date()),
           "n_sessions": int(d["date"].nunique()),
           "n_decline_sessions": int(dec["date"].nunique()),
           "decline_boundary_pct": float(dec["mkt_win_pct"].max()),
           "primary": {}, "depth": {}, "decomposition": {}, "sector": {}}
    for h in cfg.horizons:
        y = f"fwd_xs_mkt_{h}"
        ls = long_short(dec, "dec_all", y, cfg.n_quantiles, lag=h)
        tbl = quantile_table(dec, "dec_all", y, cfg.n_quantiles)
        blk["primary"][f"h{h}"] = {
            "ls": ls["mean"], "t": ls["t"], "n_sessions": ls["n"],
            "buckets": [float(v) for v in tbl["mean"]],
            **monotonicity(tbl),
            "long_only_d1_excess": float(tbl["mean"].iloc[0]),
            "long_only_d1_net_of_40bp": float(tbl["mean"].iloc[0] - 0.40),
        }
        sq = long_short(dec, "q_sector", f"fwd_xs_sec_{h}", 5, lag=h)
        blk["sector"][f"h{h}"] = {
            "q5_minus_q1": sq["mean"], "t": sq["t"],
            "rank_ic": rank_ic(dec, "resid_pct", f"fwd_xs_sec_{h}", lag=h)}
    for band in d["depth"].cat.categories:
        s = d[d["depth"] == band]
        if s["date"].nunique() < 20:
            continue
        blk["depth"][band] = {
            f"h{h}": {**{kk: long_short(s, "dec_all", f"fwd_xs_mkt_{h}",
                                        cfg.n_quantiles, lag=h)[kk]
                         for kk in ("mean", "t")},
                      "n_sessions": int(s["date"].nunique())}
            for h in (5, 10)}

    # H038: the two halves the exploration window said the score is made of.
    dec = dec.copy()
    dec["orth_beta"] = orthogonal_score(dec, level=True)
    def _flip(g: pd.DataFrame) -> pd.Series:
        y, x = g["raw_win_pct"], g["resid_pct"]
        m = y.notna() & x.notna()
        if m.sum() < 30:
            return pd.Series(np.nan, index=g.index)
        X = np.column_stack([np.ones(int(m.sum())), x[m].to_numpy()])
        o = pd.Series(np.nan, index=g.index)
        o[m] = y[m].to_numpy() - X @ np.linalg.lstsq(X, y[m].to_numpy(),
                                                     rcond=None)[0]
        return o
    dec["orth_draw"] = dec.groupby("date", group_keys=False)[
        ["raw_win_pct", "resid_pct"]].apply(_flip)
    for name in ("orth_beta", "orth_draw", "raw_win_pct", "beta"):
        dec["_q"] = np.ceil(dec.groupby("date")[name].transform(
            lambda s: s.rank(pct=True)) * cfg.n_quantiles).clip(1, cfg.n_quantiles)
        blk["decomposition"][name] = {}
        for h in (5, 10, 20):
            y = f"fwd_xs_mkt_{h}"
            ls = long_short(dec, "_q", y, cfg.n_quantiles, lag=h)
            blk["decomposition"][name][f"h{h}"] = {
                "ls": ls["mean"], "t": ls["t"],
                "spearman": monotonicity(
                    quantile_table(dec, "_q", y, cfg.n_quantiles))["spearman"]}
    return blk


def _semi_stale_verdict(out: dict) -> tuple[str, str]:
    """Apply the bar exactly as it was frozen, with no discretion left in it."""
    p = out["runs"]["k10_broad"]["primary"]
    d = out["runs"]["k10_broad"]["depth"]
    both_neg = p["h5"]["ls"] < 0 and p["h10"]["ls"] < 0
    strong = max(abs(p["h5"]["t"]), abs(p["h10"]["t"])) >= 2.0
    grad = all(d.get("<-6", {}).get(f"h{h}", {}).get("mean", 0)
               < d.get("-3..-1", {}).get(f"h{h}", {}).get("mean", 0)
               for h in (5, 10)) if "<-6" in d and "-3..-1" in d else False
    if both_neg and strong and grad:
        return "PASS", ("The reversal gradient replicates: both horizons "
                        "negative, at least one at |t| >= 2, and the depth "
                        "gradient preserved.")
    if both_neg and grad:
        return "PARTIAL", ("Both horizons negative and the depth gradient is "
                           "preserved, but neither horizon reaches |t| >= 2.")
    if both_neg:
        return "PARTIAL", ("Both horizons negative, but the depth gradient is "
                           "not preserved, so what replicates is not the "
                           "finding H034 reported.")
    return "FAIL", "The reversal gradient does not replicate on this window."
