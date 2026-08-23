"""The family's measurements, runnable from the repository rather than a script.

Everything in FINDINGS.md for this family was produced here. That matters more
than it sounds: a number in a document whose only source is a scratch file is
a number nobody can re-derive after the file is gone, and this project's
standing rule is that a measurement has to stay reachable.

Nothing here reads an outcome mean or compares arms in a way that could be read
as a directional result. `spread.check` measures dispersion — a second moment —
and `clients` and `events` read no outcome at all.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from ....alpha_eval import spread
from ....research_data import repository
from . import clients, events

logger = logging.getLogger(__name__)

MIN_TV_CR = 1.0
DEFAULT_HORIZONS = (1, 10)


def context(bars: pd.DataFrame | None = None,
            min_tv_cr: float = MIN_TV_CR) -> pd.DataFrame:
    """The liquid universe with the trailing scales every measurement needs.

    All rolling, all shifted by construction — a 20-session median ending at
    the session itself is knowable at that session's close, which is where
    every outcome window below starts.

    Two price spaces travel together on purpose. Returns, volatility and the
    outcome are computed on the **adjusted** close, because a split is not a
    50% loss. Anything compared against a deal — its price, its quantity — is
    computed on the **raw** close and the raw volume, because that is the
    space the deal file prints in. `events._scale` names the raw columns
    explicitly so the two cannot be confused at the call site.

    `min_tv_cr` is a parameter rather than a constant because it is a
    parameter: the withdrawal of the distribution narrowing (FINDINGS.md,
    2026-08-22) turned on a floor nobody had varied, and a floor that can only
    be changed by editing a module constant is a floor nobody will vary.
    """
    if bars is None:
        bars = repository.daily_bars(
            columns=["symbol", "date", "close", "volume",
                     "close_raw", "volume_raw"])
    b = bars.sort_values(["symbol", "date"]).copy()
    b["tv_cr"] = b["close"] * b["volume"] / 1e7
    g = b.groupby("symbol", sort=False)
    b["med_tv"] = g["tv_cr"].transform(lambda s: s.rolling(20, min_periods=10).median())
    b["med_vol"] = g["volume"].transform(lambda s: s.rolling(20, min_periods=10).median())
    b["med_vol_raw"] = g["volume_raw"].transform(
        lambda s: s.rolling(20, min_periods=10).median())
    b["ret"] = g["close"].pct_change()
    b["vol20"] = b.groupby("symbol", sort=False)["ret"].transform(
        lambda s: s.rolling(20, min_periods=10).std())
    return b[b["med_tv"] >= min_tv_cr].reset_index(drop=True)


def panel(liquid: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Forward excess returns plus the quintiles a control is matched on."""
    p = spread.outcomes(liquid, horizon=horizon).merge(
        liquid[["symbol", "date", "vol20", "med_tv", "volume", "med_vol"]],
        on=["symbol", "date"], how="left").dropna(
            subset=["vol20", "med_tv", "med_vol"])
    p["volx"] = p["volume"] / p["med_vol"]
    for col, q in (("vol20", "vol_q"), ("med_tv", "liq_q"), ("volx", "volx_q")):
        p[q] = p.groupby("date")[col].transform(
            lambda s: pd.qcut(s, 5, labels=False, duplicates="drop"))
    return p.dropna(subset=["vol_q", "liq_q", "volx_q"])


def gate(horizons: tuple[int, ...] = DEFAULT_HORIZONS,
         partition: str | None = None) -> pd.DataFrame:
    """The dispersion table: does this event family fan outcomes out?

    The control is round-trip bulk-deal days on the same session — not the
    market and not the matched panel. FINDINGS.md 2026-08-22: round-trip days
    already carry 1.218 against a matched panel at h=10, so a contrast drawn
    against the panel would clear on the noise the family shares with itself.
    """
    liquid = context()
    ev = events.build_events(bars=liquid, partition=partition).rename(
        columns={"session": "date"})
    rows = []
    for h in horizons:
        p = panel(liquid, h)
        bulk_only = p.merge(ev[["symbol", "date"]].drop_duplicates(),
                            on=["symbol", "date"])
        arms = {
            "all bulk vs matched panel": (ev, p),
            "round-trip only vs panel": (ev[~ev["is_directional"]], p),
            "directional vs panel": (ev[ev["is_directional"]], p),
            "directional vs round-trip": (ev[ev["is_directional"]], bulk_only),
            "accumulation vs round-trip": (ev[ev["direction"] == "accumulation"], bulk_only),
            "distribution vs round-trip": (ev[ev["direction"] == "distribution"], bulk_only),
        }
        for label, (e, pool) in arms.items():
            try:
                r = spread.check(e[["symbol", "date"]], pool, horizon=h,
                                 label=label, match_on=("vol_q", "liq_q", "volx_q"))
            except spread.SpreadError as exc:
                rows.append({"horizon": h, "arm": label, "note": str(exc)[:70]})
                continue
            try:
                r["persistence"] = spread.event_persistence(
                    e[["symbol", "date"]].drop_duplicates(), horizon=h)["overlap_share"]
            except spread.SpreadError:
                r["persistence"] = np.nan
            rows.append({"horizon": h, "arm": label,
                         "dispersion_ratio": r["dispersion_ratio"],
                         "tail_ratio": r["tail_ratio"], "n": r["n_events"],
                         "per_session": r["events_per_session"],
                         "persistence": r["persistence"]})
    return pd.DataFrame(rows)


def counterparties(partition: str | None = None) -> pd.DataFrame:
    """Who is actually in this file, by row and by distinct entity."""
    return clients.coverage(clients.classify_frame(events.load(partition=partition)))


def summary(partition: str | None = None) -> dict[str, Any]:
    ev = events.build_events(partition=partition)
    return {"events": events.summarise(ev),
            "counterparties": counterparties(partition).to_dict("index")}
