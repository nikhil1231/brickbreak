"""Opening behaviour as a handful of nameable states, in parallel with the numbers.

WHY A SECOND REPRESENTATION
`behaviour.py` produces thirty continuous features. That is the right substrate
for a search and the wrong thing to hand a human, because the question that
actually needs answering — "is this the pattern my uncle is looking at?" — is
asked in words. This module assigns each morning, at each `t`, to one of a small
set of named states: persistent demand, fading spike, orderly breakout, rejected
breakout, heavy volume with no progress, selling absorbed and recovered, chaotic,
inert, or none of the above.

The two representations are run **in parallel and compared**, not one instead of
the other. If a continuous feature finds something the archetypes miss, the
archetypes are too coarse. If the archetypes find something the features miss,
the archetype is encoding an interaction worth writing down as a feature. Both
are informative and the disagreement is the interesting part.

HOW THE BANDS ARE SET, AND WHY THERE ARE NO NUMBERS IN THEM
Every condition below is a **tercile of a cross-sectional rank within the same
session**. There is no tunable threshold anywhere in this file: "high volume"
means "top third of mornings that day", full stop. That is deliberate and it is
the defence against the failure mode this exploration was warned about — a rule
that reads `volume > 8.7%, gap 0.63-0.91%` is fitting the sample, and a rule
that reads "top third by volume" cannot be, because there is nothing to fit.

The cost is real and worth stating: terciles are coarse, so a genuine effect
that lives in the top 5% will be diluted here and show up better in the
continuous pass. That is the trade, made knowingly.

PRECEDENCE, WHICH IS A MODELLING CHOICE AND NOT A FACT
A morning can satisfy several descriptions at once — a heavy-volume morning that
spiked and gave it back is both "fading spike" and, on a bad day, "chaotic".
Assignment is a priority ladder, so the *order* below carries meaning. It runs
from the most specific and most diagnostic states to the most generic:
`inert` first because a morning with almost no prints cannot be classified as
anything else honestly (this is the Phase 2.3 censoring problem in archetype
form), then the two-sided path states that require a specific sequence
(`absorbed_recovered`, `rejected_breakout`), then the volume-character states,
then the residual shape states. `unremarkable` is not a failure of the scheme;
it is most mornings, and forcing them into a named bucket would be the mistake.

WHAT THIS IS NOT
It is not a signal, a score, or a ranking. Assigning a name to a morning says
nothing about what happens next; that is measured separately, and on this data
it is measured **exploratorily** — the archetypes were designed after looking at
the same panel they are evaluated on. See H013.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# The order is the precedence ladder. See the module docstring.
ARCHETYPES = (
    "inert",
    "absorbed_recovered",
    "rejected_breakout",
    "persistent_demand",
    "fading_spike",
    "heavy_vol_no_progress",
    "orderly_breakout",
    "chaotic",
    "unremarkable",
)


@dataclass(frozen=True)
class ArchetypeConfig:
    """Band widths, not thresholds.

    `hi`/`lo` are quantiles of a cross-sectional rank, so 2/3 and 1/3 mean
    "top third" and "bottom third" of that session's mornings. `move_pct` is the
    one quantity expressed in price units rather than ranks, because "price came
    back above its open" is a statement about a level and not about a peer group;
    it is set at a round 0.2% and the sensitivity to it is reported by
    `band_sensitivity` rather than assumed away.
    """
    hi: float = 2 / 3
    lo: float = 1 / 3
    move_pct: float = 0.2
    min_ticks: int = 12


def _r(df: pd.DataFrame, col: str) -> pd.Series:
    """A cross-sectional rank column, or all-NaN if the feature is absent."""
    c = col if col.endswith("_xr") else col + "_xr"
    if c in df.columns:
        return df[c]
    return pd.Series(np.nan, index=df.index)


def assign(df: pd.DataFrame, cfg: ArchetypeConfig | None = None) -> pd.Series:
    """Label every (symbol, date, t) row with exactly one archetype.

    Uses only columns computed causally at `t`, so the label is available to a
    rule at `t` and carries no information from later in the window.
    """
    cfg = cfg or ArchetypeConfig()
    hi, lo, mv = cfg.hi, cfg.lo, cfg.move_pct

    vol = _r(df, "vol_rel_daily_pct")
    persist = _r(df, "active_bucket_frac")
    burst = _r(df, "vol_hhi")
    eff = _r(df, "abs_path_efficiency")
    churn = _r(df, "churn_vs_atr")
    prog = _r(df, "move_per_vol")
    rng_pos = _r(df, "range_pos")

    up = df["entry_vs_open_pct"]
    hi_vs_open = df["high_vs_open_pct"]
    lo_vs_open = df["low_vs_open_pct"]
    dd = df["dd_from_high_pct"]
    ticks = df["n_ticks_t"]

    out = pd.Series("unremarkable", index=df.index, dtype=object)

    # A morning with almost no prints has no behaviour to describe. Naming it
    # anything else would be reading the sampling rate as a market state — the
    # exact error that censored `om_low_vs_open_pct` in Phase 2.3.
    cond = {
        "inert": ticks < cfg.min_ticks,
        # Sellers pushed it below the open and it came back through: the
        # sequence, not the endpoint, is what makes this one interesting.
        "absorbed_recovered": (lo_vs_open < -mv) & (up > mv),
        # The mirror image: it traded up and lost the whole move.
        "rejected_breakout": (hi_vs_open > mv) & (up < -mv),
        # Unusual volume that kept arriving, with price holding its gain.
        "persistent_demand": (vol > hi) & (persist > hi) & (up > mv),
        # Unusual volume arriving in one burst, with the gain given back.
        "fading_spike": (vol > hi) & (burst > hi) & (dd < -mv) & (hi_vs_open > mv),
        # Plenty of volume and nowhere to show for it.
        "heavy_vol_no_progress": (vol > hi) & (prog < lo),
        # A clean directional path sitting near the top of its own range.
        "orderly_breakout": (eff > hi) & (up > mv) & (rng_pos > hi),
        # Movement without direction, relative to what this stock normally does.
        "chaotic": (eff < lo) & (churn > hi),
    }
    # Later names never overwrite earlier ones: precedence is the ladder above.
    assigned = pd.Series(False, index=df.index)
    for name in ARCHETYPES[:-1]:
        m = cond[name].fillna(False) & ~assigned
        out[m] = name
        assigned |= m
    return pd.Categorical(out, categories=list(ARCHETYPES))


def profile(df: pd.DataFrame, y: str, arch_col: str = "archetype",
            min_n: int = 200) -> pd.DataFrame:
    """What each archetype is, and what happened next. Descriptive, exploratory.

    Reports the outcome with date-clustered inference, because mornings sharing
    an archetype also tend to share a session — a market-wide heavy day fills the
    volume archetypes at once, and treating those rows as independent would
    inflate every t-statistic here by several times.
    """
    from .explore import cluster_stats
    rows = []
    for name, sub in df.groupby(arch_col, observed=True):
        if len(sub) < min_n:
            continue
        s = cluster_stats(sub[y], sub["date"])
        s |= {
            "archetype": str(name),
            "share_pct": round(len(sub) / len(df) * 100, 2),
            "med_vol_rel": round(float(sub["vol_rel_daily_pct"].median()), 2),
            "med_entry_vs_open": round(float(sub["entry_vs_open_pct"].median()), 3),
            "med_ticks": int(sub["n_ticks_t"].median()),
        }
        rows.append(s)
    out = pd.DataFrame(rows)
    return out.sort_values("mean", ascending=False).reset_index(drop=True) if len(out) else out


def band_sensitivity(df: pd.DataFrame, y: str,
                     cfgs: tuple[ArchetypeConfig, ...] | None = None) -> pd.DataFrame:
    """Re-label under wider and narrower bands and report how the outcomes move.

    The point of the whole scheme is that it should not depend on where the
    bands sit. This is the test of that claim rather than the assertion of it: an
    archetype whose outcome swings when "top third" becomes "top quarter" is
    describing a cut-point, not a behaviour, and should be read as noise.
    """
    cfgs = cfgs or (
        ArchetypeConfig(hi=0.60, lo=0.40, move_pct=0.15),
        ArchetypeConfig(),                                   # 2/3, 1/3, 0.20
        ArchetypeConfig(hi=0.75, lo=0.25, move_pct=0.30),
    )
    from .explore import cluster_stats
    rows = []
    for cfg in cfgs:
        lab = assign(df, cfg)
        for name in ARCHETYPES:
            m = lab == name
            if m.sum() < 200:
                continue
            s = cluster_stats(df.loc[m, y], df.loc[m, "date"])
            rows.append({"archetype": name, "hi": cfg.hi, "move_pct": cfg.move_pct,
                         "n": s["n"], "mean": s["mean"], "t": s["t"]})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    piv = out.pivot_table(index="archetype", columns="hi", values="mean")
    piv["range"] = piv.max(axis=1) - piv.min(axis=1)
    piv["sign_stable"] = (np.sign(piv.drop(columns="range")).nunique(axis=1) == 1)
    return piv.round(4)


def transitions(df: pd.DataFrame, arch_col: str = "archetype") -> pd.DataFrame:
    """How a morning's state changes as the window develops.

    The user's framing is that setup quality *evolves*: a morning may not look
    like anything at 60s and be unmistakable by 180s. A rule that evaluates at a
    single second cannot see that, and the transition matrix is the cheapest way
    to find out whether the states are stable enough for a fixed evaluation
    time to be defensible at all.
    """
    d = df[["symbol", "date", "t_offset_s", arch_col]].sort_values(
        ["symbol", "date", "t_offset_s"])
    nxt = d.groupby(["symbol", "date"], sort=False)[arch_col].shift(-1)
    m = nxt.notna()
    tab = pd.crosstab(d.loc[m, arch_col], nxt[m], normalize="index")
    return (tab * 100).round(1)
