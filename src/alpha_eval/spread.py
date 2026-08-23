"""The cheap gate an event family passes before it costs a single token.

THE QUESTION THIS ASKS, AND THE ONE IT REFUSES TO ASK
"Does this event predict returns?" is a test. It compares arms, it spends the
partition, and it goes through the dispatch gate. This module does not ask it.

It asks: **do outcomes after this event fan out more than they otherwise
would?** That is a second moment, not a first. It names no direction, ranks
nothing, and cannot produce a tradeable claim — which is exactly why it is
affordable to run on every candidate family before choosing between them.

WHY DISPERSION IS THE RIGHT GATE
A selector can only add value where outcomes differ. If every earnings event in
the panel is followed by the same return, there is nothing for a judge to
choose between and no prompt will invent any. If outcomes fan out, something is
separating them — and it may be findable, by code or by judgement.

The inverse is the trap the average-based check falls into: an event family
whose outcomes split into a strong up-group and a strong down-group has a mean
of zero and enormous opportunity. A gate built on means throws it away, which
is the single most likely way a good family gets killed before it is tried.

WHY IT MUST BE MATCHED WITHIN THE SESSION
Events cluster in time — results season, IPO waves, deal flow in bull markets.
An unmatched dispersion ratio would mostly measure that events happen on
exciting days. Every comparison here is against non-event names **in the same
session**, which is H020's lesson applied to a variance rather than a mean.

WHAT THE NUMBERS MEAN
    dispersion_ratio median per-session MAD after the event, over the same
                     figure for size-matched same-session non-events. 1.0 is
                     "this event tells you nothing about how uncertain the
                     next ten days are". Robust by necessity, not taste — see
                     `_dispersion`.
    tail_ratio       share of |excess| beyond 10%, same comparison. Fat tails
                     with an ordinary variance is a different, and often more
                     interesting, shape than a uniform widening.
    n_events, n_sessions, blocks — because a ratio on forty events spread over
                     forty sessions is not evidence of anything either.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TAIL_PCT = 10.0
# Below this a family has nothing to select on and no judge can rescue it.
# Above ~1.3 the family is worth the next stage. Between, it depends on n.
INTERESTING_DISPERSION_RATIO = 1.15


class SpreadError(RuntimeError):
    pass


def outcomes(bars: pd.DataFrame, horizon: int = 10) -> pd.DataFrame:
    """Forward excess return over the equal-weighted market, per name per day.

    The market leg is the same-session cross-sectional mean, so this is the
    zero line every contrast in the lab already uses.
    """
    d = bars[["symbol", "date", "close"]].sort_values(["symbol", "date"]).copy()
    d["fwd"] = d.groupby("symbol")["close"].shift(-horizon) / d["close"] - 1.0
    d = d.dropna(subset=["fwd"])
    d["excess_pct"] = 100.0 * (d["fwd"] - d.groupby("date")["fwd"].transform("mean"))
    return d[["symbol", "date", "excess_pct"]]


def check(events: pd.DataFrame, panel: pd.DataFrame, horizon: int = 10,
          label: str = "family", match_on: tuple[str, ...] = ()) -> dict[str, Any]:
    """Does this event family fan outcomes out, against its own sessions?

    `events` needs `symbol` and `date`. `panel` is the output of `outcomes`.

    `match_on` names extra `panel` columns the control must match on as well as
    the session — a volatility decile, a size tier. Without it the gate cannot
    tell "this event fans outcomes out" from "this event happens in names that
    were already jumpy", and for anything flow-related the second is the
    likelier story. Matching on a point-in-time volatility bucket is the
    cheapest way to find out, and it should be the default suspicion rather
    than an afterthought.
    """
    for col in ("symbol", "date"):
        if col not in events.columns:
            raise SpreadError(f"events need a {col!r} column")
    if events.empty:
        raise SpreadError(f"{label}: no events")

    ev = events[["symbol", "date"]].drop_duplicates().copy()
    ev["date"] = pd.to_datetime(ev["date"])
    p = panel.copy()
    p["date"] = pd.to_datetime(p["date"])

    missing = [c for c in match_on if c not in p.columns]
    if missing:
        raise SpreadError(f"match_on names columns absent from the panel: {missing}")
    marked = p.merge(ev.assign(_is_event=True), on=["symbol", "date"], how="left")
    # astype(bool) matters: fillna on a merged indicator leaves object dtype,
    # and `~` on object is a bitwise negation of ints, not a logical one.
    marked["_is_event"] = marked["_is_event"].fillna(False).astype(bool)

    # Only sessions carrying both an event and a control can say anything, for
    # the same reason a paired contrast needs both arms.
    g = marked.groupby("date")["_is_event"]
    usable = g.transform("any") & (~marked["_is_event"]).groupby(
        marked["date"]).transform("any")
    m = marked[usable]
    hit = m[m["_is_event"]]
    ctl = m[~m["_is_event"]]
    if hit.empty:
        raise SpreadError(f"{label}: no event landed on a session with controls")

    def _tail(x: pd.Series) -> float:
        return float((x.abs() > TAIL_PCT).mean())

    # ROBUST, NOT VARIANCE. Excess returns are heavy-tailed enough that the
    # mean of per-session sample variances is dominated by a handful of
    # sessions and does not converge: two independent random control draws of
    # the same panel scored 0.84 and 1.53 against each other. Measured here,
    # before this was changed. A median of per-session MADs scores the same
    # two draws at ~1.00, which is the only reason to trust anything below it.
    def _dispersion(frame: pd.DataFrame) -> float:
        per = frame.groupby("date")["excess_pct"].apply(
            lambda x: float((x - x.median()).abs().median()) if len(x) >= 2 else np.nan)
        per = per.dropna()
        return float(per.median()) if len(per) else np.nan

    # The control is drawn to the SAME per-session size as the event group: a
    # dispersion estimated from five observations behaves differently from one
    # estimated from a thousand, whatever the estimator.
    keys = ["date", *match_on]
    counts = hit.groupby(keys).size()
    rng = np.random.default_rng(0)
    ctl_by_key = {k: g for k, g in ctl.groupby(keys[0] if len(keys) == 1 else keys)}
    picks = []
    for key, k in counts.items():
        pool = ctl_by_key.get(key)
        if pool is None or len(pool) < k:
            continue
        picks.append(pool.iloc[rng.choice(len(pool), size=int(k), replace=False)])
    ctl_matched = pd.concat(picks) if picks else ctl.iloc[0:0]
    if ctl_matched.empty:
        raise SpreadError(f"{label}: no session had enough controls to match")

    d_hit, d_ctl = _dispersion(hit), _dispersion(ctl_matched)
    t_hit, t_ctl = _tail(hit["excess_pct"]), _tail(ctl_matched["excess_pct"])
    sessions = int(hit["date"].nunique())

    return {
        "family": label,
        "horizon": horizon,
        "matched_on": ",".join(match_on) or "session only",
        "n_events": int(len(hit)),
        "n_sessions": sessions,
        "independent_blocks": int(sessions / max(horizon, 1)),
        "events_per_session": round(len(hit) / max(sessions, 1), 2),
        "mad_event_pct": round(d_hit, 2),
        "mad_control_pct": round(d_ctl, 2),
        "dispersion_ratio": round(d_hit / d_ctl, 3) if d_ctl else None,
        "tail_event_pct": round(100 * t_hit, 2),
        "tail_control_pct": round(100 * t_ctl, 2),
        "tail_ratio": round(t_hit / t_ctl, 3) if t_ctl else None,
        "verdict": _read(d_hit / d_ctl if d_ctl else np.nan,
                         t_hit / t_ctl if t_ctl else np.nan, len(hit), sessions,
                         len(hit) / max(sessions, 1)),
    }


def _read(vr: float, tr: float, n_events: int, sessions: int,
          per_session: float) -> str:
    if not np.isfinite(vr):
        return "UNREADABLE — no control variance"
    if per_session < 2.0:
        return (f"UNREADABLE — {per_session:.2f} events per session. A "
                f"within-session dispersion needs at least two names in the "
                f"group, so most sessions contribute nothing and the ratio is "
                f"computed from whichever few happened to double up")
    if n_events < 200 or sessions < 40:
        return (f"TOO FEW — {n_events} events over {sessions} sessions is not "
                f"enough to read a ratio, whatever it says")
    if vr >= INTERESTING_DISPERSION_RATIO or (np.isfinite(tr) and tr >= 1.5):
        return ("WORTH THE NEXT STAGE — outcomes fan out after this event, so "
                "there is something for a selector to separate. Says nothing "
                "about direction and nothing about whether it is findable")
    if vr <= 1.03:
        return ("NOTHING TO SELECT ON — outcomes after this event are no more "
                "dispersed than an ordinary day. No prompt can create variation "
                "that is not there")
    return ("MARGINAL — mild widening. Worth a second look with a sharper event "
            "definition before it is worth cases")


def compare(reports: list[dict[str, Any]]) -> pd.DataFrame:
    """Families side by side, ordered by how much they fan outcomes out."""
    cols = ["family", "n_events", "n_sessions", "events_per_session",
            "mad_event_pct", "mad_control_pct", "dispersion_ratio",
            "tail_event_pct", "tail_ratio", "verdict"]
    return pd.DataFrame(reports)[cols].sort_values(
        "dispersion_ratio", ascending=False).reset_index(drop=True)


def event_persistence(events: pd.DataFrame, horizon: int,
                      max_lag: int | None = None) -> dict[str, Any]:
    """How much a session-paired contrast really loses to an h-day overlap.

    PLAN.md quotes `independent_blocks = sessions / horizon`, on the reasoning
    that consecutive ten-day windows share nine days. That is right for a
    *level* and wrong for a *paired difference*, because pairing inside the
    session cancels the common market factor that carries most of the overlap.

    What is left depends on one structural fact and no outcome at all: **do the
    same names recur on neighbouring sessions?** If today's event set and
    tomorrow's are disjoint, the two differences are built from different
    stocks and are very nearly independent however long the window. If they are
    the same names, the windows overlap and the differences do too.

    So this measures membership persistence and converts it, rather than
    assuming either extreme. A first attempt measured the autocorrelation of a
    *randomly reassigned* placebo and read ~0.02 at h=10 — but random
    reassignment destroys the persistence, which is exactly the quantity that
    matters, so the reading was an artefact of the placebo rather than a fact
    about the panel. Measured properly on the bulk-deal distribution set:
    19% of names recur one session later, decaying to 5% by ten.

    Returns the implied `overlap_share` for `paired_overlap`-style reasoning:
    the lag-1 membership overlap scaled by the share of the window two
    neighbouring sessions have in common.
    """
    max_lag = horizon if max_lag is None else max_lag
    by = events.groupby("date")["symbol"].apply(set).sort_index()
    if len(by) < max_lag + 2:
        raise SpreadError("too few sessions to measure persistence")

    overlaps = {}
    for lag in range(1, max_lag + 1):
        vals = []
        for i in range(len(by) - lag):
            a, b = by.iloc[i], by.iloc[i + lag]
            if a and b:
                vals.append(len(a & b) / min(len(a), len(b)))
        overlaps[lag] = float(np.mean(vals)) if vals else 0.0

    window_shared = (horizon - 1) / horizon if horizon > 1 else 0.0
    share = min(overlaps.get(1, 0.0), 1.0)
    return {
        "horizon": horizon,
        "sessions": int(len(by)),
        "median_names_per_session": int(np.median([len(s) for s in by])),
        "membership_overlap": {k: round(v, 3) for k, v in overlaps.items()},
        # The fraction of the paired difference that is shared with its
        # neighbour: only the recurring names carry the overlapping window.
        "overlap_share": round(share, 3),
        "implied_lag1_autocorr": round(share * window_shared, 3),
        "effective_sessions_multiplier": round(
            1.0 / (1.0 + share * (horizon - 1)), 3),
    }
