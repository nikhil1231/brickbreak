"""The replay — six phases, and a seal between the fourth and the fifth.

    freeze    definition.json + manifest, hashed
    generate  candidates.jsonl        broad, from the frozen generator
    build     cases.jsonl             label-free by construction
    decide    decisions.jsonl         AI + baselines; the future is not loaded
    reveal    outcomes.jsonl          <- the only phase that spends sample
    evaluate  report.json

WHY THIS IS SIX FUNCTIONS AND NOT ONE
Because the ordering *is* the experiment. MISSION §6 asks that a decision never
be revised after subsequent data is seen, and an instruction to that effect is
worth nothing — the useful version is a `reveal` that refuses to run unless the
decisions already on disk hash to what was committed. The phases are separate
processes' worth of separation: each writes its artefact and stops.

WHERE THE BUDGET IS SPENT, WHICH IS LATER THAN IT LOOKS
Not at `freeze`, and not at `decide`. A replay that is defined, generated,
built and judged has read nothing about what happened next; it has spent tokens
and compute, both of which are replaceable. `reveal` is the first moment the
partition is touched, so that is where `gate.enforce_dispatch_gate` and
`ledger.enforce_permission` fire. A replay abandoned before the reveal costs
nothing — the same economics as `runner.preflight`, and the reason both exist.

A REPLAY IS A TEST OF THE PARTITION AND IS COUNTED AS ONE
It writes an Evidence record with `signal_id = "replay:<id>"`, so
`runner.burden` counts it beside every signal ever scored and Benjamini-Hochberg
sees it without either knowing this package exists.

ARTEFACTS ARE JSONL, NOT PARQUET
Five hundred rows do not need parquet, and `tests/test_architecture.py` forbids
`read_parquet` outside `research_data` — a rule worth keeping intact for a
convenience that would buy nothing here.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from ..core import config
from ..persistence import Evidence, SampleBudgetLedger, build_manifest, store
from ..research_data import frame, splits
from ..runner import gate
from . import baselines, case as case_mod, decider as decider_mod
from . import evaluate as evaluate_mod
from . import generators, outcomes as outcomes_mod
from .decision import Decision, commit_hash, from_jsonl as decisions_from_jsonl
from .decision import to_jsonl as decisions_to_jsonl
from .opportunity import OpportunityDef, validate

logger = logging.getLogger(__name__)

REPLAYS_DIR = config.METADATA_DIR / "research_store" / "replays"

PHASES = ("freeze", "generate", "build", "decide", "reveal", "evaluate")


class ReplayError(RuntimeError):
    pass


class SealBrokenError(ReplayError):
    """The decisions on disk are not the decisions that were committed."""


@dataclass
class Replay:
    """The on-disk home of one discretionary experiment."""
    id: str
    root: Path

    # -- artefact paths ----------------------------------------------------
    @property
    def definition_path(self) -> Path: return self.root / "definition.json"
    @property
    def manifest_path(self) -> Path: return self.root / "manifest.json"
    @property
    def candidates_path(self) -> Path: return self.root / "candidates.jsonl"
    @property
    def cases_path(self) -> Path: return self.root / "cases.jsonl"
    @property
    def decisions_path(self) -> Path: return self.root / "decisions.jsonl"
    @property
    def seal_path(self) -> Path: return self.root / "seal.json"
    @property
    def outcomes_path(self) -> Path: return self.root / "outcomes.jsonl"
    @property
    def report_path(self) -> Path: return self.root / "report.json"

    # -- readers -----------------------------------------------------------
    def definition(self) -> OpportunityDef:
        if not self.definition_path.exists():
            raise ReplayError(f"{self.id} has no definition; run freeze first")
        return OpportunityDef.from_dict(
            json.loads(self.definition_path.read_text()))

    def candidates(self) -> pd.DataFrame:
        from io import StringIO
        if not self.candidates_path.exists():
            raise ReplayError(f"{self.id} has no candidates; run generate first")
        return pd.read_json(StringIO(self.candidates_path.read_text()),
                            orient="records", lines=True)

    def cases(self) -> list[case_mod.Case]:
        if not self.cases_path.exists():
            raise ReplayError(f"{self.id} has no cases; run build first")
        return case_mod.from_jsonl(self.cases_path.read_text())

    def decisions(self) -> list[Decision]:
        if not self.decisions_path.exists():
            raise ReplayError(f"{self.id} has no decisions; run decide first")
        return decisions_from_jsonl(self.decisions_path.read_text())

    def outcomes(self) -> pd.DataFrame:
        if not self.outcomes_path.exists():
            raise ReplayError(f"{self.id} has no outcomes; run reveal first")
        return outcomes_mod.from_jsonl(self.outcomes_path.read_text())

    def status(self) -> dict[str, Any]:
        done = {p: getattr(self, f"{k}_path").exists() for p, k in (
            ("freeze", "definition"), ("generate", "candidates"),
            ("build", "cases"), ("decide", "decisions"),
            ("reveal", "outcomes"), ("evaluate", "report"))}
        return {"id": self.id, "phases": done,
                "next": next((p for p, ok in done.items() if not ok), None)}


def _open(replay_id: str) -> Replay:
    return Replay(id=replay_id, root=REPLAYS_DIR / replay_id)


def get(replay_id: str) -> Replay:
    r = _open(replay_id)
    if not r.root.exists():
        raise ReplayError(f"no replay {replay_id!r} under {REPLAYS_DIR}")
    return r


def list_replays() -> list[Replay]:
    if not REPLAYS_DIR.exists():
        return []
    return [_open(p.name) for p in sorted(REPLAYS_DIR.iterdir(), reverse=True)
            if p.is_dir()]


# ---------------------------------------------------------------------------
# 1. freeze
# ---------------------------------------------------------------------------

def freeze(defn: OpportunityDef) -> Replay:
    """Write the definition down before anything can be influenced by a result.

    The budget is deliberately *not* checked here. Defining an experiment reads
    nothing; refusing at this point would only stop the definition being
    recorded, and an unrecorded definition is how a spec gets adjusted after
    the fact.
    """
    validate(defn, check_budget=False)
    rid = defn.id or f"RPL_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    defn = defn.with_id(rid)
    r = _open(rid)
    if r.definition_path.exists():
        raise ReplayError(
            f"{rid} is already frozen. A definition is immutable — start a new "
            f"replay rather than editing this one.")
    r.root.mkdir(parents=True, exist_ok=True)
    r.definition_path.write_text(defn.to_json() + "\n")
    logger.info("froze %s (definition %s)", rid, defn.definition_hash)
    return r


# ---------------------------------------------------------------------------
# 2. generate  &  3. build
# ---------------------------------------------------------------------------

def generate(replay_id: str, panel: pd.DataFrame | None = None) -> pd.DataFrame:
    """Run the frozen generator, then the frozen sampler. Label-free."""
    r = get(replay_id)
    d = r.definition()
    if panel is None:
        panel = frame.load_daily_panel(
            version=d.dataset_version, partition=d.partition,
            asof_open=True, include_context=True)

    cands = generators.generate(panel, d.generator, d.generator_params)
    picked = generators.sample(cands, n=d.sample_n, strategy=d.sample_strategy,
                               seed=d.sample_seed)
    r.candidates_path.write_text(
        picked.to_json(orient="records", lines=True, date_format="iso") + "\n")
    logger.info("%s: %d candidates sampled from %d over %d sessions",
                replay_id, len(picked), len(cands), picked["date"].nunique())
    return picked


def build(replay_id: str, panel: pd.DataFrame | None = None,
          bars: pd.DataFrame | None = None) -> list[case_mod.Case]:
    """Turn candidates into cases. Still label-free, and checked."""
    r = get(replay_id)
    d = r.definition()
    picked = r.candidates()
    if panel is None:
        panel = frame.load_daily_panel(
            version=d.dataset_version, partition=d.partition,
            asof_open=True, include_context=True)
    if bars is None:
        bars = frame.bars(version=d.dataset_version,
                          columns=["open", "high", "low", "close", "volume"])

    cases = case_mod.build(
        picked, panel, bars, blocks=d.context_blocks, anonymise=d.anonymise,
        history_sessions=d.history_sessions, n_analogues=d.n_analogues,
        analogue_horizon=d.primary_horizon, replay_id=replay_id)
    r.cases_path.write_text(case_mod.to_jsonl(cases))
    logger.info("%s: built %d cases (set hash %s)", replay_id, len(cases),
                case_mod.case_set_hash(cases))
    return cases


# ---------------------------------------------------------------------------
# 4. decide — the future is not loaded in this phase
# ---------------------------------------------------------------------------

def decide(replay_id: str, progress: Callable[[int, int], None] | None = None,
           fit_frame: pd.DataFrame | None = None, **kwargs: Any
           ) -> list[Decision]:
    """Judge every case, then run every baseline on the same cases, then seal.

    Nothing in this function calls `frame.forward_return`, and nothing it calls
    does either. The seal written at the end is what `reveal` checks.
    """
    r = get(replay_id)
    d = r.definition()
    cases = r.cases()
    if r.decisions_path.exists():
        raise ReplayError(
            f"{replay_id} already has committed decisions. Re-deciding would "
            f"be a second test of the same sample with nothing to show for it "
            f"— start a new replay if the prompt or the model has changed.")

    ai = decider_mod.decide(cases, provider=d.provider, model=d.model,
                            horizon=d.primary_horizon, replay_id=replay_id,
                            progress=progress, **kwargs)
    failures = decider_mod.failure_summary(ai)
    if failures["failed_pct"] > 20:
        logger.warning(
            "%s: %.1f%% of AI calls failed. A case that breaks a call is "
            "likelier to be an unusual case, which is the population under "
            "study — read the report against this number.",
            replay_id, failures["failed_pct"])

    if fit_frame is None and baselines.RANK_MODEL in d.baselines:
        fit_frame = _rank_fit_frame(d)

    arms = baselines.run(d.baselines, cases, ai, replay_id,
                         seed=d.sample_seed, fit_frame=fit_frame)
    everything = ai + arms
    r.decisions_path.write_text(decisions_to_jsonl(everything))

    ai_prompt_hashes = sorted({x.prompt_hash for x in ai})
    ai_prompt_versions = sorted({x.prompt_version for x in ai})
    seal = {
        "commit_hash": commit_hash(everything),
        "case_set_hash": case_mod.case_set_hash(cases),
        "prompt_hash": (ai_prompt_hashes[0] if len(ai_prompt_hashes) == 1
                        else ai_prompt_hashes),
        "prompt_version": (ai_prompt_versions[0] if len(ai_prompt_versions) == 1
                           else ai_prompt_versions),
        "model": d.model or "<provider-default>",
        "identity_hash": d.identity_hash(case_mod.case_set_hash(cases)),
        "n_decisions": len(everything),
        "ai_take_rate": round(baselines.take_rate(ai), 4),
        "failures": failures,
        "committed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    r.seal_path.write_text(json.dumps(seal, indent=2) + "\n")
    logger.info("%s: committed %d decisions, AI take rate %.1f%%",
                replay_id, len(everything), seal["ai_take_rate"] * 100)
    return everything


def _rank_fit_frame(d: OpportunityDef) -> pd.DataFrame:
    """Prior situations with resolved outcomes, for the rank-model baseline.

    Built from the *whole* dataset version rather than the evaluation
    partition: the baseline is entitled to learn from history the AI also
    implicitly has, and restricting it to the partition would weaken it — which
    would flatter the AI. Leakage is prevented by `resolved_by`, not by the
    partition, so every row it fits on had already printed its outcome.
    """
    panel = frame.load_daily_panel(version=d.dataset_version, partition=None,
                                   asof_open=True, include_context=True)
    bars = frame.bars(version=d.dataset_version, columns=["close"])
    b = bars[["symbol", "date", "close"]].dropna().sort_values(["symbol", "date"])
    cal = np.sort(b["date"].unique())
    pos = pd.Series(np.arange(len(cal)), index=cal)
    h = d.primary_horizon
    fwd = b.groupby("symbol", sort=False)["close"].shift(-h)
    fit = pd.DataFrame({
        "symbol": b["symbol"].to_numpy(),
        "date": b["date"].to_numpy(),
        "outcome_pct": ((fwd / b["close"] - 1.0) * 100.0).to_numpy(),
    })
    idx = fit["date"].map(pos).to_numpy()
    fit["resolved_by"] = cal[np.clip(idx + h, 0, len(cal) - 1)]
    fit = fit[fit["outcome_pct"].notna()]
    feats = [f for f in baselines.RANK_FEATURES if f in panel.columns]
    return fit.merge(panel[["symbol", "date"] + feats], on=["symbol", "date"],
                     how="inner")


# ---------------------------------------------------------------------------
# 5. reveal — the seal, the gate, and the ledger
# ---------------------------------------------------------------------------

def check_seal(replay_id: str) -> dict[str, Any]:
    """Refuse to go on unless the decisions are the ones that were committed."""
    r = get(replay_id)
    if not r.decisions_path.exists():
        raise SealBrokenError(
            f"{replay_id} has no committed decisions. The future cannot be "
            f"revealed before a decision exists — that ordering is the "
            f"experiment (MISSION §6).")
    if not r.seal_path.exists():
        raise SealBrokenError(
            f"{replay_id} has decisions but no seal, so there is nothing to "
            f"check them against. Treat this replay as compromised.")
    seal = json.loads(r.seal_path.read_text())
    actual = commit_hash(r.decisions())
    if actual != seal.get("commit_hash"):
        raise SealBrokenError(
            f"{replay_id}: the decisions on disk hash to {actual}, but "
            f"{seal.get('commit_hash')} was committed. A decision has been "
            f"changed, added or removed since. This replay cannot produce "
            f"evidence and a new one must be run.")
    return seal


def reveal(replay_id: str, enforce_budget: bool = True,
           bars: pd.DataFrame | None = None) -> pd.DataFrame:
    """Compute what happened. The first and only phase that spends sample."""
    r = get(replay_id)
    d = r.definition()
    seal = check_seal(replay_id)

    if enforce_budget:
        # Checked here rather than at freeze: this is the moment the partition
        # is read, and everything before it was replaceable.
        validate(d, check_budget=True)
        gate.enforce_dispatch_gate(_gate_spec(d))
        gate.reserve_outcome_access(
            _gate_spec(d), source_id=f"replay:{replay_id}",
            batch_id=f"REPLAY:{replay_id}")

    cases = r.cases()
    keys = pd.DataFrame({
        "case_id": [c.case_id for c in cases],
        "symbol": [c.symbol for c in cases],
        "date": [c.date for c in cases],
    })
    out = outcomes_mod.compute(
        keys, horizons=d.horizons, primary_horizon=d.primary_horizon,
        version=d.dataset_version, bars=bars, entry_timing=d.entry_timing)
    r.outcomes_path.write_text(outcomes_mod.to_jsonl(out))
    logger.info("%s: revealed outcomes for %d cases (identity %s)",
                replay_id, len(out), seal.get("identity_hash"))
    return out


def _gate_spec(d: OpportunityDef):
    """Present a replay to the dispatch gate as what it is: one more test."""
    from ..runner.spec import ExperimentSpec
    return ExperimentSpec(
        hypothesis_id=d.hypothesis_id, question=d.idea,
        signal_name=f"replay:{d.id}", dataset_version=d.dataset_version,
        partition=d.partition, role=d.role, horizons=tuple(d.horizons),
        primary_horizon=d.primary_horizon,
        # The gate reads the partition and the role; the signal criterion is
        # not meaningful for a selector and is not consulted by it.
        pass_criterion={"min_mean_ic": 0.015, "min_spread_bps": 30.0},
    )


# ---------------------------------------------------------------------------
# 6. evaluate
# ---------------------------------------------------------------------------

def evaluate(replay_id: str, record: bool = True,
             panel: pd.DataFrame | None = None) -> dict[str, Any]:
    """Compare the arms, against the bar that was frozen before the run."""
    r = get(replay_id)
    d = r.definition()
    check_seal(replay_id)

    meta = _case_strata(r, d, panel)
    report = evaluate_mod.evaluate(r.decisions(), r.outcomes(), d,
                                   cases_meta=meta)
    r.report_path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    if record:
        record_evidence(replay_id, report)
    logger.info("%s: %s — %s", replay_id,
                report["verdict"]["failure_class"],
                report["verdict"]["statement"])
    return report


def _case_strata(r: Replay, d: OpportunityDef,
                 panel: pd.DataFrame | None) -> pd.DataFrame:
    """Regime, sector, liquidity and size per case, for the breakdowns.

    Read from the panel rather than from the case, because a case under
    anonymisation deliberately does not carry the sector label or the absolute
    liquidity — and these are used to *stratify* a result, never to score one,
    which is the distinction the catalogue exists to enforce.
    """
    cols = ["mkt_regime", "sector", "size_tier", "median_tv_20_cr"]
    if panel is None:
        panel = frame.load_daily_panel(
            version=d.dataset_version, partition=d.partition,
            asof_open=True, include_context=True)
    have = [c for c in cols if c in panel.columns]
    if not have:
        return pd.DataFrame()
    cases = r.cases()
    keys = pd.DataFrame({
        "case_id": [c.case_id for c in cases],
        "symbol": [c.symbol for c in cases],
        "date": pd.to_datetime([c.date for c in cases]),
    })
    p = panel[["symbol", "date"] + have].copy()
    p["date"] = pd.to_datetime(p["date"])
    return keys.merge(p, on=["symbol", "date"], how="left").drop(
        columns=["symbol", "date"])


def record_evidence(replay_id: str, report: dict[str, Any]) -> Evidence:
    """File the result where `burden` and the ledger already look.

    `signal_id = "replay:<id>"` is the whole trick: `burden._collect_partition_tests`
    reads Evidence records, so a replay is counted beside every signal ever
    scored — Šidák and Benjamini-Hochberg both see it without either knowing
    this package exists.
    """
    r = get(replay_id)
    d = r.definition()
    seal = json.loads(r.seal_path.read_text())
    headline = report.get("headline", {})

    manifest = build_manifest(
        hypothesis_id=d.hypothesis_id, spec=d.to_dict(), partition=d.partition,
        result_metrics=headline, dataset_version=d.dataset_version,
        provider_used=d.provider, model_used=d.model or "<provider-default>",
        runtime_seconds=0.0, universe_name=d.generator)
    manifest["identity_hash"] = seal.get("identity_hash")
    manifest["prompt_hash"] = seal.get("prompt_hash")
    manifest["case_set_hash"] = seal.get("case_set_hash")
    r.manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n")

    ev = Evidence(
        id=f"EV_{replay_id}", hypothesis_id=d.hypothesis_id,
        signal_id=f"replay:{replay_id}", exploration_id=replay_id,
        role=d.role, dataset_version=d.dataset_version, partition=d.partition,
        metrics={
            "t_stat": headline.get("take_vs_skip_t"),
            "excess_lift_bps": headline.get("excess_lift_bps"),
            "take_vs_skip_bps": headline.get("take_vs_skip_bps"),
            "lift_over_baseline_bps": headline.get("lift_over_baseline_bps"),
            "take_rate_pct": headline.get("take_rate_pct"),
            "failure_class": report.get("verdict", {}).get("failure_class"),
        },
        verdict_statement=report.get("verdict", {}).get("statement", ""),
        manifest_hash=manifest["hash"],
    )
    store.add_evidence(ev)

    ledger = SampleBudgetLedger.load()
    manifest_split = splits.load(d.dataset_version)
    quarters = [q["quarter"] for q in manifest_split.get("quarters", [])
                if q.get("set") == d.partition]
    h = store.get_hypothesis(d.hypothesis_id)
    ledger.record_usage(
        hypothesis_id=d.hypothesis_id, family=h.family if h else "general",
        role=d.role, partition=d.partition, quarters=quarters,
        manifest_hash=manifest["hash"], save_after=True)
    return ev
