"""Unified alpha evaluation suite and report generator (the refactor plan §5.8).

Runs the standard battery across:
1. Predictive Content (Rank IC, IC decay, Clustered t-stats)
2. Quantile Profiling (Q1..Q5, Monotonicity, Spread)
3. Signal Mechanics (Turnover, Persistence, Coverage)
4. Neutralisation Diagnostics (Retained IC, Factor Exposures, H038 Check)
5. Canonical Backtest (Top-K Portfolio vs Market)
6. Subperiod & Regime Conditioning
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
import pandas as pd

from . import diagnostics, neutralisation, backtest
from .guards import assert_scorable


def evaluate_signal(
    df: pd.DataFrame,
    signal_col: str,
    forward_col: str = "fwd_ret_5d_pct",
    horizons: tuple[int, ...] = (1, 5, 10, 20),
    run_backtest: bool = True,
    run_neutralisation: bool = True,
    backtest_cfg: backtest.BacktestConfig | None = None,
    baseline_col: str | None = None,
    selector_mode: bool = False,
    date_col: str = "date",
    symbol_col: str = "symbol",
    output_path: Path | None = None,
    allow_unscorable: bool = False,
) -> dict:
    """Executes the standard alpha evaluation battery and emits a structured fingerprint."""
    assert_scorable(signal_col, allow_unscorable=allow_unscorable)
    report = {
        "signal": signal_col,
        "primary_forward_col": forward_col,
        "n_total_rows": len(df),
        "evaluation_mode": "selector" if selector_mode else "dense",
    }

    # 1. Predictive Content & IC
    ic_res = diagnostics.rank_ic(df, signal_col, forward_col, date_col=date_col)
    decay_template = ("excess_ret_{h}d_pct"
                      if forward_col.startswith("excess_ret_")
                      else "fwd_ret_{h}d_pct")
    ic_decay = diagnostics.ic_decay(
        df, signal_col, horizons=horizons,
        forward_col_template=decay_template, date_col=date_col)
    report["predictive_content"] = {
        "primary_ic": {
            "mean_ic": ic_res["mean_ic"],
            "ic_ir": ic_res["ic_ir"],
            "t_stat": ic_res["t_stat"],
            "positive_ic_pct": ic_res["positive_ic_pct"],
            "n_sessions": ic_res["n_sessions"],
        },
        "ic_decay": ic_decay,
    }

    # 2. Quantile Profile (Quintiles Q1..Q5 & Deciles D1..D10)
    q5 = diagnostics.quantile_profile(df, signal_col, forward_col, q=5, date_col=date_col)
    q10 = diagnostics.quantile_profile(df, signal_col, forward_col, q=10, date_col=date_col)
    report["quantiles"] = {
        "q5_profile": q5["quantiles"],
        "q5_monotonicity": q5["monotonicity"],
        "q5_spread_pct": q5["spread_pct"],
        "q5_spread_bps": q5["spread_bps"],
        "q5_spread_t": q5["spread_t"],
        "q10_spread_pct": q10["spread_pct"],
        "q10_spread_bps": q10["spread_bps"],
        "q10_monotonicity": q10["monotonicity"],
    }

    if baseline_col:
        if baseline_col not in df.columns:
            raise ValueError(f"baseline column {baseline_col!r} is missing")
        if selector_mode:
            report["baseline_comparison"] = diagnostics.selector_vs_baseline(
                df, signal_col, baseline_col, forward_col,
                date_col=date_col)
        else:
            baseline_ic = diagnostics.rank_ic(
                df, baseline_col, forward_col, date_col=date_col)
            baseline_q = diagnostics.quantile_profile(
                df, baseline_col, forward_col, q=5, date_col=date_col)
            report["baseline_comparison"] = {
                "baseline_name": baseline_col,
                "signal_mean_ic": ic_res["mean_ic"],
                "baseline_mean_ic": baseline_ic["mean_ic"],
                "incremental_mean_ic": round(
                    float(ic_res["mean_ic"] - baseline_ic["mean_ic"]), 4),
                "signal_spread_bps": q5["spread_bps"],
                "baseline_spread_bps": baseline_q["spread_bps"],
                "incremental_spread_bps": round(
                    float(q5["spread_bps"] - baseline_q["spread_bps"]), 1),
            }

    # 3. Signal Mechanics
    report["signal_mechanics"] = diagnostics.signal_mechanics(
        df, signal_col, date_col=date_col, symbol_col=symbol_col
    )

    # 4. Neutralisation Diagnostics
    if run_neutralisation:
        report["neutralisation"] = neutralisation.neutralisation_analysis(
            df, signal_col, forward_col, date_col=date_col
        )

    # 5. Canonical Backtest
    if run_backtest:
        report["canonical_backtest"] = backtest.canonical_backtest(
            df, signal_col, cfg=backtest_cfg, date_col=date_col, symbol_col=symbol_col
        )

    # 6. Conditioning & Stratification
    conditioning = {}
    d = df.copy()
    if date_col in d.columns and "year" not in d.columns:
        d["year"] = pd.to_datetime(d[date_col]).dt.year

    for group_var in ("year", "mkt_regime", "sector", "size_tier"):
        if group_var in d.columns:
            conditioning[group_var] = diagnostics.stratify_by_group(
                d, signal_col, forward_col, group_var, date_col=date_col
            )
    report["conditioning"] = conditioning

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, default=str))

    return report
