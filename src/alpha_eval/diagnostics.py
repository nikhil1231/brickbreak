"""Standard statistical alpha diagnostics.

Evaluates the predictive content, quantile profiles, signal mechanics, and
subperiod/regime conditioning of any cross-sectional signal.

CRITICAL INVARIANTS:
1. Clustered standard errors: cross-sectional observations within a session
   share market shocks. Clustered t-statistics (CR0 by session date) are
   reported alongside naive ones.
2. Monotonicity: quantiles are formed within each session, and monotonicity
   measures whether returns step upward orderly from Q1 to Q5.
3. Decision units: every effect is reported in basis points (bps) per trade
   and win rate lift beside t-statistics.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# overlapping forward windows
# ---------------------------------------------------------------------------

_HORIZON_RE = re.compile(r"(\d+)\s*d")


def horizon_from_column(name: str, default: int = 1) -> int:
    """Read the forward horizon out of a label column name.

    `fwd_ret_20d_pct` -> 20. Callers may always pass `horizon=` explicitly;
    this exists so the common path cannot forget.
    """
    m = _HORIZON_RE.search(str(name))
    return int(m.group(1)) if m else default


def _hac_var_of_mean(x: np.ndarray, lags: int) -> float:
    """Variance of the mean of a serially dependent series (Hansen-Hodrick).

    WHY THIS IS NOT OPTIONAL
    A forward return over [t, t+h] shares h-1 days with the one starting at
    t+1, so a daily IC series (or a daily long-short spread) is autocorrelated
    by construction and `std/sqrt(T)` is far too small. Measured on a null
    where the signal has *zero* predictive power, at h=20 the uncorrected
    t-statistic had a standard deviation of 5.1 instead of 1 and rejected at
    |t|>2 in 68% of runs.

    This is a different failure from H016. Clustering by session fixes the
    cross-sectional correlation *within* a day; this fixes the serial overlap
    *across* days. A signal needs both.

    WHY A RECTANGULAR KERNEL AND NOT BARTLETT
    Overlapping h-day returns give the IC series an MA(h-1) structure: the
    true autocovariances past lag h-1 are zero, and the ones inside it are
    large. Bartlett's taper shrinks exactly the terms that carry the
    correction. Measured over 150 null replications:

        h=20   Bartlett(h-1)  std 1.34, 12.0% rejected
               Bartlett(2h-2) std 1.26, 10.7% rejected
               rectangular    std 1.13,  8.0% rejected   <- used

    Against 68% rejected with no correction at all.

    Rectangular is not positive semi-definite, so a negative estimate falls
    back to Bartlett at twice the bandwidth.

    WHAT IS STILL NOT FIXED
    Residual over-rejection at long horizons is real: measured at 8-13% across
    replication batches at h=20, against a nominal 5%. It is a sample-size
    limit, not an estimator choice — 400 sessions at h=20 hold only ~20
    non-overlapping blocks. `rank_ic` therefore reports `effective_n`
    (sessions / horizon), and a marginal t at a long horizon backed by a small
    `effective_n` should be read as marginal.
    """
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        return np.nan
    e = x - x.mean()

    def _sum(weights) -> float:
        s = float(e @ e) / n
        for l in range(1, min(int(lags), n - 1) + 1):
            s += 2.0 * weights(l) * float(e[l:] @ e[:-l]) / n
        return s

    s = _sum(lambda l: 1.0)
    if s <= 0:
        wide = min(2 * int(lags), n - 1)
        s = _sum(lambda l: max(0.0, 1.0 - l / (wide + 1.0)))
    return max(s, 0.0) / n

def spearman_corr(a: pd.Series | np.ndarray, b: pd.Series | np.ndarray) -> float:
    """Spearman rank correlation using pandas rank and Pearson correlation."""
    s_a = pd.Series(a).rank()
    s_b = pd.Series(b).rank()
    c = s_a.corr(s_b)
    return float(c) if np.isfinite(c) else np.nan


# ---------------------------------------------------------------------------
# inference & session clustering
# ---------------------------------------------------------------------------

def cluster_stats(y: pd.Series, dates: pd.Series, lags: int = 0) -> dict:
    """Mean and t-statistic with standard errors clustered by session (CR0).

    Mornings on the same date share a market. The clustered estimator sums
    within-date residuals before squaring:
        Var(mean) = [sum_g (sum_{i in g} e_ig)^2 / n^2] * [G / (G - 1)]

    With `lags > 0` this becomes Driscoll-Kraay: the same date-summed
    residuals, plus Bartlett-weighted cross-products between dates up to
    `lags` apart. Pass `lags = horizon - 1` whenever the outcome is an
    overlapping forward return, or the t-statistic is inflated by roughly
    sqrt(horizon) — see `_bartlett_var_of_mean`.

    `lags=0` reproduces `explore.cluster_stats` exactly, which is the
    implementation the H016 finding was measured with.
    """
    m = y.notna() & dates.notna()
    y, dates = y[m], dates[m]
    n = len(y)
    if n < 2:
        return {"n": int(n), "n_dates": 0, "mean": np.nan, "median": np.nan,
                "hit_pct": np.nan, "t": np.nan, "naive_t": np.nan,
                "se": np.nan, "naive_se": np.nan}

    mean = float(y.mean())
    resid = y - mean
    by_date = resid.groupby(dates).sum().sort_index()
    g = len(by_date)

    s = by_date.to_numpy(dtype=float)

    def _acc(weights) -> float:
        a = float(s @ s)
        for l in range(1, min(int(lags), g - 1) + 1):
            a += 2.0 * weights(l) * float(s[l:] @ s[:-l])
        return a

    acc = _acc(lambda l: 1.0)              # rectangular; see _hac_var_of_mean
    if acc <= 0:
        wide = min(2 * int(lags), g - 1)
        acc = _acc(lambda l: max(0.0, 1.0 - l / (wide + 1.0)))
    var = max(acc, 0.0) / (n ** 2)
    if g > 1:
        var *= g / (g - 1)

    se = float(np.sqrt(var)) if var > 0 else np.nan
    naive_se = float(y.std() / np.sqrt(n)) if n > 1 else np.nan

    return {
        "n": int(n),
        "n_dates": int(g),
        "hac_lags": int(lags),
        "mean": round(mean, 4),
        "median": round(float(y.median()), 4),
        "hit_pct": round(float((y > 0).mean() * 100), 2),
        "se": round(se, 4) if np.isfinite(se) else np.nan,
        "naive_se": round(naive_se, 4) if np.isfinite(naive_se) else np.nan,
        "t": round(mean / se, 2) if se and se > 0 else np.nan,
        "naive_t": round(mean / naive_se, 2) if naive_se and naive_se > 0 else np.nan,
    }


# ---------------------------------------------------------------------------
# Information Coefficient (Rank IC)
# ---------------------------------------------------------------------------

def rank_ic(
    df: pd.DataFrame,
    signal_col: str,
    forward_col: str,
    date_col: str = "date",
    min_symbols: int = 10,
    horizon: int | None = None,
) -> dict:
    """Daily Spearman rank Information Coefficient (IC) with forward returns.

    `horizon` sets the Newey-West lag used for the t-statistic (h-1). It is
    inferred from `forward_col` when not given, because forgetting it is the
    difference between a 5% false-positive rate and a 68% one.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with signal, forward return, and date.
    signal_col : str
        Column name for the cross-sectional score.
    forward_col : str
        Column name for the forward outcome return.
    date_col : str
        Date column name.
    min_symbols : int
        Minimum symbols required in a session to compute IC.
    horizon : int or None
        Forward horizon in sessions. Inferred from `forward_col` if None.

    Returns
    -------
    dict
        Summary dictionary with mean_ic, std_ic, ic_ir, t_stat, etc.
    """
    h = horizon if horizon is not None else horizon_from_column(forward_col)
    lags = max(0, int(h) - 1)

    valid = df[[date_col, signal_col, forward_col]].dropna()
    if len(valid) == 0:
        return {
            "mean_ic": np.nan, "std_ic": np.nan, "ic_ir": np.nan,
            "t_stat": np.nan, "naive_t_stat": np.nan, "positive_ic_pct": np.nan,
            "horizon": int(h), "hac_lags": lags,
            "n_sessions": 0, "n_obs": 0, "ic_series": pd.Series(dtype=float),
        }

    def _session_ic(g: pd.DataFrame) -> float:
        if len(g) < min_symbols:
            return np.nan
        # Spearman correlation
        return spearman_corr(g[signal_col], g[forward_col])

    ic_by_date = valid.groupby(date_col, sort=True).apply(_session_ic).dropna()
    n_sessions = len(ic_by_date)
    if n_sessions == 0:
        return {
            "mean_ic": np.nan, "std_ic": np.nan, "ic_ir": np.nan,
            "t_stat": np.nan, "naive_t_stat": np.nan, "positive_ic_pct": np.nan,
            "horizon": int(h), "hac_lags": lags,
            "n_sessions": 0, "n_obs": len(valid),
            "ic_series": pd.Series(dtype=float),
        }

    mean_ic = float(ic_by_date.mean())
    std_ic = float(ic_by_date.std()) if n_sessions > 1 else np.nan
    ic_ir = (mean_ic / std_ic * np.sqrt(250)) if std_ic and std_ic > 0 else np.nan

    # The IC series is autocorrelated whenever the label overlaps, so the
    # headline t-statistic is Newey-West. The naive one is kept beside it
    # because the gap between them is itself worth seeing.
    hac_var = _hac_var_of_mean(ic_by_date.to_numpy(), lags)
    hac_se = float(np.sqrt(hac_var)) if np.isfinite(hac_var) and hac_var > 0 else np.nan
    t_stat = (mean_ic / hac_se) if hac_se and hac_se > 0 else np.nan
    naive_t = (mean_ic / (std_ic / np.sqrt(n_sessions))) if std_ic and std_ic > 0 else np.nan
    pos_pct = float((ic_by_date > 0).mean() * 100)

    return {
        "mean_ic": round(mean_ic, 4),
        "std_ic": round(std_ic, 4) if np.isfinite(std_ic) else np.nan,
        "ic_ir": round(ic_ir, 2) if np.isfinite(ic_ir) else np.nan,
        "t_stat": round(t_stat, 2) if np.isfinite(t_stat) else np.nan,
        "naive_t_stat": round(naive_t, 2) if np.isfinite(naive_t) else np.nan,
        "horizon": int(h),
        "hac_lags": lags,
        # Non-overlapping blocks behind the t-statistic. The HAC correction
        # cannot manufacture independent observations that are not there.
        "effective_n": int(n_sessions // max(1, int(h))),
        "positive_ic_pct": round(pos_pct, 2),
        "n_sessions": int(n_sessions),
        "n_obs": int(len(valid)),
        "ic_series": ic_by_date,
    }


def ic_decay(
    df: pd.DataFrame,
    signal_col: str,
    horizons: tuple[int, ...] = (1, 5, 10, 20),
    forward_col_template: str = "fwd_ret_{h}d_pct",
    date_col: str = "date",
) -> list[dict]:
    """IC decay curve across forward horizons."""
    rows = []
    for h in horizons:
        col = forward_col_template.format(h=h)
        if col not in df.columns:
            continue
        res = rank_ic(df, signal_col, col, date_col=date_col, horizon=h)
        rows.append({
            "horizon": h,
            "mean_ic": res["mean_ic"],
            "ic_ir": res["ic_ir"],
            "t_stat": res["t_stat"],
            "naive_t_stat": res["naive_t_stat"],
            "positive_ic_pct": res["positive_ic_pct"],
            "n_sessions": res["n_sessions"],
        })
    return rows


# ---------------------------------------------------------------------------
# Quantile Buckets & Monotonicity
# ---------------------------------------------------------------------------

def quantile_profile(
    df: pd.DataFrame,
    signal_col: str,
    forward_col: str,
    q: int = 5,
    date_col: str = "date",
    min_symbols_per_date: int = 10,
    horizon: int | None = None,
    seed: int = 0,
) -> dict:
    """Within-session quantile profiling: Q1..Qq returns, monotonicity, spread.

    Parameters
    ----------
    q : int
        Number of buckets (5 for quintiles, 10 for deciles). Q1 is lowest score,
        Qq is highest score.
    horizon : int or None
        Forward horizon, for the overlap correction on the spread's
        t-statistic. Inferred from `forward_col` when None.
    seed : int
        Tie-break seed. Ties are split at random rather than collapsed, so
        buckets are always equal-sized — see below.

    ON TIES
    This used to bucket with `pd.qcut(..., duplicates="drop")`, which silently
    renumbers when a session has fewer distinct values than buckets. On a
    tie-heavy session the *top* bucket then came back labelled Q3 and never
    entered Q5, while Q1 pooled 66% of the names against 20% on a clean
    session — measured at Q1 n=4157 against Q5 n=1000 on a mixed frame. Since
    the quantile plot is the headline visual, an unequal and mislabelled one is
    worse than useless.

    Ties are now broken at random (seeded, so runs reproduce) and buckets are
    always exactly `q` and equal-sized. `tie_pct` reports how much of the
    bucketing that arbitration is carrying.
    """
    valid = df[[date_col, signal_col, forward_col]].dropna().copy()
    if len(valid) < q * 10:
        return {
            "quantiles": [],
            "spread_pct": np.nan,
            "spread_bps": np.nan,
            "spread_t": np.nan,
            "spread_naive_t": np.nan,
            "monotonicity": np.nan,
            "tie_pct": np.nan,
            "q_count": q,
        }

    h = horizon if horizon is not None else horizon_from_column(forward_col)
    lags = max(0, int(h) - 1)
    rng = np.random.default_rng(seed)

    # How much of the cross-section is tied, before anything is decided?
    tie_pct = float(valid.groupby(date_col)[signal_col]
                    .transform(lambda s: s.duplicated(keep=False)).mean() * 100)

    def _assign_q(s: pd.Series) -> pd.Series:
        n = len(s)
        if n < max(min_symbols_per_date, q):
            return pd.Series(np.nan, index=s.index)
        order = pd.Series(rng.permutation(n), index=s.index)
        ranked = pd.DataFrame({"s": s, "t": order}).sort_values(["s", "t"])
        buckets = np.ceil((np.arange(n) + 1) / n * q).astype(int) - 1
        return pd.Series(buckets, index=ranked.index).reindex(s.index)

    valid["q_bucket"] = valid.groupby(date_col)[signal_col].transform(_assign_q)
    valid = valid.dropna(subset=["q_bucket"]).copy()
    valid["q_bucket"] = valid["q_bucket"].astype(int) + 1  # 1-indexed: 1..q

    # Quantile summaries
    q_stats = []
    bucket_means = []
    for b in range(1, q + 1):
        sub = valid[valid["q_bucket"] == b]
        cs = cluster_stats(sub[forward_col], sub[date_col], lags=lags)
        cs["bucket"] = b
        cs["name"] = f"Q{b}"
        q_stats.append(cs)
        bucket_means.append(cs["mean"])

    # Monotonicity: Spearman rank correlation of bucket index with bucket mean
    if len(bucket_means) >= 3 and not np.isnan(bucket_means).any():
        mono_r = spearman_corr(list(range(1, q + 1)), bucket_means)
        monotonicity = round(float(mono_r), 3)
    else:
        monotonicity = np.nan

    # Spread: Q_top minus Q_bottom per date
    daily_q = valid.groupby([date_col, "q_bucket"])[forward_col].mean().unstack()
    if 1 in daily_q.columns and q in daily_q.columns:
        daily_spread = daily_q[q] - daily_q[1]
        daily_spread = daily_spread.dropna()
        spread_mean = float(daily_spread.mean())
        spread_std = float(daily_spread.std())
        # Overlapping labels make the daily spread series autocorrelated too.
        sv = _hac_var_of_mean(daily_spread.to_numpy(), lags)
        spread_se = float(np.sqrt(sv)) if np.isfinite(sv) and sv > 0 else np.nan
        spread_t = (spread_mean / spread_se) if spread_se and spread_se > 0 else np.nan
        spread_naive_t = (spread_mean / (spread_std / np.sqrt(len(daily_spread)))) \
            if spread_std > 0 else np.nan
        spread_bps = round(spread_mean * 100, 1)  # 1% = 100 bps
    else:
        spread_mean = np.nan
        spread_t = np.nan
        spread_naive_t = np.nan
        spread_bps = np.nan

    return {
        "quantiles": q_stats,
        "monotonicity": monotonicity,
        "spread_pct": round(spread_mean, 4) if np.isfinite(spread_mean) else np.nan,
        "spread_bps": spread_bps,
        "spread_t": round(spread_t, 2) if np.isfinite(spread_t) else np.nan,
        "spread_naive_t": round(spread_naive_t, 2) if np.isfinite(spread_naive_t) else np.nan,
        "horizon": int(h),
        "hac_lags": lags,
        "tie_pct": round(tie_pct, 1),
        "q_count": q,
    }


def selector_vs_baseline(
    df: pd.DataFrame,
    signal_col: str,
    baseline_col: str,
    forward_col: str,
    date_col: str = "date",
    horizon: int | None = None,
) -> dict:
    """Compare a sparse selector with a baseline at the identical daily take rate.

    Non-candidates are NaN by contract. On each active session the baseline
    takes exactly as many names as the selector, preventing selectivity from
    being mistaken for skill. The headline observation is one paired
    selector-minus-baseline mean per session, corrected for overlapping
    horizons.
    """
    required = [date_col, signal_col, baseline_col, forward_col]
    d = df[required].copy()
    d = d.dropna(subset=[date_col, forward_col, baseline_col])
    h = horizon if horizon is not None else horizon_from_column(forward_col)
    selector_rows = []
    baseline_rows = []
    paired = []
    n_selected = 0
    for date, group in d.groupby(date_col, sort=True):
        selected = group[group[signal_col].notna()]
        n_take = len(selected)
        if n_take == 0:
            continue
        baseline = group.nlargest(n_take, baseline_col, keep="first")
        if len(baseline) != n_take:
            continue
        sel_mean = float(selected[forward_col].mean())
        base_mean = float(baseline[forward_col].mean())
        selector_rows.append((date, sel_mean))
        baseline_rows.append((date, base_mean))
        paired.append((date, sel_mean - base_mean))
        n_selected += n_take

    if not paired:
        return {
            "n_selected": 0, "n_sessions": 0, "selected_mean_bps": np.nan,
            "baseline_mean_bps": np.nan, "lift_bps": np.nan,
            "lift_t": np.nan, "lift_naive_t": np.nan,
        }
    paired_df = pd.DataFrame(paired, columns=[date_col, "diff"])
    sel = pd.Series(dict(selector_rows)).sort_index()
    base = pd.Series(dict(baseline_rows)).sort_index()
    stats = cluster_stats(
        paired_df["diff"], paired_df[date_col], lags=max(0, int(h) - 1))
    return {
        "n_selected": int(n_selected),
        "n_sessions": int(len(paired_df)),
        "selected_mean_bps": round(float(sel.mean()) * 100.0, 1),
        "baseline_mean_bps": round(float(base.mean()) * 100.0, 1),
        "lift_bps": round(float(paired_df["diff"].mean()) * 100.0, 1),
        "lift_t": stats["t"],
        "lift_naive_t": stats["naive_t"],
        "horizon": int(h),
    }


# ---------------------------------------------------------------------------
# Signal Mechanics (Turnover, Autocorrelation, Coverage)
# ---------------------------------------------------------------------------

def signal_mechanics(
    df: pd.DataFrame,
    signal_col: str,
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> dict:
    """Evaluates signal stability, autocorrelation, and universe coverage."""
    valid = df[[date_col, symbol_col, signal_col]].dropna().copy()
    if len(valid) == 0:
        return {
            "mean_turnover": np.nan,
            "autocorrelation_1d": np.nan,
            "autocorrelation_5d": np.nan,
            "mean_coverage_names": 0,
            "min_coverage_names": 0,
            "max_coverage_names": 0,
        }

    # Universe coverage per session
    counts = valid.groupby(date_col)[symbol_col].count()
    cov_mean = float(counts.mean())
    cov_min = int(counts.min())
    cov_max = int(counts.max())

    # Daily percentile ranks for turnover and autocorrelation
    valid["rank_pct"] = valid.groupby(date_col)[signal_col].rank(pct=True)
    wide = valid.pivot(index=date_col, columns=symbol_col, values="rank_pct")
    wide = wide.sort_index()

    # Daily turnover: mean absolute rank change from t-1 to t
    diff = wide.diff(1).abs()
    daily_turnover = diff.mean(axis=1).dropna()
    mean_turnover = float(daily_turnover.mean()) if len(daily_turnover) > 0 else np.nan

    # Autocorrelations: cross-sectional correlation between rank(t) and rank(t-k)
    def _lag_corr(k: int) -> float:
        corrs = []
        for i in range(k, len(wide)):
            r0 = wide.iloc[i - k]
            r1 = wide.iloc[i]
            m = r0.notna() & r1.notna()
            if m.sum() >= 10:
                c = spearman_corr(r0[m], r1[m])
                if np.isfinite(c):
                    corrs.append(c)
        return float(np.mean(corrs)) if corrs else np.nan

    ac_1d = _lag_corr(1)
    ac_5d = _lag_corr(5)

    return {
        "mean_turnover": round(mean_turnover, 4) if np.isfinite(mean_turnover) else np.nan,
        "autocorrelation_1d": round(ac_1d, 3) if np.isfinite(ac_1d) else np.nan,
        "autocorrelation_5d": round(ac_5d, 3) if np.isfinite(ac_5d) else np.nan,
        "mean_coverage_names": round(cov_mean, 1),
        "min_coverage_names": cov_min,
        "max_coverage_names": cov_max,
    }


# ---------------------------------------------------------------------------
# Conditioning & Stratification
# ---------------------------------------------------------------------------

def stratify_by_group(
    df: pd.DataFrame,
    signal_col: str,
    forward_col: str,
    group_col: str,
    date_col: str = "date",
    min_obs: int = 50,
    horizon: int | None = None,
) -> list[dict]:
    """Evaluates IC and Q5-Q1 spread broken down by a conditioning variable."""
    if group_col not in df.columns:
        return []

    valid = df[[date_col, signal_col, forward_col, group_col]].dropna()
    groups = valid[group_col].unique()

    rows = []
    for g in sorted(groups, key=lambda x: str(x)):
        sub = valid[valid[group_col] == g]
        if len(sub) < min_obs:
            continue

        ic_res = rank_ic(sub, signal_col, forward_col, date_col=date_col,
                         horizon=horizon)
        qp = quantile_profile(sub, signal_col, forward_col, q=5,
                              date_col=date_col, horizon=horizon)

        rows.append({
            "group": str(g),
            "n_obs": len(sub),
            "n_sessions": ic_res["n_sessions"],
            "mean_ic": ic_res["mean_ic"],
            "ic_t_stat": ic_res["t_stat"],
            "q5_minus_q1_pct": qp["spread_pct"],
            "q5_minus_q1_t": qp["spread_t"],
            "monotonicity": qp["monotonicity"],
        })
    return rows
