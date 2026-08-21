"""The opportunity definition — frozen before anything is generated or judged.

The discretionary counterpart of `runner.spec.ExperimentSpec`, and it inherits
that module's two hard-won rules verbatim:

- **Partitions, never date ranges.** A hand-written window is how a holdout
  gets read twice.
- **A bar has to be able to fail.** H037 scored a PASS on -0.037% because its
  criterion was "both horizons negative" — a sign test wearing a number's
  clothes. Every threshold here has a floor below which it is not a bar.

WHAT IS DIFFERENT, AND WHY THE OLD VOCABULARY DOES NOT TRANSFER
`ExperimentSpec.pass_criterion` speaks in mean IC, quantile spread and
monotonicity. None of those is defined for a selector: there is no
cross-sectional score to rank, only a set of cases and a TAKE/SKIP/WATCH on
each. The quantity under test is a **lift** — how much better the selected
subset did than the opportunities it was selected from — and the criterion
vocabulary says so.

THE THREE CONTRASTS A CRITERION CAN NAME, AND WHY THE THIRD IS THE REAL ONE

    excess_lift        TAKE mean excess  -  all-candidates mean excess
    take_vs_skip       TAKE mean excess  -  SKIP mean excess
    lift_over_baseline TAKE mean excess  -  best quantitative baseline, at the
                                            same take rate

The first two can both be satisfied by a selector that has merely rediscovered
the generator's own score. Only the third asks the mission's question, which is
not "did the AI make money" but *did AI selection improve outcomes relative to
the opportunities it was given*. A definition that names only the first two is
accepted — it is a legitimate weaker claim — but `evaluate` reports all three
regardless, so the weaker bar cannot hide the stronger answer.

THE DECIDER IS NOT FROZEN THE WAY A FUNCTION IS
A signal is code: run it twice on the same frame and it is the same test. A
decider is a *prompt version, a model, and a case set*, and changing any of the
three while keeping the other two is a fresh test against the same sample with
nothing about it that looks like a second dispatch. `identity_hash` is the
triple, and `runner.burden` counts it.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from typing import Any

from ..persistence import ledger, store
from ..persistence.manifest import compute_payload_hash
from ..research_data import splits


VALID_PARTITIONS = ("train", "validation", "test", "forward")
VALID_ROLES = ("generation", "exploratory", "confirmatory")
VALID_SAMPLE_STRATEGIES = ("stratified_by_session", "random", "all")


class OpportunityValidationError(RuntimeError):
    pass


# Floors, in the units the contrast is measured in. Transaction costs are
# 0.40% round trip on this data — a measured, conservative number — so a
# selector lift inside 40 bps is not a result, whatever its t-statistic says.
# `lift_over_baseline` floors lower because it is a *difference of two
# selections* that both pay the same costs, so the cost floor does not apply to
# it twice; 20 bps is where the noise sits on a 500-case sample.
MIN_MEANINGFUL: dict[str, float] = {
    "min_excess_lift_bps": 40.0,
    "min_take_vs_skip_bps": 40.0,
    "min_lift_over_baseline_bps": 20.0,
    # Confidence that does not predict is not confidence. The slope is of mean
    # excess on stated confidence, in bps per unit; a flat selector scores 0.
    "min_calibration_slope_bps": 20.0,
}


def validate_pass_criterion(criterion: dict[str, float]) -> None:
    """Reject a bar that cannot fail, or that is a sign test (H037)."""
    if not criterion:
        raise OpportunityValidationError(
            "no pass criterion. Freeze one before any case is judged, in units "
            "of the effect — a bar written after the result is not a bar.")

    unknown = [k for k in criterion if k not in MIN_MEANINGFUL]
    if unknown:
        raise OpportunityValidationError(
            f"unrecognised pass-criterion keys {unknown}; expected any of "
            f"{sorted(MIN_MEANINGFUL)}. The signal vocabulary (mean IC, "
            f"quantile spread, monotonicity) is not defined for a selector.")

    for key, floor in MIN_MEANINGFUL.items():
        if key not in criterion:
            continue
        val = criterion[key]
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            raise OpportunityValidationError(f"{key} must be a number, got {val!r}")
        if val <= 0:
            raise OpportunityValidationError(
                f"{key}={val} is a sign test, not a bar. Any positive number "
                f"passes it, including one indistinguishable from zero (H037).")
        if val < floor:
            raise OpportunityValidationError(
                f"{key}={val} is below {floor}, which is inside transaction "
                f"costs or inside the noise on a case-budgeted sample. Set a "
                f"bar you would act on.")


DEFAULT_PASS_CRITERION: dict[str, float] = {
    "min_excess_lift_bps": 60.0,
    "min_lift_over_baseline_bps": 30.0,
}

# The context blocks a case may carry. Named here rather than in `case` so that
# a definition can be validated without building anything.
CONTEXT_BLOCKS = (
    "price_history",
    "location",
    "market",
    "sector",
    "relative_strength",
    "volatility_liquidity",
    "volume",
    "extension_contraction",
    "quant",
    "analogues",
)

DEFAULT_BASELINES = ("take_all", "random_matched", "top_n_by_score", "market")


@dataclass(frozen=True)
class OpportunityDef:
    """One immutable discretionary experiment, frozen before it runs.

    `anonymise` defaults True and should be left there. A model may simply
    remember what a named Indian equity did in a named quarter, and no amount
    of case hygiene closes that channel — the leak is in the weights, not in
    the frame. Under anonymisation the symbol and the calendar date never reach
    the decider and prices are rebased, so what is left is the judgement.
    Running the same definition with `anonymise=False` and differencing the two
    is a *measurement of memorisation*, and it is worth doing deliberately
    rather than discovering by accident.
    """
    id: str
    hypothesis_id: str
    idea: str

    # --- candidate generation: broad, and frozen ---
    generator: str = "liquid_universe"
    generator_params: dict[str, Any] = field(default_factory=dict)

    # --- which situations, and how many of them ---
    sample_n: int = 500
    sample_strategy: str = "stratified_by_session"
    sample_seed: int = 0

    # --- what the judge is shown ---
    context_blocks: tuple[str, ...] = CONTEXT_BLOCKS
    anonymise: bool = True
    history_sessions: int = 60
    n_analogues: int = 5

    # --- who judges, and how the verdict is scored ---
    prompt_version: str = "v1"
    provider: str = "api"
    model: str = ""
    baselines: tuple[str, ...] = DEFAULT_BASELINES
    horizons: tuple[int, ...] = (5, 10, 20)
    primary_horizon: int = 10
    entry_timing: str = "open"

    # --- the partition, and the bar ---
    dataset_version: str = "v1"
    partition: str = "train"
    role: str = "exploratory"
    pass_criterion: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_PASS_CRITERION))
    falsification_condition: str = (
        "TAKE mean excess return is at or below the mean over all candidates")
    created_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpportunityDef":
        d = dict(data)
        for key in ("context_blocks", "baselines", "horizons"):
            if isinstance(d.get(key), list):
                d[key] = tuple(d[key])
        return cls(**d)

    # -- hashes -------------------------------------------------------------

    @property
    def definition_hash(self) -> str:
        """Everything that decides *which cases exist and what they contain*.

        Deliberately excludes the decider and the bar: two definitions that
        differ only in which model judges them describe the same case set, and
        the case set is the expensive thing to build.
        """
        payload = {k: v for k, v in self.to_dict().items()
                   if k not in ("id", "created_at", "provider", "model",
                                "prompt_version", "pass_criterion",
                                "falsification_condition", "baselines")}
        return compute_payload_hash(payload)

    def identity_hash(self, case_set_hash: str) -> str:
        """What makes this a *distinct test* of the sample.

        Prompt, model and case set. Re-running an identical triple is a cache
        hit and costs nothing; changing any one of them is a new question asked
        of the same finite history, and `runner.burden` has to see it as one.
        """
        return compute_payload_hash({
            "prompt_version": self.prompt_version,
            "model": self.model or "<provider-default>",
            "case_set": case_set_hash,
        })

    def with_id(self, new_id: str) -> "OpportunityDef":
        return replace(self, id=new_id)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)


def validate(defn: OpportunityDef,
             budget_ledger: "ledger.SampleBudgetLedger | None" = None,
             check_budget: bool = True) -> None:
    """Everything that can be checked before a single case is built.

    `check_budget` is False during drafting and True at the reveal. The budget
    is not spent by defining an experiment or by judging its cases — only by
    looking at what happened next — so the ledger question is asked where the
    spending happens, not here.
    """
    if defn.partition not in VALID_PARTITIONS:
        raise OpportunityValidationError(
            f"invalid partition {defn.partition!r}; must be one of "
            f"{VALID_PARTITIONS}. Hand-written date ranges are forbidden.")
    if defn.role not in VALID_ROLES:
        raise OpportunityValidationError(
            f"invalid role {defn.role!r}; must be one of {VALID_ROLES}.")
    if defn.sample_strategy not in VALID_SAMPLE_STRATEGIES:
        raise OpportunityValidationError(
            f"invalid sample_strategy {defn.sample_strategy!r}; must be one of "
            f"{VALID_SAMPLE_STRATEGIES}.")
    if defn.entry_timing not in ("open", "close"):
        raise OpportunityValidationError(
            f"invalid entry_timing {defn.entry_timing!r}. A case is built "
            f"as-of the open, so a decision is tradeable at that open or at "
            f"that close; there is no intraday window on this path.")

    unknown_blocks = [b for b in defn.context_blocks if b not in CONTEXT_BLOCKS]
    if unknown_blocks:
        raise OpportunityValidationError(
            f"unknown context blocks {unknown_blocks}; expected any of "
            f"{list(CONTEXT_BLOCKS)}")

    if defn.sample_n < 1:
        raise OpportunityValidationError("sample_n must be at least 1")
    if defn.primary_horizon not in defn.horizons:
        raise OpportunityValidationError(
            f"primary_horizon {defn.primary_horizon} is not among horizons "
            f"{defn.horizons}; the bar would be measured on a horizon the "
            f"replay never scores.")

    # The purge is defined in sessions, so the longest horizon has to fit
    # inside the budget the split was frozen with, or the purge does not bind.
    manifest = splits.load(defn.dataset_version)
    splits.check_horizon(max(defn.horizons), manifest)

    validate_pass_criterion(defn.pass_criterion)

    # A definition names a registered hypothesis or it is refused. Resolving an
    # unknown id to a "general" family once granted it confirmatory access to
    # spent quarters, because nothing is recorded against a family that does
    # not exist — the exact inverse of the rule that ambiguous lineage blocks.
    h = store.get_hypothesis(defn.hypothesis_id)
    if h is None:
        raise OpportunityValidationError(
            f"hypothesis {defn.hypothesis_id!r} is not in the store. Lineage "
            f"cannot be established, so the data budget cannot be checked. "
            f"Register the hypothesis (and its edges) first — when lineage is "
            f"ambiguous, block.")

    if not check_budget:
        return

    target_quarters = [q["quarter"] for q in manifest.get("quarters", [])
                       if q.get("set") == defn.partition]
    lg = budget_ledger or ledger.SampleBudgetLedger.load()
    lg.enforce_permission(
        hypothesis_id=defn.hypothesis_id,
        family=h.family,
        role=defn.role,
        quarters=target_quarters,
        dataset_version=defn.dataset_version,
    )
