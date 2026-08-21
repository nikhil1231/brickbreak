"""End-to-End Research Runner (the refactor plan §5.7).

Executes an exploration from a specification:
1. Validates spec and checks data budget permissions.
2. Loads data via `research_data.frame`.
3. Computes the candidate signal.
4. Evaluates through `alpha_eval.evaluate_signal()`.
5. Classifies outcome via the §5.11 failure taxonomy.
6. Emits immutable cryptographic manifest.
7. Persists Exploration, Signal, and Evidence to store.
8. Updates the sample budget ledger.
9. Updates Hypothesis status and idea graph.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
import pandas as pd

from ..alpha_eval import evaluate_signal
from ..persistence import (
    Edge,
    Evidence,
    Exploration,
    Hypothesis,
    SampleBudgetLedger,
    Signal,
    build_manifest,
    save_exploration,
    save_hypothesis,
    save_manifest,
    save_signal,
    store,
)
from ..research_data import frame, splits
from .classifier import classify_result
from .interpret import write_interpretation
from . import burden as burden_mod
from .spec import ExperimentSpec, validate_spec


def run_exploration(
    spec: ExperimentSpec,
    compute_signal_fn: Callable[[pd.DataFrame], pd.DataFrame | pd.Series],
    save_results: bool = True,
    bars: pd.DataFrame | None = None,
    provider_used: str = "none",
    model_used: str = "none",
) -> dict[str, Any]:
    """Executes one complete, clean exploration end-to-end."""
    t0 = time.time()

    # 1. Pre-dispatch validation & sample budget permission check
    ledger = SampleBudgetLedger.load()
    validate_spec(spec, budget_ledger=ledger)

    # 2. Safe data loading through research_data
    df = frame.load_daily_panel(
        version=spec.dataset_version,
        partition=spec.partition,
        asof_open=True,
        include_context=True,
    )

    # Attach forward returns for all requested horizons
    for h in spec.horizons:
        df[f"fwd_ret_{h}d_pct"] = frame.forward_return(
            df, horizon=h, version=spec.dataset_version, bars=bars
        )

    # 3. Compute candidate signal
    res = compute_signal_fn(df)
    if isinstance(res, pd.Series):
        df[spec.signal_name] = res
    elif isinstance(res, pd.DataFrame):
        df = res

    if spec.signal_name not in df.columns:
        raise ValueError(f"Signal function did not produce expected column {spec.signal_name!r}")

    # 4. Standard alpha evaluation battery
    primary_fwd = f"fwd_ret_{spec.primary_horizon}d_pct"
    eval_report = evaluate_signal(
        df,
        signal_col=spec.signal_name,
        forward_col=primary_fwd,
        horizons=spec.horizons,
        run_backtest=True,
        run_neutralisation=True,
    )

    # 5. Failure classification & interpretation
    failure_class, verdict, next_moves = classify_result(eval_report, spec)
    # The class stays rule-based; the prose around it is written from the same
    # numbers, so a reader gets something they can act on rather than a table.
    interpretation = write_interpretation(eval_report, spec, failure_class,
                                          next_moves)

    # Where this sits among everything else asked of the same partition. Not a
    # veto — a label, so "significant" cannot quietly mean "significant among
    # the fifty things we tried" (the refactor plan §9).
    primary_t = (eval_report.get("predictive_content", {})
                 .get("primary_ic", {}).get("t_stat"))
    h_for_burden = store.get_hypothesis(spec.hypothesis_id)
    multiplicity = burden_mod.assess(
        primary_t, spec.partition,
        family=h_for_burden.family if h_for_burden else None).to_dict()
    runtime = time.time() - t0

    # 6. Immutable cryptographic manifest
    exp_id = f"EXP_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    manifest_data = build_manifest(
        hypothesis_id=spec.hypothesis_id,
        spec=spec.to_dict(),
        partition=spec.partition,
        result_metrics=eval_report.get("predictive_content", {}),
        dataset_version=spec.dataset_version,
        provider_used=provider_used,
        model_used=model_used,
        runtime_seconds=runtime,
        universe_name=spec.universe_name,
    )

    result_summary = {
        "exploration_id": exp_id,
        "hypothesis_id": spec.hypothesis_id,
        "signal_name": spec.signal_name,
        "partition": spec.partition,
        "role": spec.role,
        "failure_class": failure_class,
        "multiplicity": multiplicity,
        "verdict": verdict,
        "interpretation": interpretation,
        "suggested_next_moves": next_moves,
        "evaluation": eval_report,
        "manifest": manifest_data,
        "runtime_seconds": round(runtime, 2),
    }

    if not save_results:
        return result_summary

    # 7. Persistence to Research Store
    # A. Save Signal
    mech = eval_report.get("signal_mechanics", {})
    sig = Signal(
        name=spec.signal_name,
        owner_hypothesis_id=spec.hypothesis_id,
        definition=spec.question,
        coverage_profile={"mean_coverage": mech.get("mean_coverage_names", 0)},
        turnover_profile={
            "mean_turnover": mech.get("mean_turnover", 0),
            "autocorrelation_1d": mech.get("autocorrelation_1d", 0),
        },
    )
    save_signal(sig)

    # B. Save Exploration
    exp = Exploration(
        id=exp_id,
        hypothesis_id=spec.hypothesis_id,
        spec=spec.to_dict(),
        verdict=interpretation,
        failure_class=failure_class,
        signals_produced=[spec.signal_name],
        manifest_hash=manifest_data["hash"],
    )
    save_exploration(exp)

    # C. Save Evidence
    ev = Evidence(
        id=f"EV_{exp_id}",
        hypothesis_id=spec.hypothesis_id,
        signal_id=spec.signal_name,
        exploration_id=exp_id,
        role=spec.role,
        dataset_version=spec.dataset_version,
        partition=spec.partition,
        metrics={
            "mean_ic": eval_report.get("predictive_content", {}).get("primary_ic", {}).get("mean_ic"),
            # The same number the multiplicity assessment above was given, on
            # purpose. Without it `burden.partition_summary` reads None for
            # every exploratory result, scores it p=1.0, and reports that
            # nothing survives the false-discovery step — not as a finding,
            # but because the finding never reached it.
            "t_stat": primary_t,
            "spread_bps": eval_report.get("quantiles", {}).get("q5_spread_bps"),
            "monotonicity": eval_report.get("quantiles", {}).get("q5_monotonicity"),
            "failure_class": failure_class,
        },
        verdict_statement=interpretation,
        manifest_hash=manifest_data["hash"],
    )
    store.add_evidence(ev)

    # 8. Record partition consumption in Sample Budget Ledger
    split_manifest = splits.load(spec.dataset_version)
    consumed_quarters = [
        q["quarter"] for q in split_manifest.get("quarters", [])
        if q.get("set") == spec.partition
    ]
    h = store.get_hypothesis(spec.hypothesis_id)
    fam = h.family if h else "general"

    ledger.record_usage(
        hypothesis_id=spec.hypothesis_id,
        family=fam,
        role=spec.role,
        partition=spec.partition,
        quarters=consumed_quarters,
        manifest_hash=manifest_data["hash"],
        save_after=True,
    )

    # 9. Update Hypothesis status & Idea Graph
    if h:
        if failure_class == "SUCCESS":
            h.status = "validated" if spec.role == "confirmatory" else "promising"
        elif failure_class in ("NO_SIGNAL", "SIGNAL_TOO_SMALL", "HIGH_TURNOVER"):
            h.status = "rejected"

        # Attach suggested edge relations if any
        for move in next_moves:
            rel = move.get("relation")
            if rel:
                # Add proposed edge structure
                h.edges.append(Edge(target_id=f"proposed_{move['action']}", relation=rel))
        save_hypothesis(h)

    return result_summary
