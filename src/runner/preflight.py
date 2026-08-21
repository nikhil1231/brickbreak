"""Label-free pre-flight screening (PLAN.md §6).

Evaluates candidate signals before dispatch WITHOUT ever loading or touching
forward outcome labels. A candidate rejected in pre-flight preserves the sample
budget because no test against forward returns was ever run.

Evaluates:
1. Degeneracy & universe coverage (INSUFFICIENT_SAMPLE, DATA_QUALITY)
2. Daily rank turnover (HIGH_TURNOVER against 40 bps round trip)
3. Factor correlation & H038 check (SIGNAL_BUT_BETA, REDUNDANT_WITH_EXISTING_ALPHA)
4. Correlation against existing signals (REDUNDANT_WITH_EXISTING_ALPHA)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
import numpy as np
import pandas as pd

from ..alpha_eval import diagnostics
from ..alpha_eval.guards import assert_no_forward_labels, assert_scorable
from ..alpha_eval.neutralisation import extract_factor_columns
from ..persistence import PreFlightResult, store
from .spec import ExperimentSpec

logger = logging.getLogger(__name__)


@dataclass
class PreFlightConfig:
    max_turnover: float = 0.70
    min_coverage_names: float = 50.0
    min_active_sessions_pct: float = 0.80
    max_factor_abs_corr: float = 0.95
    max_existing_signal_corr: float = 0.90


def run_preflight(
    df: pd.DataFrame,
    signal_col: str,
    spec: ExperimentSpec | None = None,
    cfg: PreFlightConfig | None = None,
    save_results: bool = True,
    date_col: str = "date",
    symbol_col: str = "symbol",
) -> PreFlightResult:
    """Executes label-free pre-flight checks on a candidate signal.

    Guarantees:
    - Never evaluates, loads, or references forward return columns.
    - If the check fails, NO Evidence/Exploration is created and burden.count_tests
      is NOT incremented.
    """
    if cfg is None:
        cfg = PreFlightConfig()

    # Invariant: Pre-flight must NEVER see forward labels
    assert_no_forward_labels(df, context="pre-flight check")
    assert_scorable(signal_col)

    hypo_id = spec.hypothesis_id if spec else "H_UNKNOWN"
    partition = spec.partition if spec else "train"
    pf_id = f"PF_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{signal_col}"

    reasons: list[str] = []
    failure_class: str | None = None

    # 1. Basic degeneracy & coverage
    if signal_col not in df.columns:
        return PreFlightResult(
            id=pf_id,
            hypothesis_id=hypo_id,
            signal_name=signal_col,
            partition=partition,
            passed=False,
            failure_class="DATA_QUALITY",
            reasons=[f"Column {signal_col!r} not found in frame"],
        )

    valid = df[[date_col, symbol_col, signal_col]].dropna().copy()
    if len(valid) == 0:
        return PreFlightResult(
            id=pf_id,
            hypothesis_id=hypo_id,
            signal_name=signal_col,
            partition=partition,
            passed=False,
            failure_class="DATA_QUALITY",
            reasons=["Signal series contains only NaN values"],
        )

    # Constant signal check
    sig_std = valid[signal_col].std()
    if pd.isna(sig_std) or sig_std == 0:
        return PreFlightResult(
            id=pf_id,
            hypothesis_id=hypo_id,
            signal_name=signal_col,
            partition=partition,
            passed=False,
            failure_class="DATA_QUALITY",
            reasons=["Signal is constant across universe (variance is zero); cannot rank anything"],
        )

    # Session coverage
    counts = valid.groupby(date_col)[symbol_col].count()
    mean_cov = float(counts.mean()) if len(counts) > 0 else 0.0
    min_cov = int(counts.min()) if len(counts) > 0 else 0
    max_cov = int(counts.max()) if len(counts) > 0 else 0

    total_sessions = df[date_col].nunique()
    active_sessions = (counts >= 10).sum()
    active_session_pct = (active_sessions / max(1, total_sessions))

    if mean_cov < cfg.min_coverage_names:
        reasons.append(
            f"Mean universe coverage of {mean_cov:.1f} names/session is below "
            f"minimum required {cfg.min_coverage_names:.1f}"
        )
        failure_class = failure_class or "INSUFFICIENT_SAMPLE"

    if active_session_pct < cfg.min_active_sessions_pct:
        reasons.append(
            f"Only {active_session_pct*100:.1f}% of sessions meet 10-name minimum "
            f"(required >= {cfg.min_active_sessions_pct*100:.0f}%)"
        )
        failure_class = failure_class or "INSUFFICIENT_SAMPLE"

    # 2. Signal mechanics (Turnover, Autocorrelation)
    mechanics = diagnostics.signal_mechanics(
        df, signal_col=signal_col, date_col=date_col, symbol_col=symbol_col
    )
    turnover = mechanics.get("mean_turnover")
    if turnover is not None and not np.isnan(turnover):
        if turnover > cfg.max_turnover:
            reasons.append(
                f"Mean rank turnover {turnover:.3f}/session exceeds maximum {cfg.max_turnover:.2f}; "
                f"cannot survive 40 bps round-trip transaction costs"
            )
            failure_class = failure_class or "HIGH_TURNOVER"

    # 3. Factor correlations (Market Beta, Size, Volatility, Momentum) & H038 Guard
    factor_corrs: dict[str, float] = {}
    factor_map = extract_factor_columns(df)
    for factor_name, factor_col in factor_map.items():
        if factor_col not in df.columns or factor_col == signal_col:
            continue
        if not pd.api.types.is_numeric_dtype(df[factor_col]):
            continue

        pair_df = df[[date_col, signal_col, factor_col]].dropna()
        if len(pair_df) < 50:
            continue

        def _corr(g: pd.DataFrame) -> float:
            if len(g) < 10:
                return np.nan
            return diagnostics.spearman_corr(g[signal_col], g[factor_col])

        session_corrs = pair_df.groupby(date_col).apply(_corr).dropna()
        if len(session_corrs) > 0:
            mean_corr = float(session_corrs.mean())
            mean_abs_corr = float(session_corrs.abs().mean())
            factor_corrs[factor_name] = round(mean_corr, 4)

            if mean_abs_corr > cfg.max_factor_abs_corr:
                if factor_name == "beta":
                    reasons.append(
                        f"Signal has mean absolute correlation {mean_abs_corr:.3f} with market beta; "
                        f"algebraically identical to beta (H038 check)"
                    )
                    failure_class = failure_class or "SIGNAL_BUT_BETA"
                else:
                    reasons.append(
                        f"Signal has mean absolute correlation {mean_abs_corr:.3f} with factor '{factor_name}'"
                    )
                    failure_class = failure_class or "REDUNDANT_WITH_EXISTING_ALPHA"

    # 4. Correlation with existing signals
    signal_corrs: dict[str, float] = {}
    for existing_sig in store.list_signals():
        other_name = existing_sig.name
        if other_name == signal_col or other_name not in df.columns:
            continue
        pair_df = df[[date_col, signal_col, other_name]].dropna()
        if len(pair_df) < 50:
            continue

        def _corr_sig(g: pd.DataFrame) -> float:
            if len(g) < 10:
                return np.nan
            return diagnostics.spearman_corr(g[signal_col], g[other_name])

        session_corrs = pair_df.groupby(date_col).apply(_corr_sig).dropna()
        if len(session_corrs) > 0:
            mean_abs_corr = float(session_corrs.abs().mean())
            signal_corrs[other_name] = round(float(session_corrs.mean()), 4)
            if mean_abs_corr > cfg.max_existing_signal_corr:
                reasons.append(
                    f"Signal has mean absolute correlation {mean_abs_corr:.3f} with existing signal {other_name!r}"
                )
                failure_class = failure_class or "REDUNDANT_WITH_EXISTING_ALPHA"

    passed = len(reasons) == 0
    if passed:
        failure_class = None

    result = PreFlightResult(
        id=pf_id,
        hypothesis_id=hypo_id,
        signal_name=signal_col,
        partition=partition,
        passed=passed,
        failure_class=failure_class,
        reasons=reasons,
        mechanics=mechanics,
        factor_correlations=factor_corrs,
        signal_correlations=signal_corrs,
    )

    if save_results:
        store.save_preflight(result)

    return result
