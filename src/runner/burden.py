"""Lab-level multiple comparisons and batch correction (PLAN.md §5, §9, Stage H).

THE PROBLEM THIS EXISTS FOR
discovery.permutation_null already handles the maximum within one scan:
over 68 features the 95th percentile of max |t| under the null is ~3.4, not
1.96. But a lab that asks hundreds of cheap questions of 27 quarters is the
same machine running slowly. The 40th independent experiment against train
has roughly a 87% chance of producing at least one |t| > 1.96 by luck, and
nothing in the per-experiment report knows the other 39 happened.

NON-NEGOTIABLE INVARIANT (PLAN.md §4):
Two counters of the same quantity will drift apart. Any second count of
"tests absorbed" derives directly from the first, or does not exist.
`count_tests` and `partition_summary` derive from `_collect_partition_tests`
and can never disagree.

TWO MULTIPLICITY REGIMES:
1. Pre-registered batches: Benjamini-Hochberg applied across a frozen batch (Stage 3).
2. Partition burden: Šidák on the running count of distinct signals scored.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any

from ..persistence import store

_N = NormalDist()


def two_sided_p(t: float | None) -> float:
    """p-value for a t-statistic, using the normal approximation."""
    if t is None or not math.isfinite(t):
        return 1.0
    return 2.0 * (1.0 - _N.cdf(abs(float(t))))


def required_t(n_tests: int, alpha: float = 0.05) -> float:
    """The |t| a maximum over `n_tests` must clear (Šidák)."""
    n = max(1, int(n_tests))
    alpha_adj = 1.0 - (1.0 - alpha) ** (1.0 / n)
    return float(_N.inv_cdf(1.0 - alpha_adj / 2.0))


def prob_any_false_positive(n_tests: int, alpha: float = 0.05) -> float:
    """Chance of at least one spurious hit at `alpha` over n independent tests."""
    return 1.0 - (1.0 - alpha) ** max(1, int(n_tests))


def benjamini_hochberg(pvals: list[float], q: float = 0.10) -> list[bool]:
    """Which p-values survive at false-discovery rate `q`."""
    n = len(pvals)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: pvals[i])
    keep = [False] * n
    cutoff_rank = -1
    for rank, i in enumerate(order, start=1):
        if pvals[i] <= q * rank / n:
            cutoff_rank = rank
    for rank, i in enumerate(order, start=1):
        if rank <= cutoff_rank:
            keep[i] = True
    return keep


def _collect_partition_tests(partition: str, family: str | None = None) -> list[dict[str, Any]]:
    """Collect latest non-void test records for a partition.

    This is the single canonical counting and extraction function for
    partition-level multiplicity. Both `count_tests` and `partition_summary`
    derive from this, ensuring they cannot disagree.
    """
    by_exploration: dict[str, list] = {}
    for ev in store.list_evidence():
        if not ev.is_void:
            by_exploration.setdefault(ev.exploration_id, []).append(ev)

    latest: dict[tuple[str, str | None], dict[str, Any]] = {}
    for exp in store.list_explorations():
        if exp.is_void:
            continue
        spec = exp.spec or {}
        if spec.get("partition") != partition:
            continue
        if family:
            h = store.get_hypothesis(exp.hypothesis_id)
            if not h or h.family != family:
                continue

        signal = spec.get("signal_name")
        ev_list = by_exploration.get(exp.id, [])

        t_val = None
        for ev in ev_list:
            if ev.partition == partition:
                t_val = (ev.metrics or {}).get("ic_t_stat") or (ev.metrics or {}).get("t_stat")
                break

        latest[(exp.hypothesis_id, signal)] = {
            "exploration_id": exp.id,
            "hypothesis_id": exp.hypothesis_id,
            "signal": signal,
            "t_stat": t_val,
            "p_value": two_sided_p(t_val),
        }

    return list(latest.values())


def count_tests(partition: str, family: str | None = None) -> int:
    """Distinct signals already scored against this partition.

    Derives strictly from `_collect_partition_tests` so it can never disagree
    with `partition_summary`.
    """
    return len(_collect_partition_tests(partition, family=family))


@dataclass
class Burden:
    partition: str
    n_prior_tests: int
    n_including_this: int
    t_stat: float | None
    p_value: float
    naive_bar: float
    adjusted_bar: float
    clears_naive: bool
    clears_adjusted: bool
    prob_any_false_positive: float
    note: str

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        for k in ("p_value", "naive_bar", "adjusted_bar",
                  "prob_any_false_positive"):
            d[k] = round(float(d[k]), 4)
        return d


def assess(t_stat: float | None, partition: str, alpha: float = 0.05,
           family: str | None = None) -> Burden:
    """Put one result in the context of everything else asked of that partition."""
    prior = count_tests(partition, family=family)
    n = prior + 1
    bar = required_t(n, alpha)
    p = two_sided_p(t_stat) if t_stat is not None else 1.0
    clears_naive = bool(t_stat is not None and abs(t_stat) >= 1.96)
    clears_adj = bool(t_stat is not None and abs(t_stat) >= bar)

    if clears_adj:
        note = (f"clears the bar for a maximum over {n} tests on {partition} "
                f"(|t| >= {bar:.2f})")
    elif clears_naive:
        note = (f"clears |t|>1.96 but not the {n}-test bar of {bar:.2f}. "
                f"This is experiment {n} against {partition}; at 5% each, "
                f"{prob_any_false_positive(n, alpha) * 100:.0f}% of runs that "
                f"far would produce at least one hit by luck. Worth a "
                f"follow-up, not a promotion.")
    else:
        note = f"does not clear |t|>1.96, before any multiplicity adjustment"

    return Burden(
        partition=partition,
        n_prior_tests=prior,
        n_including_this=n,
        t_stat=None if t_stat is None else round(float(t_stat), 3),
        p_value=p,
        naive_bar=1.96,
        adjusted_bar=bar,
        clears_naive=clears_naive,
        clears_adjusted=clears_adj,
        prob_any_false_positive=prob_any_false_positive(n, alpha),
        note=note,
    )


def partition_summary(partition: str, q: float = 0.10) -> dict[str, Any]:
    """Everything tested against a partition, with FDR applied across the set."""
    rows = _collect_partition_tests(partition)
    keep = benjamini_hochberg([r["p_value"] for r in rows], q=q)
    for r, k in zip(rows, keep):
        r["survives_fdr"] = bool(k)
    return {
        "partition": partition,
        "n_tests": len(rows),
        "fdr_q": q,
        "n_surviving_fdr": sum(keep),
        "sidak_bar": round(required_t(max(1, len(rows))), 3),
        "results": rows,
    }


def assess_batch(batch_id: str, q: float = 0.10, alpha: float = 0.05) -> dict[str, Any]:
    """Evaluate Benjamini-Hochberg and Šidák corrections across a pre-registered batch (Stage H)."""
    batch = store.get_batch(batch_id)
    if not batch:
        raise KeyError(f"Batch {batch_id!r} not found in store.")

    by_exploration: dict[str, list] = {}
    for ev in store.list_evidence():
        if not ev.is_void:
            by_exploration.setdefault(ev.exploration_id, []).append(ev)

    results = []
    for spec_dict in batch.specs:
        hyp_id = spec_dict.get("hypothesis_id")
        sig_name = spec_dict.get("signal_name")
        part = spec_dict.get("partition", batch.partition)

        t_val = None
        exp_id = None
        for exp in store.list_explorations(hypothesis_id=hyp_id):
            if exp.is_void:
                continue
            e_spec = exp.spec or {}
            if e_spec.get("signal_name") == sig_name and e_spec.get("partition") == part:
                exp_id = exp.id
                for ev in by_exploration.get(exp.id, []):
                    if ev.partition == part:
                        t_val = (ev.metrics or {}).get("ic_t_stat") or (ev.metrics or {}).get("t_stat")
                        break
                if exp_id:
                    break

        p_val = two_sided_p(t_val)
        results.append({
            "hypothesis_id": hyp_id,
            "signal": sig_name,
            "exploration_id": exp_id,
            "t_stat": t_val,
            "p_value": p_val,
        })

    n = len(results)
    batch_sidak = round(required_t(max(1, n), alpha=alpha), 3)
    pvals = [r["p_value"] for r in results]
    keep = benjamini_hochberg(pvals, q=q)

    for r, k in zip(results, keep):
        r["survives_fdr"] = bool(k)
        t = r["t_stat"]
        r["clears_batch_sidak"] = bool(t is not None and abs(t) >= batch_sidak)

    return {
        "batch_id": batch.batch_id,
        "batch_hash": batch.batch_hash,
        "partition": batch.partition,
        "batch_size": n,
        "fdr_q": q,
        "batch_sidak_bar": batch_sidak,
        "n_surviving_fdr": sum(keep),
        "results": results,
    }
