"""Outcome-free dossier qualification and signal authoring."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from ..alpha_eval.guards import assert_no_forward_labels
from ..contracts import (
    LifecycleState,
    LifecycleTracker,
    MechanismDossier,
    QualificationArtifact,
    source_hash,
)
from ..contracts.compiler import save_qualification
from ..firewall import evaluate_structural_gate
from ..persistence import Edge, Hypothesis, store
from ..research_data import frame
from . import agent, job, preflight
from .spec import ExperimentSpec


class QualificationError(RuntimeError):
    pass


def _canonical_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def load_adjudication(path: Path) -> tuple[dict[str, Any], MechanismDossier]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict) or "dossier" not in raw or "approved" not in raw:
        raise QualificationError(
            "qualify requires the adjudication JSON emitted by `attack`, not a raw dossier")
    dossier = MechanismDossier.from_dict(raw["dossier"])
    return raw, dossier


def _promote_dossier(dossier: MechanismDossier) -> MechanismDossier:
    existing = store.get_hypothesis(dossier.hypothesis_id)
    provisional = not (
        dossier.hypothesis_id.startswith("H")
        and dossier.hypothesis_id[1:].isdigit()
    )
    if provisional:
        dossier = replace(dossier, hypothesis_id=store.next_hypothesis_id())
        existing = None

    if existing is not None:
        if existing.statement != dossier.claim or existing.family != dossier.family:
            raise QualificationError(
                f"{dossier.hypothesis_id} already identifies a different hypothesis")
        return dossier

    edges = []
    for target in dossier.nearest_hypothesis_ids:
        if target != dossier.hypothesis_id and store.get_hypothesis(target):
            edges.append(Edge(target_id=target, relation="adjacent-to"))
    store.save_hypothesis(Hypothesis(
        id=dossier.hypothesis_id,
        title=dossier.claim[:100],
        statement=dossier.claim,
        rationale=(f"{dossier.causal_chain} Counterparty: {dossier.counterparty}; "
                   f"persistence: {dossier.counterparty_persistence_rationale}"),
        status="proposed",
        family=dossier.family,
        edges=edges,
        tags=["research-director", "outcome-free-qualified"],
    ))
    return dossier


def _author_source(
    spec: ExperimentSpec,
    panel: pd.DataFrame,
    provider: str,
    model: str | None,
    timeout_s: int,
    max_turns: int,
    agent_fn: Callable[[str, Path], agent.AgentResult] | None,
) -> tuple[str, str, int, float | None]:
    import re
    from tempfile import TemporaryDirectory

    columns = [c for c in panel.columns
               if not str(c).startswith(("fwd_ret_", "excess_ret_"))]
    prompt = f"""Author one deterministic, point-in-time cross-sectional signal.

Question: {spec.question}
Signal name: {spec.signal_name}
Available columns: {', '.join(sorted(columns))}

Return strict JSON with exactly one key, "source". Its value must be Python
source containing only optional pandas/numpy imports and exactly one function:

def compute(df: pandas.DataFrame) -> pandas.Series

