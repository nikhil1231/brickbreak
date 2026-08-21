"""Lab-level multiple comparisons (the refactor plan §9).

THE PROBLEM THIS EXISTS FOR
`discovery.permutation_null` already handles the maximum *within* one scan:
over 68 features the 95th percentile of max |t| under the null is ~3.4, not
1.96. But a lab that asks hundreds of cheap questions of 27 quarters is the
same machine running slowly. The 40th independent experiment against `train`
has roughly a 87% chance of producing at least one |t| > 1.96 by luck, and
nothing in the per-experiment report knows the other 39 happened.

So the count is kept, and the bar moves with it. This is not a veto — a result
below the adjusted bar is still recorded, still visible, still worth a
follow-up. It is a label, so that "significant" cannot silently mean
"significant among the fifty things we tried".

TWO NUMBERS ARE REPORTED, DELIBERATELY
- **Šidák** on the running count: the bar a *maximum* over n tests has to clear.
  Conservative, and correct if you are cherry-picking the best of n.
- **Benjamini-Hochberg**: what survives at a 10% false-discovery rate across
  everything tested on that partition. Less brutal, and the right frame when
  the question is "which of these are worth following up" rather than "is this
  one real".

The count is of *distinct signals scored against a partition*, taken from the
store. Voided explorations do not count — they were not evidence.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

from ..persistence import store

_N = NormalDist()


def two_sided_p(t: float) -> float:
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


def count_tests(partition: str, family: str | None = None) -> int:
    """Distinct signals already scored against this partition.

    Counted from non-void explorations, because a voided result was never
    evidence and should not raise the bar for anything else.
    """
    seen = set()
    for exp in store.list_explorations():
        spec = exp.spec or {}
        if spec.get("partition") != partition:
            continue
        if family:
            h = store.get_hypothesis(exp.hypothesis_id)
            if not h or h.family != family:
                continue
        seen.add((exp.hypothesis_id, spec.get("signal_name")))
    return len(seen)


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


def partition_summary(partition: str, q: float = 0.10) -> dict:
    """Everything tested against a partition, with FDR applied across the set.

    Counted on the same key as `count_tests`, and that is the whole point of
    the deduplication here. These two functions answer the same question —
    how much has this partition already absorbed — and a report where they
    disagree states a bar that nothing in the ledger ever had to clear. The
    store makes the failure concrete: eighteen re-runs of one development
    fixture read as eighteen tests, pushing the quoted Šidák bar to 3.02 when
    three distinct signals have actually been scored.

    Evidence is matched on its own partition as well as its exploration's.
    Forward-lane evidence points back at the *train* exploration that
    registered the signal and accrues a fresh row every time the lane is
    advanced, so without that second check a signal running forward would
    quietly inflate the burden on the partition it has already left.
    """
    by_exploration: dict[str, list] = {}
    for ev in store.list_evidence():
        by_exploration.setdefault(ev.exploration_id, []).append(ev)

    # Explorations arrive in id order, which is chronological, so re-running a
    # signal supersedes the earlier reading rather than joining it.
    latest: dict[tuple[str, str | None], dict] = {}
    for exp in store.list_explorations():
        spec = exp.spec or {}
        if spec.get("partition") != partition:
            continue
        for ev in by_exploration.get(exp.id, []):
            if ev.partition != partition:
                continue
            t = (ev.metrics or {}).get("ic_t_stat") or (ev.metrics or {}).get("t_stat")
            signal = spec.get("signal_name")
            latest[(exp.hypothesis_id, signal)] = {
                "exploration_id": exp.id,
                "hypothesis_id": exp.hypothesis_id,
                "signal": signal,
                "t_stat": t, "p_value": two_sided_p(t)}

    rows = list(latest.values())
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
