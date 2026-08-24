"""Outcome-free dossier qualification and signal authoring."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np
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
from ..core import config
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


def _sync_markdown_ledger(dossier: MechanismDossier) -> None:
    """Mirror a stable hypothesis ID into the authoritative Markdown ledger."""
    production_hypotheses = (
        config.METADATA_DIR / "research_store" / "hypotheses").resolve()
    if store.HYPOTHESES_DIR.resolve() != production_hypotheses:
        return
    import fcntl
    import re

    path = config.PROJECT_ROOT / "HYPOTHESES.md"
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            current = handle.read()
            if re.search(
                    rf"^##\s+{re.escape(dossier.hypothesis_id)}\b",
                    current, flags=re.MULTILINE):
                return
            handle.seek(0, 2)
            if current and not current.endswith("\n"):
                handle.write("\n")
            nearest = ", ".join(dossier.nearest_hypothesis_ids) or "none"
            handle.write(
                f"\n\n## {dossier.hypothesis_id} — {dossier.claim}\n\n"
                f"Status: **PROPOSED — OUTCOME UNTESTED, "
                f"{datetime.now():%Y-%m-%d}.** Registered by the research "
                "director before outcome access.\n\n"
                f"**Population.** {dossier.population}\n\n"
                f"**Mechanism.** {dossier.interpretation} Counterparty: "
                f"{dossier.counterparty}\n\n"
                f"**Frozen economic bar.** {dossier.min_effect_bps:.1f} bps. "
                f"Strongest baseline: {dossier.strongest_baseline}\n\n"
                f"**Lineage.** Nearest prior hypotheses: {nearest}.\n"
            )
            handle.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _promote_dossier(dossier: MechanismDossier) -> MechanismDossier:
    existing = store.get_hypothesis(dossier.hypothesis_id)
    provisional = not (
        dossier.hypothesis_id.startswith("H")
        and dossier.hypothesis_id[1:].isdigit()
    )
    if provisional:
        assigned = store.reserve_hypothesis_id(
            source_key=dossier.dossier_hash,
            statement=dossier.claim,
            family=dossier.family,
        )
        dossier = replace(dossier, hypothesis_id=assigned)
        existing = store.get_hypothesis(assigned)

    if existing is not None:
        if existing.statement != dossier.claim or existing.family != dossier.family:
            raise QualificationError(
                f"{dossier.hypothesis_id} already identifies a different hypothesis")
        _sync_markdown_ledger(dossier)
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
        tags=[
            "research-director", "outcome-free-registered",
            f"dossier:{dossier.dossier_id}",
            f"dossier-hash:{dossier.dossier_hash}",
        ],
    ))
    _sync_markdown_ledger(dossier)
    return dossier


def _author_source(
    spec: ExperimentSpec,
    dossier: MechanismDossier,
    panel: pd.DataFrame,
    provider: str,
    model: str | None,
    timeout_s: int,
    max_turns: int,
    agent_fn: Callable[[str, Path], agent.AgentResult] | None,
) -> tuple[str, str, str, str, str, str, tuple[str, ...], str, int,
           float | None]:
    import re
    from tempfile import TemporaryDirectory

    columns = [c for c in panel.columns
               if not str(c).startswith(("fwd_ret_", "excess_ret_"))]
    material_dissents = [
        d.to_dict() for d in dossier.dissents
        if d.severity in ("fatal", "material")
    ]
    dossier_for_author = dossier.to_dict()
    # The scout needs to know which outcomes exist; the code author does not.
    # Supplying label names here caused H051's author to reference one despite
    # the instruction not to, wasting a qualification attempt.
    dossier_for_author["available_observations"] = sorted(columns)
    prompt = f"""Author one deterministic, point-in-time cross-sectional signal
and its strongest simple outcome-blind baseline.

Question: {spec.question}
Signal name: {spec.signal_name}
Available columns: {', '.join(sorted(columns))}
Full frozen mechanism dossier:
{json.dumps(dossier_for_author, indent=2)}
Material or fatal review objections that must be resolved:
{json.dumps(material_dissents, indent=2)}

Return strict JSON with exactly these keys:
- source: Python source containing only optional pandas/numpy imports and one
  function named compute;
