"""Phase 2.3: where the mass actually sits, before any threshold is chosen.

WHY THIS EXISTS
The entry rules are stated qualitatively — a "modest" gap, "strong" opening
volume, a low "not far below" the open. Turning those into numbers by guessing
would bake three beliefs into the strategy at once. This module measures the
candidate pool's distributions so the cut-points can be read off the data, and
it deliberately produces no filter and no score.

WHAT THE MEASUREMENTS SAY, AND THE TWO TRAPS IN THEM

1. The gaps are far smaller than the language suggests. Median +0.24%, p90
   +1.03%, p99 +2.71%; only 2.1% of candidate mornings gap more than 2%. This
   is not a surprise once stated: the screener selects for volatility
   *contraction*, so it hands over quiet stocks by construction. Any gap
   threshold above ~1.5% is a decision to trade a few hundred days out of
   64,000, and that should be a deliberate choice rather than a side effect of
   picking a round number.

2. `om_low_vs_open_pct` cannot be read as a strength signal as it stands. It is
   censored at zero by construction — `om_low` is the minimum low across the
   first minute and `om_open` is the first bar's open, so the ratio can never
   be positive — and 35.7% of candidate days sit exactly at the boundary. That
   atom is a liquidity artifact, not a bullish tell: it covers 52% of days in
   the thinnest turnover quintile against 25% in the most liquid, because a
   stock that prints nine times a minute has few chances to trade below its
   opening price. "The low held near the open" is nearly free for a thin name
   and genuinely binding only for an active one, so the rule needs to be
   conditioned on trade frequency before it means the same thing across the
   pool. `om_body_pct` saturates at 100% for the same reason.

Everything here is reported, nothing is applied.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

REPORT_PATH = config.METADATA_DIR / "characterization.json"

QUANTILES = [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]

# The measures the entry rules are stated in, plus the two that qualify them.
MEASURES = {
    "gap_pct": "opening print vs previous close, %",
    "open_drift_pct": "first tradeable tick vs opening print, %",
    "vol_5m_pct_of_median_daily": "first 5 minutes as % of median 20d daily volume",
    "vol_5m_rel_own": "first 5 min vs own trailing mean (selection-biased)",
    "om_low_vs_open_pct": "first-minute low vs open, % (censored at 0)",
    "om_body_pct": "first-minute body as % of its range (saturates at 100)",
    "range_5m_pct": "5-minute range as % of open",
}

GAP_BUCKETS = [-np.inf, -5, -2, -1, -0.5, 0, 0.5, 1, 2, 3, 5, np.inf]
VOL_BUCKETS = [0, 1, 2.5, 5, 10, 20, 40, np.inf]


def describe(panel: pd.DataFrame) -> dict:
    """Quantiles and moments for each measure the rules are stated in."""
    out = {}
    for col, label in MEASURES.items():
        if col not in panel.columns:
            continue
        s = panel[col].dropna()
        if s.empty:
            continue
        out[col] = {
            "label": label,
            "n": int(len(s)),
            "mean": round(float(s.mean()), 4),
            "sd": round(float(s.std()), 4),
            "quantiles": {f"p{int(q*100):02d}": round(float(s.quantile(q)), 4)
                          for q in QUANTILES},
        }
    return out


def gap_profile(panel: pd.DataFrame) -> list[dict]:
    """How the other measures behave across gap buckets."""
    b = pd.cut(panel["gap_pct"], GAP_BUCKETS)
    g = panel.groupby(b, observed=True)
    rows = []
    for name, sub in g:
        rows.append({
            "bucket": str(name),
            "n": int(len(sub)),
            "pct_of_panel": round(len(sub) / len(panel) * 100, 3),
            "median_vol_pct_of_daily": round(float(sub["vol_5m_pct_of_median_daily"].median()), 3),
            "median_om_low_vs_open": round(float(sub["om_low_vs_open_pct"].median()), 3),
            "median_range_5m": round(float(sub["range_5m_pct"].median()), 3),
        })
    return rows


def volume_profile(panel: pd.DataFrame) -> list[dict]:
    b = pd.cut(panel["vol_5m_pct_of_median_daily"], VOL_BUCKETS)
    rows = []
    for name, sub in panel.groupby(b, observed=True):
        rows.append({
            "bucket": str(name),
            "n": int(len(sub)),
            "pct_of_panel": round(len(sub) / len(panel) * 100, 3),
            "median_gap": round(float(sub["gap_pct"].median()), 3),
            "median_range_5m": round(float(sub["range_5m_pct"].median()), 3),
            "median_om_low_vs_open": round(float(sub["om_low_vs_open_pct"].median()), 3),
        })
    return rows


def censoring_check(panel: pd.DataFrame) -> dict:
    """Quantify the zero-atom in `om_low_vs_open_pct` against liquidity.

    This is the number that decides whether the "low near the open" rule can be
    used as stated, so it is measured rather than asserted.
    """
    d = panel.dropna(subset=["om_low_vs_open_pct", "median_tv_20_cr"]).copy()
    if d.empty:
        return {}
    d["q"] = pd.qcut(d["median_tv_20_cr"].rank(method="first"), 5,
                     labels=["Q1_thin", "Q2", "Q3", "Q4", "Q5_liquid"])
    by = d.groupby("q", observed=True).apply(
        lambda s: pd.Series({
            "n": len(s),
            "pct_at_zero": round(float((s["om_low_vs_open_pct"] == 0).mean() * 100), 2),
            "median_om_bars": float(s["om_bars"].median()),
        }), include_groups=False)
    return {
        "pct_at_zero_overall": round(float((d["om_low_vs_open_pct"] == 0).mean() * 100), 2),
        "pct_positive": round(float((d["om_low_vs_open_pct"] > 0).mean() * 100), 4),
        "by_turnover_quintile": by.reset_index().to_dict("records"),
    }


def joint_mass(panel: pd.DataFrame,
               gap_bands: tuple[tuple[float, float], ...] = ((0, 1), (0, 2), (0, 3), (-1, 2)),
               vol_floors: tuple[float, ...] = (5, 10, 20)) -> list[dict]:
    """How many mornings survive each candidate ('modest gap', 'strong volume').

    Reported as a grid rather than a recommendation: the point is to show what
    each pair of cut-points costs in sample size before one is adopted.
    """
    rows = []
    for lo, hi in gap_bands:
        for v in vol_floors:
            m = (panel["gap_pct"].between(lo, hi)
                 & (panel["vol_5m_pct_of_median_daily"] >= v))
            rows.append({
                "gap_low": lo, "gap_high": hi, "vol_floor_pct": v,
                "n_days": int(m.sum()),
                "pct_of_panel": round(float(m.mean()) * 100, 3),
                "n_sessions": int(panel.loc[m, "date"].nunique()),
                "n_symbols": int(panel.loc[m, "symbol"].nunique()),
            })
    return rows


def report(panel: pd.DataFrame, save: bool = True) -> dict:
    out = {
        "panel_rows": int(len(panel)),
        "symbols": int(panel["symbol"].nunique()),
        "sessions": int(panel["date"].nunique()),
        "window": [str(panel["date"].min().date()), str(panel["date"].max().date())],
        "distributions": describe(panel),
        "gap_profile": gap_profile(panel),
        "volume_profile": volume_profile(panel),
        "censoring": censoring_check(panel),
        "joint_mass": joint_mass(panel),
    }
    if save:
        import json
        config.METADATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(out, indent=2, default=str))
    return out
