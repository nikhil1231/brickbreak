"""Factor neutralisation and projection diagnostics (PLAN.md §5.9).

MANDATORY INVARIANT:
For every candidate signal: does predictive power survive after controlling
for standard risk factors (market beta, sector, size, volatility, momentum)?

THE H038 LESSON:
A score built by subtracting a factor (e.g. resid = r - beta * r_mkt) is
algebraically identical to beta when r_mkt is constant within a session.
This module auto-projects signals off what they adjust for and measures the
true incremental information.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import diagnostics



STANDARD_FACTORS = ("beta", "sector", "size", "volatility", "momentum")


def extract_factor_columns(df: pd.DataFrame) -> dict[str, str]:
    """Identifies standard factor columns available in the dataframe."""
    mapping = {}
    if "beta" in df.columns:
        mapping["beta"] = "beta"
    elif "mkt_ret_20d" in df.columns:
        mapping["beta"] = "mkt_ret_20d"

    if "sector" in df.columns:
        mapping["sector"] = "sector"

    if "median_tv_20_cr" in df.columns:
        mapping["size"] = "median_tv_20_cr"
    elif "turnover" in df.columns:
        mapping["size"] = "turnover"

    if "atr_pct" in df.columns:
        mapping["volatility"] = "atr_pct"
    elif "range_pct_ma" in df.columns:
        mapping["volatility"] = "range_pct_ma"

    if "ret_20d" in df.columns:
        mapping["momentum"] = "ret_20d"
    elif "ret_60d" in df.columns:
        mapping["momentum"] = "ret_60d"

    return mapping


def cross_sectional_residualize(
    df: pd.DataFrame,
    signal_col: str,
    factor_cols: list[str],
    date_col: str = "date",
    min_symbols: int = 15,
) -> pd.Series:
    """Regress signal against factor columns cross-sectionally per session.

    Returns the residual series aligned to df's index.
    """
    valid = df[[date_col, signal_col] + factor_cols].copy()
    resids = pd.Series(np.nan, index=df.index, name=f"{signal_col}_neutralized")

    # Check for categorical columns (e.g. sector) to dummy encode
    num_cols = [c for c in factor_cols if pd.api.types.is_numeric_dtype(valid[c])]
    cat_cols = [c for c in factor_cols if not pd.api.types.is_numeric_dtype(valid[c])]

    for d, g in valid.groupby(date_col):
        g_clean = g.dropna()
        if len(g_clean) < max(min_symbols, len(factor_cols) + 5):
            continue

        y = g_clean[signal_col].to_numpy(dtype=float)

        # Build design matrix X
        X_parts = [np.ones((len(g_clean), 1))]
        if num_cols:
            num_data = g_clean[num_cols].to_numpy(dtype=float)
            # Standardize numeric factors per session
            num_std = (num_data - np.mean(num_data, axis=0)) / (np.std(num_data, axis=0) + 1e-8)
            X_parts.append(num_std)

        if cat_cols:
            for cc in cat_cols:
                dummies = pd.get_dummies(g_clean[cc], drop_first=True, dtype=float).to_numpy()
                if dummies.shape[1] > 0:
                    X_parts.append(dummies)

        X = np.hstack(X_parts)

        # OLS projection: residuals = y - X * inv(X'X) * X'y
        try:
            beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
            pred = X @ beta
            resid = y - pred
            resids.loc[g_clean.index] = resid
        except Exception:
            continue

    return resids


def neutralisation_analysis(
    df: pd.DataFrame,
    signal_col: str,
    forward_col: str,
    factor_cols: list[str] | None = None,
    date_col: str = "date",
) -> dict:
    """Complete neutralisation report: raw vs neutralised IC and decomposition."""
    if factor_cols is None:
        factor_map = extract_factor_columns(df)
        factor_cols = list(factor_map.values())

    # Raw IC
    raw_ic_res = diagnostics.rank_ic(df, signal_col, forward_col, date_col=date_col)

    # Neutralized signal
    clean_factors = [f for f in factor_cols if f in df.columns]
    if not clean_factors:
        return {
            "raw_mean_ic": raw_ic_res["mean_ic"],
            "neutralized_mean_ic": raw_ic_res["mean_ic"],
            "ic_retention_pct": 100.0,
            "factors_controlled": [],
            "factor_ic_breakdown": {},
        }

    resid_col = f"_temp_resid_{signal_col}"
    d = df.copy()
    d[resid_col] = cross_sectional_residualize(d, signal_col, clean_factors, date_col=date_col)

    neu_ic_res = diagnostics.rank_ic(d, resid_col, forward_col, date_col=date_col)

    # Individual factor correlations and ICs
    factor_breakdown = {}
    for f in clean_factors:
        if not pd.api.types.is_numeric_dtype(d[f]):
            continue
        # Signal vs Factor correlation
        valid_sf = d[[date_col, signal_col, f]].dropna()
        if len(valid_sf) > 50:
            def _corr(g):
                if len(g) < 10:
                    return np.nan
                return diagnostics.spearman_corr(g[signal_col], g[f])
            sf_corrs = valid_sf.groupby(date_col).apply(_corr).dropna()
            mean_sf_corr = float(sf_corrs.mean()) if len(sf_corrs) > 0 else np.nan
        else:
            mean_sf_corr = np.nan

        # Factor IC
        f_ic = diagnostics.rank_ic(d, f, forward_col, date_col=date_col)

        factor_breakdown[f] = {
            "signal_factor_rank_corr": round(mean_sf_corr, 3) if np.isfinite(mean_sf_corr) else np.nan,
            "factor_raw_ic": f_ic["mean_ic"],
            "factor_ic_t": f_ic["t_stat"],
        }

    retention = np.nan
    if raw_ic_res["mean_ic"] and abs(raw_ic_res["mean_ic"]) > 1e-6:
        retention = round((neu_ic_res["mean_ic"] / raw_ic_res["mean_ic"]) * 100.0, 1)

    return {
        "raw_mean_ic": raw_ic_res["mean_ic"],
        "raw_ic_t_stat": raw_ic_res["t_stat"],
        "neutralized_mean_ic": neu_ic_res["mean_ic"],
        "neutralized_ic_t_stat": neu_ic_res["t_stat"],
        "ic_retention_pct": retention,
        "factors_controlled": clean_factors,
        "factor_breakdown": factor_breakdown,
    }


def orthogonal_projection_test(
    df: pd.DataFrame,
    score_col: str,
    factor_col: str,
    date_col: str = "date",
) -> dict:
    """H038 Guard: tests whether score is algebraically identical to factor.

    If a score is built by subtracting a factor, within any single session it
    may have near-1.0 correlation with that factor.
    """
    valid = df[[date_col, score_col, factor_col]].dropna()
    if len(valid) < 50:
        return {"mean_abs_corr": np.nan, "is_pure_factor": False, "verdict": "insufficient_sample"}

    def _abs_corr(g):
        if len(g) < 10:
            return np.nan
        c = diagnostics.spearman_corr(g[score_col], g[factor_col])
        return abs(c) if np.isfinite(c) else np.nan

    corrs = valid.groupby(date_col).apply(_abs_corr).dropna()
    mean_abs_corr = float(corrs.mean()) if len(corrs) > 0 else np.nan
    is_pure_factor = bool(mean_abs_corr > 0.95)

    verdict = "independent"
    if mean_abs_corr > 0.95:
        verdict = "WARNING: score is algebraically identical to factor (H038 error)"
    elif mean_abs_corr > 0.70:
        verdict = "heavily exposed to factor (>70% rank correlation)"

    return {
        "mean_abs_corr": round(mean_abs_corr, 4) if np.isfinite(mean_abs_corr) else np.nan,
        "is_pure_factor": is_pure_factor,
        "verdict": verdict,
    }