- baseline_source: separate Python source with the same compute signature,
  implementing the dossier's strongest simple baseline without outcomes and,
  for a selector, returning NaN outside the same registered eligible population;
- baseline_name: short Python identifier for that baseline, distinct from the
  signal name;
- eligibility_source: separate Python source with the same compute signature,
  returning a boolean Series for the dossier's exact registered population;
- eligibility_name: short Python identifier distinct from signal/baseline;
- signal_kind: "selector" for a discrete event/case rule, otherwise "dense";
- dissent_resolutions: one concise string per material/fatal objection stating
  the exact code or contract constraint that resolves it. Use the literal word
  UNRESOLVED when the supplied frame cannot resolve an objection.

Each source must define:

def compute(df: pandas.DataFrame) -> pandas.Series

Higher means more attractive. Use only the supplied frame. Do not inspect any
files, repository, network resource, outcomes, dates outside the frame, or
forward-return columns. Do not evaluate performance. Handle missing values.

Implement the population, trigger, point-in-time thresholds, participation
constraints, strongest-baseline distinction, and natural falsifiers in the
full dossier—not merely the one-sentence claim. For a selector, return NaN for
every non-candidate; zero is a valid score and must not mean "not selected".
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
    required = {
        "source", "baseline_source", "baseline_name", "signal_kind",
        "eligibility_source", "eligibility_name", "dissent_resolutions",
    }
    if set(payload) != required:
        raise QualificationError(
            "signal author JSON must contain exactly " + ", ".join(sorted(required)))
    if not all(isinstance(payload[name], str) for name in (
            "source", "baseline_source", "baseline_name", "signal_kind",
            "eligibility_source", "eligibility_name")):
        raise QualificationError("signal and baseline author fields must be strings")
    if payload["signal_kind"] not in ("dense", "selector"):
        raise QualificationError("signal_kind must be dense or selector")
    if not isinstance(payload["dissent_resolutions"], list) or not all(
            isinstance(item, str) for item in payload["dissent_resolutions"]):
        raise QualificationError("dissent_resolutions must be a list of strings")
    return (payload["source"], payload["baseline_source"],
            payload["baseline_name"], payload["eligibility_source"],
            payload["eligibility_name"], payload["signal_kind"],
            tuple(payload["dissent_resolutions"]), response.text[:2000],
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
    baseline_source: str | None = None,
    baseline_name: str | None = None,
    eligibility_source: str | None = None,
    eligibility_name: str | None = None,
    signal_kind: str | None = None,
    dissent_resolutions: tuple[str, ...] | None = None,
    dataset_version: str = "v1",
    timeout_s: int = 1800,
    max_turns: int = 40,
    output_path: Path | None = None,
    agent_fn: Callable[[str, Path], agent.AgentResult] | None = None,
    temp_dir: Path | None = None,
) -> tuple[QualificationArtifact, Path]:
    """Author a signal and freeze E0 reports without constructing outcomes."""
    if adjudication.get("deterministic_only"):
        raise QualificationError(
            "deterministic-only attack is diagnostic and cannot qualify a dossier")
    if not adjudication.get("approved"):
        raise QualificationError("dossier was not approved by the attack stage")
    if (not adjudication.get("independent_review_provider")
            and not adjudication.get("independent_attack_waiver")):
        raise QualificationError(
            "qualification requires an independent provider attack or an explicit "
            "recorded owner waiver")
    dossier = MechanismDossier.from_dict(adjudication["dossier"])
    if dossier.has_data_gap:
        raise QualificationError(
            "dossier still has missing observations: "
            + ", ".join(dossier.required_observations_absent))
    if not dossier.execution_semantics_explicit:
        raise QualificationError(
            "dossier predates explicit execution semantics; re-run discover/attack "
            "with required_feature_names, data_adapter, entry_price, outcome_kind "
            "and signal_kind frozen")
    if dossier.data_adapter != "daily_panel_asof_open":
        raise QualificationError(
            f"data adapter {dossier.data_adapter!r} is not executable by the "
            "daily signal director; build and register that adapter first")
    if dossier.entry_price not in ("open", "close"):
        raise QualificationError(
            f"entry price {dossier.entry_price!r} is unsupported by the daily adapter")
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
    missing_features = sorted(
        set(dossier.required_feature_names) - set(map(str, panel.columns)))
    if missing_features:
        raise QualificationError(
            "dossier is not data-ready on daily_panel_asof_open; missing required "
            "feature(s): " + ", ".join(missing_features))
    from ..research_data.catalogue import DEFAULT as feature_catalogue
    identity_columns = {"symbol", "date", "partition"}
    unsafe_features = []
    for name in dossier.required_feature_names:
        if name in identity_columns:
            continue
        if name not in feature_catalogue:
            unsafe_features.append(f"{name} (not catalogued)")
            continue
        feature = feature_catalogue[name]
        if (not feature.point_in_time or feature.stratification_only
                or feature.available_as_of == "future"):
            unsafe_features.append(
                f"{name} ({feature.available_as_of}, PIT={feature.point_in_time})")
    if unsafe_features:
        raise QualificationError(
            "required scoring features are not mechanically PIT-safe: "
            + ", ".join(unsafe_features))

    author_summary = "supplied frozen signal source"
    turns = 0
    cost = None
    dissent_resolutions = tuple(dissent_resolutions or ())
    if signal_source is None:
        (signal_source, baseline_source, baseline_name, eligibility_source,
         eligibility_name, signal_kind,
         dissent_resolutions, author_summary, turns, cost) = _author_source(
            spec, dossier, panel, provider, model, timeout_s, max_turns, agent_fn)
    else:
        if baseline_source is None or eligibility_source is None:
            raise QualificationError(
                "a supplied signal must also supply frozen baseline and eligibility "
                "sources; implicit fallbacks are prohibited")
        signal_kind = signal_kind or dossier.signal_kind
    assert signal_source is not None
    assert baseline_source is not None
    assert eligibility_source is not None
    baseline_name = baseline_name or "strongest_simple_baseline"
    eligibility_name = eligibility_name or "registered_eligibility"
    signal_kind = signal_kind or dossier.signal_kind
    if signal_kind != dossier.signal_kind:
        raise QualificationError(
            "authored signal_kind differs from the frozen dossier semantics")
    if not baseline_name.isidentifier() or baseline_name == signal_name:
        raise QualificationError(
            "baseline_name must be a valid identifier distinct from signal_name")
    if (not eligibility_name.isidentifier()
            or eligibility_name in (signal_name, baseline_name)):
        raise QualificationError(
            "eligibility_name must be a valid identifier distinct from signal/baseline")
    spec = replace(
        spec,
        entry_price=dossier.entry_price,
        outcome_kind=dossier.outcome_kind,
        signal_kind=signal_kind,
        baseline_name=baseline_name,
        eligibility_name=eligibility_name,
    )

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
        compute_baseline = _load_compute(
            baseline_source, f"{signal_name}_baseline", working_dir)
        compute_eligibility = _load_compute(
            eligibility_source, f"{signal_name}_eligibility", working_dir)
        first = compute(panel.copy())
        second = compute(panel.copy())
        baseline_first = compute_baseline(panel.copy())
        baseline_second = compute_baseline(panel.copy())
        eligibility_first = compute_eligibility(panel.copy())
        eligibility_second = compute_eligibility(panel.copy())
    finally:
        if manager is not None:
            manager.cleanup()
    if not isinstance(first, pd.Series):
        raise QualificationError("signal compute() must return a pandas Series")
    if not first.index.equals(panel.index):
        raise QualificationError("signal output is not aligned to the panel index")
    if not first.equals(second):
        raise QualificationError("signal compute() is not deterministic on identical input")
    if not isinstance(baseline_first, pd.Series):
        raise QualificationError("baseline compute() must return a pandas Series")
    if not baseline_first.index.equals(panel.index):
        raise QualificationError("baseline output is not aligned to the panel index")
    if not baseline_first.equals(baseline_second):
        raise QualificationError("baseline compute() is not deterministic on identical input")
    if not isinstance(eligibility_first, pd.Series):
        raise QualificationError("eligibility compute() must return a pandas Series")
    if not eligibility_first.index.equals(panel.index):
        raise QualificationError("eligibility output is not aligned to the panel index")
    if not eligibility_first.equals(eligibility_second):
        raise QualificationError(
            "eligibility compute() is not deterministic on identical input")
    if not pd.api.types.is_bool_dtype(eligibility_first):
        raise QualificationError("eligibility compute() must return a boolean Series")
    if eligibility_first.isna().any():
        raise QualificationError("eligibility compute() may not return missing values")
    if not pd.api.types.is_numeric_dtype(first):
        raise QualificationError("signal compute() must return a numeric Series")
    if not pd.api.types.is_numeric_dtype(baseline_first):
        raise QualificationError("baseline compute() must return a numeric Series")
    if not np.isfinite(first.dropna().to_numpy(dtype=float)).all():
        raise QualificationError("signal compute() returned a non-finite value")
    if not np.isfinite(baseline_first.dropna().to_numpy(dtype=float)).all():
        raise QualificationError("baseline compute() returned a non-finite value")
    if signal_kind == "selector" and first.notna().all():
        raise QualificationError(
            "selector signal must return NaN outside candidates; a dense zero floor "
            "would make non-candidates enter quantiles and the backtest")
    eligible = eligibility_first.astype(bool)
    if not eligible.any():
        raise QualificationError("frozen eligibility population is empty")
    if not baseline_first.notna().equals(eligible):
        raise QualificationError(
            "baseline must be defined exactly on the frozen eligible population")
    if signal_kind == "selector":
        candidate = first.notna()
        if (candidate & ~eligible).any():
            raise QualificationError(
                "selector contains candidates outside the frozen eligible population")
    elif not first.notna().equals(eligible):
        raise QualificationError(
            "dense signal must be defined exactly on the frozen eligible population")

    qualified_panel = panel.copy()
    qualified_panel[signal_name] = first
    qualified_panel[eligibility_name] = eligible
    assert_no_forward_labels(qualified_panel, context="qualified signal frame")
    structural = evaluate_structural_gate(
        qualified_panel,
        predictor_col=signal_name,
        horizon=dossier.expected_horizon_days,
        min_independent_blocks=8,
        cost_floor_bps=40.0,
        target_effect_bps=dossier.min_effect_bps,
        selector_mode=signal_kind == "selector",
    )
    preflight_result = preflight.run_preflight(
        qualified_panel, signal_name, spec=spec, save_results=True)

    unresolved = [
        item for item in dissent_resolutions if "UNRESOLVED" in item.upper()
    ]
    required_resolution_count = sum(
        dissent.severity in ("fatal", "material") for dissent in dossier.dissents)
    semantic_reasons = []
    if required_resolution_count and len(dissent_resolutions) < required_resolution_count:
        semantic_reasons.append(
            "Not every material/fatal attack dissent has a frozen resolution")
    if unresolved:
        semantic_reasons.extend(unresolved)
    semantic_check = {
        "passed": not semantic_reasons,
        "signal_kind": signal_kind,
        "data_adapter": dossier.data_adapter,
        "entry_price": dossier.entry_price,
        "outcome_kind": dossier.outcome_kind,
        "baseline_name": baseline_name,
        "eligibility_name": eligibility_name,
        "required_feature_names": list(dossier.required_feature_names),
        "dissent_resolution_count": len(dissent_resolutions),
        "reasons": semantic_reasons,
    }
    reasons = (list(structural.failure_reasons) + list(preflight_result.reasons)
               + semantic_reasons)
    approved = (structural.passed and preflight_result.passed
                and semantic_check["passed"])
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
        artifact_version=3,
        entry_price=semantic_check["entry_price"],
        outcome_kind=semantic_check["outcome_kind"],
        signal_kind=signal_kind,
        baseline_name=baseline_name,
        baseline_source=baseline_source,
        baseline_source_hash=source_hash(baseline_source),
        dissent_resolutions=dissent_resolutions,
        semantic_check=semantic_check,
        eligibility_name=eligibility_name,
        eligibility_source=eligibility_source,
        eligibility_source_hash=source_hash(eligibility_source),
    )
    path = save_qualification(artifact, path=output_path)
    return artifact, path