Higher means more attractive. Use only the supplied frame. Do not inspect any
files, repository, network resource, outcomes, dates outside the frame, or
forward-return columns. Do not evaluate performance. Handle missing values.
"""
    with TemporaryDirectory(prefix="brickbreak_author_") as temp:
        cwd = Path(temp)
        response = (agent_fn(prompt, cwd) if agent_fn else agent.run_agent(
            prompt,
            cwd=cwd,
            timeout_s=timeout_s,
            max_turns=min(max_turns, 3),
            allowed_tools=(),
            model=model,
            provider=provider,
            sandbox="read-only",
        ))
    if not response.ok:
        raise QualificationError(
            response.stderr or response.text[:500] or "signal author failed")
    match = re.search(r"\{.*\}", response.text, re.DOTALL)
    if not match:
        raise QualificationError("signal author returned no JSON object")
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise QualificationError(f"signal author returned invalid JSON: {exc}") from exc
    if set(payload) != {"source"} or not isinstance(payload["source"], str):
        raise QualificationError("signal author JSON must contain only string field 'source'")
    return (payload["source"], response.text[:2000],
            response.num_turns, response.cost_usd)


def _load_compute(source: str, signal_name: str, temp_dir: Path):
    path = temp_dir / f"{signal_name}.py"
    path.write_text(source)
    return job.load_signal_fn(path)


def qualify_adjudication(
    adjudication: dict[str, Any],
    signal_name: str,
    provider: str = "claude",
    model: str | None = None,
    signal_source: str | None = None,
    dataset_version: str = "v1",
    timeout_s: int = 1800,
    max_turns: int = 40,
    output_path: Path | None = None,
    agent_fn: Callable[[str, Path], agent.AgentResult] | None = None,
    temp_dir: Path | None = None,
) -> tuple[QualificationArtifact, Path]:
    """Author a signal and freeze E0 reports without constructing outcomes."""
    if not adjudication.get("approved"):
        raise QualificationError("dossier was not approved by the attack stage")
    dossier = MechanismDossier.from_dict(adjudication["dossier"])
    if dossier.has_data_gap:
        raise QualificationError(
            "dossier still has missing observations: "
            + ", ".join(dossier.required_observations_absent))
    dossier = _promote_dossier(dossier)

    horizons = (dossier.expected_horizon_days,)
    spec = ExperimentSpec(
        hypothesis_id=dossier.hypothesis_id,
        question=dossier.claim,
        signal_name=signal_name,
        dataset_version=dataset_version,
        partition="train",
        role="exploratory",
        horizons=horizons,
        primary_horizon=horizons[0],
        pass_criterion={
            "min_mean_ic": 0.01,
            "min_spread_bps": max(10.0, dossier.min_effect_bps),
            "min_monotonicity": 0.50,
        },
        falsification_condition=(
            f"mean IC <= 0 or spread < {dossier.min_effect_bps:.1f} bps"),
        backtest_holding=horizons[0],
    )
    panel = frame.load_daily_panel(
        version=dataset_version, partition="train", asof_open=True,
        include_context=True)
    assert_no_forward_labels(panel, context="qualification panel")

    author_summary = "supplied frozen signal source"
    turns = 0
    cost = None
    if signal_source is None:
        signal_source, author_summary, turns, cost = _author_source(
            spec, panel, provider, model, timeout_s, max_turns, agent_fn)

    from tempfile import TemporaryDirectory
    if temp_dir is None:
        manager = TemporaryDirectory(prefix="brickbreak_qualify_")
        working_dir = Path(manager.name)
    else:
        manager = None
        working_dir = temp_dir
        working_dir.mkdir(parents=True, exist_ok=True)
    try:
        compute = _load_compute(signal_source, signal_name, working_dir)
        first = compute(panel.copy())
        second = compute(panel.copy())
    finally:
        if manager is not None:
            manager.cleanup()
    if not isinstance(first, pd.Series):
        raise QualificationError("signal compute() must return a pandas Series")
    if not first.index.equals(panel.index):
        raise QualificationError("signal output is not aligned to the panel index")
    if not first.equals(second):
        raise QualificationError("signal compute() is not deterministic on identical input")

    qualified_panel = panel.copy()
    qualified_panel[signal_name] = first
    assert_no_forward_labels(qualified_panel, context="qualified signal frame")
    structural = evaluate_structural_gate(
        qualified_panel,
        predictor_col=signal_name,
        horizon=dossier.expected_horizon_days,
        min_independent_blocks=8,
        cost_floor_bps=40.0,
    )
    preflight_result = preflight.run_preflight(
        qualified_panel, signal_name, spec=spec, save_results=True)

    reasons = list(structural.failure_reasons) + list(preflight_result.reasons)
    approved = structural.passed and preflight_result.passed
    tracker = LifecycleTracker(entity_id=dossier.hypothesis_id)
    tracker.transition(
        LifecycleState.DOSSIER, actor=dossier.proposer,
        input_hashes=(dossier.dossier_hash,),
        reason="Reviewed mechanism dossier admitted to qualification")
    tracker.transition(
        LifecycleState.DATA_READY, actor="data_catalogue",
        input_hashes=(dossier.dossier_hash,),
        reason="All required observations are present in research_data")
    if approved:
        tracker.transition(
            LifecycleState.PREFLIGHTED, actor="outcome_free_gates",
            input_hashes=(source_hash(signal_source),),
            reason="Structural and signal preflight gates passed")

    qualification_id = f"QUAL_{datetime.now():%Y%m%d_%H%M%S_%f}"
    artifact = QualificationArtifact(
        qualification_id=qualification_id,
        dossier=dossier.to_dict(),
        adjudication_hash=_canonical_hash(adjudication),
        signal_name=signal_name,
        signal_source=signal_source,
        signal_source_hash=source_hash(signal_source),
        question=dossier.claim,
        dataset_version=dataset_version,
        partition="train",
        horizons=horizons,
        primary_horizon=horizons[0],
        provider=(provider if author_summary != "supplied frozen signal source"
                  else "human_owner"),
        model=model or "cli-default",
        author_summary=author_summary,
        model_turns=turns,
        model_cost_usd=cost,
        structural_gate=structural.to_dict(),
        preflight=preflight_result.to_dict(),
        approved=approved,
        rejection_reasons=tuple(reasons),
        lifecycle=tracker.to_dict(),
    )
    path = save_qualification(artifact, path=output_path)
    return artifact, path
