"""Candidate generation — broad, high-recall, and deliberately not optimised.

A generator's job is to find situations *worth examining*. It is not the
trading decision, and the moment it becomes one the experiment is void: a
generator tuned until it looks profitable has already made the selection, and
whatever lift the discretionary layer then shows is measured against a baseline
that contains the answer.

So the bias here runs the other way from every screen this project has built
before. `families.opening_window.screener` exists to *narrow* — eight stages of
tradeability, size, liquidity, sector trend, stock trend and contraction, each
with a threshold. That is the right shape for a mechanical strategy and the
wrong shape here, because everything it excludes is a case the AI never gets to
judge and therefore never gets credit or blame for.

    A narrow generator flatters the selector by hiding its hard cases.

THE ONE FILTER THAT IS NOT A BELIEF
Liquidity. A name that trades a lakh a day cannot be bought at the price on the
tape, so including it does not test judgement, it tests the fill assumption.
That floor is universe construction, not opportunity definition, and it lives
in `research_data.frame.universe`.

WHAT A GENERATOR RETURNS
`symbol`, `date`, `generator_score` and `generator_reason`. The score is the
generator's own ordering — the thing `top_n_by_score` will be run against as a
baseline — and it may be constant when the generator has no opinion, which is
the honest value for `liquid_universe`. A constant score makes `top_n_by_score`
degenerate to a random pick at the same take rate, and `baselines` says so
rather than reporting a number that looks like a ranking result.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import numpy as np
import pandas as pd

from ..alpha_eval.guards import assert_no_forward_labels
from ..research_data import frame

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("symbol", "date", "generator_score", "generator_reason")

# Below this a fill at the printed price is fiction rather than an assumption.
# Universe construction, not a view about what is attractive.
DEFAULT_MIN_TV_CR = 1.0

# A name whose trailing indicators have not warmed up cannot be judged on chart
# structure: its 20-day return, its ATR ratio and its 52-week high are all NaN,
# and a case built on it is mostly empty fields. This binds hardest right after
# a data floor, where *every* name looks newly listed — at the 2020 bhavcopy
# floor the first sessions of the panel produce cases with no history at all.
# Also universe construction: it is a statement about what can be assessed, not
# about what is attractive.
DEFAULT_MIN_HISTORY_SESSIONS = 60


class GeneratorError(RuntimeError):
    pass


_REGISTRY: dict[str, Callable[..., pd.DataFrame]] = {}


def register(name: str):
    def _wrap(fn):
        _REGISTRY[name] = fn
        return fn
    return _wrap


def available() -> list[str]:
    return sorted(_REGISTRY)


def generate(panel: pd.DataFrame, generator: str,
             params: dict[str, Any] | None = None) -> pd.DataFrame:
    """Run a registered generator and check the contract it must honour."""
    if generator not in _REGISTRY:
        raise GeneratorError(
            f"unknown generator {generator!r}; registered: {available()}")
    # A generator that could see the outcome would be selecting on it, and the
    # whole distinction between generation and selection would collapse.
    assert_no_forward_labels(panel, context=f"candidate generation ({generator})")

    out = _REGISTRY[generator](panel, **(params or {}))
    missing = [c for c in REQUIRED_COLUMNS if c not in out.columns]
    if missing:
        raise GeneratorError(
            f"generator {generator!r} did not produce {missing}")
    out = out.dropna(subset=["symbol", "date"]).copy()
    out["date"] = pd.to_datetime(out["date"])
    logger.info("generator %s: %d candidates over %d sessions",
                generator, len(out), out["date"].nunique())
    return out.sort_values(["date", "symbol"]).reset_index(drop=True)


def _warmed_up(panel: pd.DataFrame, min_history: int) -> pd.Series:
    """Sessions this symbol has already printed inside the panel, before D."""
    return panel.groupby("symbol", sort=False).cumcount()


def _liquid(panel: pd.DataFrame, min_tv_cr: float,
            min_history: int = DEFAULT_MIN_HISTORY_SESSIONS) -> pd.DataFrame:
    d = panel
    if "median_tv_20_cr" in d.columns:
        d = d[d["median_tv_20_cr"] >= min_tv_cr]
    if min_history > 0:
        d = d.sort_values(["symbol", "date"])
        d = d[_warmed_up(d, min_history) >= min_history]
    if "is_etf" in d.columns:
        # ETFs pass any volatility-contraction screen trivially — near-zero
        # vol by design — and are not the thing being judged.
        d = d[~d["is_etf"].astype(bool)]
    if "series" in d.columns:
        d = d[d["series"] == "EQ"]
    return d


@register("liquid_universe")
def liquid_universe(panel: pd.DataFrame,
                    min_tv_cr: float = DEFAULT_MIN_TV_CR,
                    min_history: int = DEFAULT_MIN_HISTORY_SESSIONS
                    ) -> pd.DataFrame:
    """Every tradeable name, every session. The maximally broad definition.

    The right generator for an idea about *judgement in general* rather than
    about a particular setup, and the strictest test of a selector: there is no
    screen doing any of the work, so every point of lift belongs to the decider.
    Its `generator_score` is constant, because it genuinely has no opinion.
    """
    d = _liquid(panel, min_tv_cr, min_history)
    return pd.DataFrame({
        "symbol": d["symbol"].to_numpy(),
        "date": d["date"].to_numpy(),
        "generator_score": np.zeros(len(d)),
        "generator_reason": f"tradeable, median 20d value >= {min_tv_cr} Cr",
    })


@register("percentile_band")
def percentile_band(panel: pd.DataFrame, feature: str = "ret_20d",
                    lo: float = 0.0, hi: float = 0.2,
                    min_tv_cr: float = DEFAULT_MIN_TV_CR,
                    min_history: int = DEFAULT_MIN_HISTORY_SESSIONS,
                    ascending: bool = True) -> pd.DataFrame:
    """Names inside a cross-sectional percentile band of one feature, per session.

    The generic shape of "the population this idea is about": *the weakest
    fifth of the market today*, *the most extended tenth*. Ranked within the
    session, so the band means the same thing in a calm market and a violent
    one — an absolute cutoff would silently empty in one regime and flood in
    another, and the regime would then be doing the selecting.
    """
    d = _liquid(panel, min_tv_cr, min_history)
    if feature not in d.columns:
        raise GeneratorError(
            f"percentile_band needs {feature!r}, which is not in the panel")
    if not 0.0 <= lo < hi <= 1.0:
        raise GeneratorError(f"need 0 <= lo < hi <= 1, got lo={lo}, hi={hi}")
    d = d[d[feature].notna()].copy()
    pct = d.groupby("date")[feature].rank(pct=True, ascending=ascending)
    keep = (pct > lo) & (pct <= hi)
    d, pct = d[keep], pct[keep]
    return pd.DataFrame({
        "symbol": d["symbol"].to_numpy(),
        "date": d["date"].to_numpy(),
        # Distance into the band, so the baseline has something to rank on.
        "generator_score": (pct.to_numpy() - lo) / max(hi - lo, 1e-9),
        "generator_reason": f"{feature} in session percentile ({lo:.2f}, {hi:.2f}]",
    })


@register("feature_event")
def feature_event(panel: pd.DataFrame, feature: str = "gap_pct",
                  minimum: float | None = None, maximum: float | None = None,
                  score_by: str | None = None,
                  min_tv_cr: float = DEFAULT_MIN_TV_CR,
                  min_history: int = DEFAULT_MIN_HISTORY_SESSIONS
                  ) -> pd.DataFrame:
    """Names where a feature crosses an absolute threshold on the session.

    For ideas that are genuinely about a level rather than a rank — a gap of
    more than 5%, an inside day, a delivery percentage above half. Absolute
    cutoffs are regime-sensitive by construction, which is a real cost; use
    `percentile_band` unless the level is the point.
    """
    d = _liquid(panel, min_tv_cr, min_history)
    if feature not in d.columns:
        raise GeneratorError(
            f"feature_event needs {feature!r}, which is not in the panel")
    if minimum is None and maximum is None:
        raise GeneratorError("feature_event needs a minimum, a maximum, or both")
    d = d[d[feature].notna()].copy()
    if minimum is not None:
        d = d[d[feature] >= minimum]
    if maximum is not None:
        d = d[d[feature] <= maximum]
    score_col = score_by or feature
    if score_col not in d.columns:
        raise GeneratorError(f"score_by={score_col!r} is not in the panel")
    bounds = ", ".join(p for p in (
        f">= {minimum}" if minimum is not None else "",
        f"<= {maximum}" if maximum is not None else "") if p)
    return pd.DataFrame({
        "symbol": d["symbol"].to_numpy(),
        "date": d["date"].to_numpy(),
        "generator_score": d[score_col].to_numpy(dtype=float),
        "generator_reason": f"{feature} {bounds}",
    })


@register("contraction_breakout")
def contraction_breakout(panel: pd.DataFrame, **overrides: Any) -> pd.DataFrame:
    """The opening-window family's screen, as one generator among several.

    Kept because it encodes a great deal of measured work about what a
    contraction looks like on this tape, and because a *narrow* generator is
    the right control for a broad one: if the AI adds nothing on top of
    `liquid_universe` but adds a lot on top of this, the finding is that its
    judgement is complementary to a screen rather than a substitute for one.

    Imported lazily and by name. The family may not be imported from the lab at
    module scope — `tests/test_architecture.py` enforces the one-way
    dependency, and this is the one place the lab reaches back, through a
    registry entry that a definition has to ask for.
    """
    import importlib
    screener = importlib.import_module(
        "src.research.families.opening_window.screener")

    cfg = screener.ScreenConfig(**overrides) if overrides else screener.ScreenConfig()
    passed = screener.run_screen(panel, cfg)
    if isinstance(passed, tuple):
        passed = passed[0]
    d = passed
    # The screen is a funnel with no ordering of its own; rank the survivors by
    # how tight the contraction was, which is the family's own stated read.
    score = (-d["atr_ratio"] if "atr_ratio" in d.columns
             else pd.Series(np.zeros(len(d)), index=d.index))
    return pd.DataFrame({
        "symbol": d["symbol"].to_numpy(),
        "date": d["date"].to_numpy(),
        "generator_score": score.to_numpy(dtype=float),
        "generator_reason": "passed the contraction-breakout screen",
    })


# ---------------------------------------------------------------------------
# sampling — part of the frozen definition, never an afterthought
# ---------------------------------------------------------------------------

def sample(candidates: pd.DataFrame, n: int, strategy: str = "stratified_by_session",
           seed: int = 0, min_per_session: float = 2.0) -> pd.DataFrame:
    """Cut a broad candidate set down to the case budget.

    One model call per case makes the full set unaffordable — a broad generator
    over `train` is six figures of situations — so the budget is real and the
    sampler is part of the frozen definition rather than something applied
    afterwards to whatever came out.

    `stratified_by_session` is the default and matters more than it looks.
    Drawing 500 rows uniformly from a panel draws them disproportionately from
    sessions with a wide cross-section, which are not a random sample of
    sessions: breadth co-moves with regime. Spreading the draw across sessions
    first keeps the case set representative of the *calendar*, which is what
    the regime breakdown and the session-clustered inference both assume.

    The session *order* is shuffled as well as the names within each session.
    Round-robin over sorted sessions is only unbiased when the draw is large
    enough to reach every session; a small one silently takes the earliest
    sessions in the partition, which near a data floor means every case has
    indicators that have not warmed up yet.
    """
    if strategy == "all" or n >= len(candidates):
        out = candidates.reset_index(drop=True)
        _refuse_degenerate_shape(out, min_per_session)
        return out
    rng = np.random.default_rng(seed)
    if strategy == "random":
        idx = rng.choice(len(candidates), size=n, replace=False)
        out = candidates.iloc[np.sort(idx)].reset_index(drop=True)
        _refuse_degenerate_shape(out, min_per_session)
        return out
    if strategy != "stratified_by_session":
        raise GeneratorError(f"unknown sample strategy {strategy!r}")

    # Round-robin across sessions: every session contributes its first pick
    # before any session contributes its second, so thin sessions are not
    # squeezed out by wide ones.
    order = []
    for _, g in candidates.groupby("date", sort=True):
        pos = np.array(g.index.to_numpy(), copy=True)
        rng.shuffle(pos)
        order.append(pos)
    rng.shuffle(order)
    picked: list[int] = []
    depth = 0
    while len(picked) < n:
        added = False
        for pos in order:
            if depth < len(pos):
                picked.append(pos[depth])
                added = True
                if len(picked) >= n:
                    break
        if not added:
            break
        depth += 1
    out = candidates.loc[sorted(picked)].reset_index(drop=True)
    _refuse_degenerate_shape(out, min_per_session)
    return out


def _refuse_degenerate_shape(sampled: pd.DataFrame, min_per_session: float) -> None:
    """A draw of one case per session cannot measure anything. Caught here.

    `excess_lift` is takes against the pool *of the same session*, so a session
    holding one case compares that case with itself and contributes an exact
    zero. Round-robin over sorted sessions reaches every session before any
    session gets a second pick, and `train` holds 749 sessions against a
    500-case budget — so the default draw lands exactly on the degenerate
    shape, and does so silently, reporting 0.0 bps and a populated report.

    Verified against a planted 300 bps edge: 0.0 bps measured at 1 case per
    session, 166 at 2, 234 at 3. Raised rather than warned, because the failure
    is toward the null and therefore indistinguishable by inspection from the
    honest answer the lab expects.
    """
    if sampled.empty or "date" not in sampled.columns:
        return
    per = len(sampled) / max(sampled["date"].nunique(), 1)
    if per < min_per_session:
        raise GeneratorError(
            f"the draw put {per:.2f} cases in each of "
            f"{sampled['date'].nunique()} sessions, below the "
            f"{min_per_session} the session-paired contrast needs. Spreading "
            f"n cases over n sessions makes every per-session contrast "
            f"degenerate and the measured lift identically zero. Either draw "
            f"more cases or, at the same token cost, concentrate them: ~8 "
            f"cases across ~63 sessions has 99% power against a 150 bps edge "
            f"where 1 across 500 has none at all.")
