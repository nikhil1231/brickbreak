"""Experiment Specification and Pre-Dispatch Validation (the refactor plan §5.5).

Every exploration is defined by an immutable spec before it runs.
The spec names the question, dataset partition, signal, outcomes, pass criterion,
falsification condition, and is verified against the sample budget ledger
before execution.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..persistence import ledger, store
from ..research_data import splits


VALID_PARTITIONS = ("train", "validation", "test", "forward")
VALID_ROLES = ("generation", "exploratory", "confirmatory")


class SpecValidationError(RuntimeError):
    pass


# A bar has to be able to fail. "Both horizons negative" was satisfied by
# -0.037% — a number indistinguishable from zero — and H037 scored a PASS it
# had not earned. `family.PASS_CRITERION` got this right by demanding a
# *fraction of the exploration effect retained*; a threshold of zero is a sign
# test wearing a number's clothes.
MIN_MEANINGFUL = {
    "min_mean_ic": 0.005,        # below this an IC is not actionable
    "min_spread_bps": 10.0,      # 10 bps is inside one round trip of cost
    "min_monotonicity": 0.3,
    "min_retained_fraction": 0.2,
}


def validate_pass_criterion(criterion: dict[str, float]) -> None:
    """Reject a bar that cannot fail, or that is a sign test (H037)."""
    if not criterion:
        raise SpecValidationError(
            "no pass criterion. Freeze one before dispatch, in units of the "
            "effect — a bar written after the result is not a bar.")

    unknown = [k for k in criterion if k not in MIN_MEANINGFUL]
    if unknown:
        raise SpecValidationError(
            f"unrecognised pass-criterion keys {unknown}; expected any of "
            f"{sorted(MIN_MEANINGFUL)}")

    for key, floor in MIN_MEANINGFUL.items():
        if key not in criterion:
            continue
        val = criterion[key]
        if val is None or not isinstance(val, (int, float)):
            raise SpecValidationError(f"{key} must be a number, got {val!r}")
        if val <= 0:
            raise SpecValidationError(
                f"{key}={val} is a sign test, not a bar. Any positive number "
                f"passes it, including one indistinguishable from zero (H037).")
        if val < floor:
            raise SpecValidationError(
                f"{key}={val} is below {floor}, which is inside the noise or "
                f"inside transaction costs. Set a bar you would act on.")


@dataclass
class ExperimentSpec:
    """The contract defining an exploration run."""
    hypothesis_id: str
    question: str
    signal_name: str
    dataset_version: str = "v1"
    partition: str = "train"
    role: str = "exploratory"
    horizons: tuple[int, ...] = (5, 10, 20)
    primary_horizon: int = 10
    pass_criterion: dict[str, float] = field(
        default_factory=lambda: {
            "min_mean_ic": 0.015,
            "min_spread_bps": 30.0,
            "min_monotonicity": 0.60,
        }
    )
    falsification_condition: str = "mean IC <= 0 or Q5-Q1 spread <= 0"
    neutralisation_factors: list[str] = field(
        default_factory=lambda: ["beta", "sector", "size", "volatility", "momentum"]
    )
    backtest_top_k: int = 5
    backtest_holding: int = 10
    universe_name: str = "liquid_universe"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentSpec:
        d = dict(data)
        if isinstance(d.get("horizons"), list):
            d["horizons"] = tuple(d["horizons"])
        return cls(**d)


def validate_spec(
    spec: ExperimentSpec,
    budget_ledger: ledger.SampleBudgetLedger | None = None,
) -> None:
    """Pre-dispatch validation of an experiment specification.

    Checks:
    1. Partition is a valid named split, never a raw date range.
    2. Role is valid.
    3. Hypothesis exists in the store.
    4. Data budget permissions are satisfied via SampleBudgetLedger.
    """
    if spec.partition not in VALID_PARTITIONS:
        raise SpecValidationError(
            f"Invalid partition {spec.partition!r}; must be one of {VALID_PARTITIONS}. "
            f"Hand-written date ranges are forbidden."
        )

    if spec.role not in VALID_ROLES:
        raise SpecValidationError(
            f"Invalid role {spec.role!r}; must be one of {VALID_ROLES}."
        )

    validate_pass_criterion(spec.pass_criterion)

    # The hypothesis must be registered. Defaulting an unknown id to a
    # "general" family granted it confirmatory access to spent quarters,
    # because no prior read is recorded against a family that does not exist —
    # the exact inverse of the stated rule that ambiguous lineage blocks.
    h = store.get_hypothesis(spec.hypothesis_id)
    if h is None:
        raise SpecValidationError(
            f"hypothesis {spec.hypothesis_id!r} is not in the store. Lineage "
            "cannot be established, so the data budget cannot be checked. "
            "Register the hypothesis (and its edges) before dispatching an "
            "experiment against it — when lineage is ambiguous, block.")
    family = h.family

    # Get active quarters for this partition
    manifest = splits.load(spec.dataset_version)
    target_quarters = [
        q["quarter"] for q in manifest.get("quarters", [])
        if q.get("set") == spec.partition
    ]

    # Enforce data budget permission
    l = budget_ledger or ledger.SampleBudgetLedger.load()
    l.enforce_permission(
        hypothesis_id=spec.hypothesis_id,
        family=family,
        role=spec.role,
        quarters=target_quarters,
        dataset_version=spec.dataset_version,
    )

