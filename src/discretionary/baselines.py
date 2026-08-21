"""The alternatives the AI has to beat, on the exact same cases.

MISSION §5 is the sharpest constraint in this project: the question is not
whether AI selection makes money, it is *whether AI selection improves outcomes
relative to the opportunities it was given*. That comparison is only meaningful
if the alternatives see the identical case set, so every baseline here takes
the same `cases` list the AI took and returns one Decision per case.

MATCHED TAKE RATE, WHICH IS THE WHOLE DESIGN
A selector that takes 12% of what it is shown cannot be compared to one that
takes everything: selectivity and skill are confounded, and the more selective
arm wins any contest where the pool is better than average. So `random_matched`
and `top_n_by_score` are run at *the AI's own realised take rate*. If the AI
took 61 of 500, they take 61 of 500 too, and the only difference left is which
61.

`take_all` deliberately does not match. It is the pool itself — the thing the
lift is measured against — and its take rate is 100% by definition.

THE MARKET IS NOT A DECIDER, AND PRETENDING OTHERWISE WOULD DOUBLE-COUNT IT
MISSION lists market exposure among the baselines. It is not implemented as an
arm here because every outcome in this package is already measured as *excess*
return over the equal-weighted market compounded across the same holding
window. The market baseline is therefore the zero line of every contrast, which
is stronger than an arm — you cannot forget to run it. `evaluate` says so where
the numbers are reported.

WHY `top_n_by_score` MATTERS MORE THAN IT LOOKS
It is the quantitative screen the lab already knows how to build, and the
mission's real question is whether contextual judgement adds anything on top of
it. If the AI cannot beat a ranking on the generator's own score, the honest
finding is that the scanner already captured the predictive value — which
MISSION §8 lists as one of the conclusions this lab must be able to reach.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import numpy as np
import pandas as pd

from .case import Case
from .decision import Decision

logger = logging.getLogger(__name__)

TAKE_ALL = "take_all"
RANDOM_MATCHED = "random_matched"
TOP_N_BY_SCORE = "top_n_by_score"
RANK_MODEL = "rank_model"

BASELINES = (TAKE_ALL, RANDOM_MATCHED, TOP_N_BY_SCORE, RANK_MODEL)

# Features the rank model is allowed. Few, point-in-time, and fixed: a baseline
# whose feature set is tuned against the outcome stops being a baseline.
RANK_FEATURES = ("ret_20d", "rs_20d_vs_mkt", "rs_60d_vs_mkt",
                 "atr_ratio_pctile", "bb_width_pctile", "dist_52w_high",
                 "deliv_pct")


class BaselineError(RuntimeError):
    pass


def take_rate(decisions: list[Decision]) -> float:
    """Share of cases taken. WATCH is not a position (see `Decision.took`)."""
    if not decisions:
        return 0.0
    return sum(d.took for d in decisions) / len(decisions)


def _decide(case: Case, replay_id: str, name: str, take: bool,
            confidence: float, rationale: str) -> Decision:
    return Decision(
        case_id=case.case_id, replay_id=replay_id, decider=name,
        action="TAKE" if take else "SKIP", confidence=confidence,
        case_hash=case.case_hash, model=name, rationale=rationale)


def _take_top(values: np.ndarray, n_take: int) -> np.ndarray:
    """Boolean mask marking the `n_take` largest values. Ties broken by order."""
    mask = np.zeros(len(values), dtype=bool)
    if n_take <= 0:
        return mask
    n_take = min(n_take, len(values))
    order = np.argsort(-values, kind="stable")
    mask[order[:n_take]] = True
    return mask


# ---------------------------------------------------------------------------
# the arms
# ---------------------------------------------------------------------------

def take_all(cases: list[Case], replay_id: str, **_: Any) -> list[Decision]:
    """The pool itself. Every lift in the report is measured against this."""
    return [_decide(c, replay_id, TAKE_ALL, True, 1.0,
                    "takes every candidate the generator produced")
            for c in cases]


def random_matched(cases: list[Case], replay_id: str, n_take: int = 0,
                   seed: int = 0, **_: Any) -> list[Decision]:
    """A seeded coin at the AI's take rate — the null hypothesis of selection.

    The arm that says what "picking 61 of 500" is worth when the picking
    carries no information. An AI that cannot beat this has not selected.
    """
    rng = np.random.default_rng(seed)
    mask = _take_top(rng.random(len(cases)), n_take)
    return [_decide(c, replay_id, RANDOM_MATCHED, bool(m), 0.5,
                    f"seeded random selection at a matched {n_take}/{len(cases)} rate")
            for c, m in zip(cases, mask)]


def top_n_by_score(cases: list[Case], replay_id: str, n_take: int = 0,
                   **_: Any) -> list[Decision]:
    """The generator's own ordering, at the AI's take rate.

    Selected *within each session*, not globally: a global cut on a score whose
    scale drifts with the regime would concentrate the whole arm in a handful
    of sessions, and then the comparison would be about timing rather than
    about selection.

    When the generator has no opinion — `liquid_universe` scores everything
    zero — this degenerates to an arbitrary pick at the same rate. That is
    reported rather than hidden, because a degenerate baseline that looks like
    a ranking result is worse than no baseline.
    """
    scores = np.array([c.generator_score for c in cases], dtype=float)
    degenerate = float(np.nanstd(scores)) == 0.0
    if degenerate:
        logger.warning(
            "top_n_by_score: the generator's score is constant, so this arm is "
            "an arbitrary pick, not a ranking. Read it as a second random arm.")

    df = pd.DataFrame({
        "i": np.arange(len(cases)),
        "date": [c.date for c in cases],
        "score": scores,
    })
    # Spread the budget across sessions in proportion to their share of cases,
    # then top up the largest remainders so the total matches exactly.
    take = np.zeros(len(cases), dtype=bool)
    groups = list(df.groupby("date", sort=True))
    shares = np.array([len(g) for _, g in groups], dtype=float)
    exact = shares / max(shares.sum(), 1) * n_take
    alloc = np.floor(exact).astype(int)
    for j in np.argsort(-(exact - alloc), kind="stable")[:n_take - alloc.sum()]:
        alloc[j] += 1
    for (_, g), k in zip(groups, alloc):
        idx = g["i"].to_numpy()
        take[idx[_take_top(g["score"].to_numpy(), int(k))]] = True

    note = ("the generator's score has no variation, so this is an arbitrary "
            "pick at a matched rate" if degenerate
            else "top of the generator's own score, within each session")
    return [_decide(c, replay_id, TOP_N_BY_SCORE, bool(m), 0.5, note)
            for c, m in zip(cases, take)]


def rank_model(cases: list[Case], replay_id: str, n_take: int = 0,
               fit_frame: pd.DataFrame | None = None, **_: Any) -> list[Decision]:
    """A least-squares rank model, refit walk-forward and never in sample.

    The strongest of the simple alternatives, and the one whose construction is
    easiest to get quietly wrong. Two rules make it honest:

    **It never sees a case's own outcome, or any outcome that had not printed
    by the case's own date.** `fit_frame` carries `resolved_by`, so a row from
    five sessions before a case is excluded at a ten-session horizon — its
    window overlaps the case. Filtering on the row's *date* instead of on when
    its outcome landed is the subtle version of this leak, and it is the one
    that looks fine.

    **It is refit as the case set advances.** A single fit at the start would
    be stale for later cases, and a stale baseline is a *weak* baseline — which
    flatters the AI. The bias has to run the other way.
    """
    if fit_frame is None or fit_frame.empty:
        logger.warning("rank_model: no fit frame supplied; arm skipped")
        return [_decide(c, replay_id, RANK_MODEL, False, 0.0,
                        "no fitting data was available") for c in cases]

    feats = [f for f in RANK_FEATURES if f in fit_frame.columns]
    if not feats:
        raise BaselineError(
            f"rank_model needs at least one of {RANK_FEATURES} in the fit frame")

    cd = pd.DataFrame({
        "i": np.arange(len(cases)),
        "date": pd.to_datetime([c.date for c in cases]),
        "symbol": [c.symbol for c in cases],
    })
    # Refit at each quarter boundary the case set touches: often enough that
    # the arm tracks the regime, rarely enough to stay cheap.
    cd["period"] = cd["date"].dt.to_period("Q")
    ff = fit_frame.copy()
    ff["resolved_by"] = pd.to_datetime(ff["resolved_by"])

    pred = np.full(len(cases), np.nan)
    for period, g in cd.groupby("period", sort=True):
        cutoff = g["date"].min()
        train = ff[ff["resolved_by"] < cutoff].dropna(
            subset=feats + ["outcome_pct"])
        if len(train) < 200:
            logger.info("rank_model: %s has only %d resolved rows before %s; "
                        "arm abstains for this period", period, len(train),
                        cutoff.date())
            continue
        mu = train[feats].mean()
        sd = train[feats].std().replace(0.0, np.nan)
        X = ((train[feats] - mu) / sd).fillna(0.0).to_numpy()
        X = np.column_stack([np.ones(len(X)), X])
        y = train["outcome_pct"].to_numpy(dtype=float)
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)

        rows = ff.merge(g[["i", "date", "symbol"]], on=["date", "symbol"],
                        how="right").set_index("i").reindex(g["i"])
        Z = ((rows[feats] - mu) / sd).fillna(0.0).to_numpy()
        pred[g["i"].to_numpy()] = np.column_stack([np.ones(len(Z)), Z]) @ beta

    scored = np.where(np.isfinite(pred), pred, -np.inf)
    mask = _take_top(scored, n_take)
    return [_decide(c, replay_id, RANK_MODEL, bool(m), 0.5,
                    "walk-forward least-squares rank model on fixed features")
            for c, m in zip(cases, mask)]


_REGISTRY: dict[str, Callable[..., list[Decision]]] = {
    TAKE_ALL: take_all,
    RANDOM_MATCHED: random_matched,
    TOP_N_BY_SCORE: top_n_by_score,
    RANK_MODEL: rank_model,
}


def available() -> list[str]:
    return list(BASELINES)


def run(names: tuple[str, ...], cases: list[Case], ai_decisions: list[Decision],
        replay_id: str, seed: int = 0,
        fit_frame: pd.DataFrame | None = None) -> list[Decision]:
    """Every requested arm, matched to the AI's realised take rate."""
    rate = take_rate(ai_decisions)
    n_take = int(round(rate * len(cases)))
    logger.info("baselines matched to a take rate of %.1f%% (%d of %d)",
                rate * 100, n_take, len(cases))

    out: list[Decision] = []
    for name in names:
        if name not in _REGISTRY:
            raise BaselineError(
                f"unknown baseline {name!r}; registered: {available()}")
        out.extend(_REGISTRY[name](cases, replay_id, n_take=n_take, seed=seed,
                                   fit_frame=fit_frame))
    return out
