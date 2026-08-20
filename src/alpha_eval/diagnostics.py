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

import numpy as np
import pandas as pd


def spearman_corr(a: pd.Series | np.ndarray, b: pd.Series | np.ndarray) -> float:
    """Spearman rank correlation using pandas rank and Pearson correlation."""
    s_a = pd.Series(a).rank()
    s_b = pd.Series(b).rank()
    c = s_a.corr(s_b)
    return float(c) if np.isfinite(c) else np.nan


# ---------------------------------------------------------------------------
# inference & session clustering
# ---------------------------------------------------------------------------

def cluster_stats(y: pd.Series, dates: pd.Series) -> dict:
    """Mean and t-statistic with standard errors clustered by session (CR0).

    Mornings on the same date share a market. The clustered estimator sums
    within-date residuals before squaring:
        Var(mean) = [sum_g (sum_{i in g} e_ig)^2 / n^2] * [G / (G - 1)]
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
    by_date = resid.groupby(dates).sum()
    g = len(by_date)

    var = float((by_date ** 2).sum()) / (n ** 2)
    if g > 1:
        var *= g / (g - 1)

    se = float(np.sqrt(var)) if var > 0 else np.nan
    naive_se = float(y.std() / np.sqrt(n)) if n > 1 else np.nan

    return {
        "n": int(n),
        "n_dates": int(g),
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
) -> dict:
    """Daily Spearman rank Information Coefficient (IC) with forward returns.

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

    Returns
    -------
    dict
        Summary dictionary with mean_ic, std_ic, ic_ir, t_stat, etc.
    """
    valid = df[[date_col, signal_col, forward_col]].dropna()
    if len(valid) == 0:
        return {
            "mean_ic": np.nan, "std_ic": np.nan, "ic_ir": np.nan,
            "t_stat": np.nan, "positive_ic_pct": np.nan,
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
            "t_stat": np.nan, "positive_ic_pct": np.nan,
            "n_sessions": 0, "n_obs": len(valid),
            "ic_series": pd.Series(dtype=float),
        }

    mean_ic = float(ic_by_date.mean())
    std_ic = float(ic_by_date.std()) if n_sessions > 1 else np.nan
    ic_ir = (mean_ic / std_ic * np.sqrt(250)) if std_ic and std_ic > 0 else np.nan
    t_stat = (mean_ic / (std_ic / np.sqrt(n_sessions))) if std_ic and std_ic > 0 else np.nan
    pos_pct = float((ic_by_date > 0).mean() * 100)

    return {
        "mean_ic": round(mean_ic, 4),
        "std_ic": round(std_ic, 4) if np.isfinite(std_ic) else np.nan,
        "ic_ir": round(ic_ir, 2) if np.isfinite(ic_ir) else np.nan,
        "t_stat": round(t_stat, 2) if np.isfinite(t_stat) else np.nan,
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
        res = rank_ic(df, signal_col, col, date_col=date_col)
        rows.append({
            "horizon": h,
            "mean_ic": res["mean_ic"],
            "ic_ir": res["ic_ir"],
            "t_stat": res["t_stat"],
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
) -> dict:
    """Within-session quantile profiling: Q1..Qq returns, monotonicity, spread.

    Parameters
    ----------
    q : int
        Number of buckets (5 for quintiles, 10 for deciles). Q1 is lowest score,
        Qq is highest score.
    """
    valid = df[[date_col, signal_col, forward_col]].dropna().copy()
    if len(valid) < q * 10:
        return {
            "quantiles": [],
            "spread_q_top_minus_bottom": np.nan,
            "spread_t": np.nan,
            "monotonicity": np.nan,
            "q_count": q,
        }

    # Form quantiles per session
    def _assign_q(s: pd.Series) -> pd.Series:
        if len(s) < max(min_symbols_per_date, q):
            return pd.Series(np.nan, index=s.index)
        return pd.qcut(s, q, labels=False, duplicates="drop")

    valid["q_bucket"] = valid.groupby(date_col)[signal_col].transform(_assign_q)
    valid = valid.dropna(subset=["q_bucket"]).copy()
    valid["q_bucket"] = valid["q_bucket"].astype(int) + 1  # 1-indexed: 1..q

    # Quantile summaries
    q_stats = []
    bucket_means = []
    for b in range(1, q + 1):
        sub = valid[valid["q_bucket"] == b]
        cs = cluster_stats(sub[forward_col], sub[date_col])
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
        spread_t = (spread_mean / (spread_std / np.sqrt(len(daily_spread)))) if spread_std > 0 else np.nan
        spread_bps = round(spread_mean * 100, 1)  # 1% = 100 bps
    else:
        spread_mean = np.nan
        spread_t = np.nan
        spread_bps = np.nan

    return {
        "quantiles": q_stats,
        "monotonicity": monotonicity,
        "spread_pct": round(spread_mean, 4) if np.isfinite(spread_mean) else np.nan,
        "spread_bps": spread_bps,
        "spread_t": round(spread_t, 2) if np.isfinite(spread_t) else np.nan,
        "q_count": q,
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

        ic_res = rank_ic(sub, signal_col, forward_col, date_col=date_col)
        qp = quantile_profile(sub, signal_col, forward_col, q=5, date_col=date_col)

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
