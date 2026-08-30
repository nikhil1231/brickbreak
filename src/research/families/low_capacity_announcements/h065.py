"""H065: frozen constructive-disclosure drift validation.

The subject set, universe, horizon, cost and bar were written into
``HYPOTHESES.md`` before this module loaded validation or test outcomes. Market
data enters only through ``research_data`` and the already-tested discretionary
outcome implementation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ....alpha_eval import diagnostics
from ....core import config
from ....discretionary import generators, outcomes
from ....research_data import frame

HYPOTHESIS_ID = "H065"
HORIZON = 20
COST_PCT = 0.40
MIN_LIFT_BPS = 50.0
MIN_POOLED_T = 2.0
PARTITIONS = ("validation", "test")
POSITIVE_SUBJECTS = frozenset({
    "Acquisition",
    "Agreements",
    "Bagging/Receiving of orders/contracts",
    "Monthly Business Updates",
})
RESULT_PATH = config.METADATA_DIR / "h065_constructive_disclosures.json"


def _is_selected(announcements: Any) -> bool:
    if not isinstance(announcements, (list, tuple)):
        return False
    return any(isinstance(item, dict)
               and str(item.get("subject", "")) in POSITIVE_SUBJECTS
               for item in announcements)


def _partition(partition: str, bars: pd.DataFrame) -> tuple[dict, pd.Series]:
    panel = frame.load_daily_panel(
        version="v1", partition=partition, asof_open=True,
        include_context=True)
    candidates = generators.low_capacity_announcement(
        panel, min_tv_cr=0.5, max_tv_cr=25.0, min_price=20.0,
        min_history=0, dataset_version="v1")
    candidates["selected"] = candidates["announcements"].apply(_is_selected)
    keys = candidates[["symbol", "date"]].copy()
    keys.insert(0, "case_id", [f"{partition}_{i}" for i in range(len(keys))])
    result = outcomes.compute(
        keys, horizons=(HORIZON,), primary_horizon=HORIZON,
        version="v1", bars=bars, entry_timing="open")
    d = candidates.reset_index(drop=True).copy()
    d["case_id"] = keys["case_id"]
    d = d.merge(result[["case_id", "primary_excess_pct"]], on="case_id")
    d = d.dropna(subset=["primary_excess_pct"])

    by_date = d.groupby("date")
    selected = by_date.apply(
        lambda x: x.loc[x["selected"], "primary_excess_pct"].mean(),
        include_groups=False)
    pool = by_date["primary_excess_pct"].mean()
    delta = (selected - pool).dropna().sort_index()
    st = diagnostics.cluster_stats(
        delta, pd.Series(delta.index, index=delta.index), lags=HORIZON - 1)
    taken = d.loc[d["selected"], "primary_excess_pct"]

    categories = []
    for subject in sorted(POSITIVE_SUBJECTS):
        mask = d["announcements"].apply(
            lambda xs: any(isinstance(x, dict) and x.get("subject") == subject
                           for x in xs))
        vals = d.loc[mask, "primary_excess_pct"]
        categories.append({
            "subject": subject, "n": int(len(vals)),
            "mean_excess_bps": round(float(vals.mean()) * 100, 1)
            if len(vals) else np.nan,
        })

    summary = {
        "partition": partition,
        "n_candidates": int(len(d)),
        "n_selected": int(d["selected"].sum()),
        "n_sessions": int(d["date"].nunique()),
        "selected_sessions": int(delta.size),
        "selected_mean_excess_bps": round(float(taken.mean()) * 100, 1),
        "selected_net_excess_bps": round(float(taken.mean() - COST_PCT) * 100, 1),
        "take_vs_pool_lift_bps": round(float(delta.mean()) * 100, 1),
        "lift_t": st["t"],
        "lift_naive_t": st["naive_t"],
        "positive_session_pct": round(float((delta > 0).mean()) * 100, 1),
        "categories": categories,
    }
    return summary, delta


def run(save: bool = True) -> dict:
    """Spend validation/test once and return the frozen H065 verdict."""
    bars = frame.bars(version="v1", columns=["open", "high", "low", "close"])
    summaries, deltas = {}, []
    for partition in PARTITIONS:
        summary, delta = _partition(partition, bars)
        summaries[partition] = summary
        deltas.append(delta)
    pooled = pd.concat(deltas).sort_index()
    pooled_stats = diagnostics.cluster_stats(
        pooled, pd.Series(pooled.index, index=pooled.index), lags=HORIZON - 1)

    checks = []
    for partition in PARTITIONS:
        row = summaries[partition]
        checks.extend([
            {"criterion": f"{partition}_net_excess_bps>0",
             "measured": row["selected_net_excess_bps"],
             "passed": row["selected_net_excess_bps"] > 0},
            {"criterion": f"{partition}_lift_bps>={MIN_LIFT_BPS}",
             "measured": row["take_vs_pool_lift_bps"],
             "passed": row["take_vs_pool_lift_bps"] >= MIN_LIFT_BPS},
        ])
    checks.append({
        "criterion": f"pooled_HH_t>={MIN_POOLED_T}",
        "measured": pooled_stats["t"],
        "passed": bool(np.isfinite(pooled_stats["t"])
                       and pooled_stats["t"] >= MIN_POOLED_T),
    })
    passed = all(c["passed"] for c in checks)
    result = {
        "hypothesis_id": HYPOTHESIS_ID,
        "generated_from": "H064 train post-outcome diagnostic",
        "dataset_version": "v1", "horizon": HORIZON,
        "cost_pct_round_trip": COST_PCT,
        "positive_subjects": sorted(POSITIVE_SUBJECTS),
        "partitions": summaries,
        "pooled": {
            "n_sessions": int(len(pooled)),
            "mean_lift_bps": round(float(pooled.mean()) * 100, 1),
            "t": pooled_stats["t"], "naive_t": pooled_stats["naive_t"],
        },
        "checks": checks, "passed": passed,
        "verdict": "SUPPORTED" if passed else "REJECTED",
    }
    if save:
        RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULT_PATH.write_text(json.dumps(result, indent=2, default=str) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
