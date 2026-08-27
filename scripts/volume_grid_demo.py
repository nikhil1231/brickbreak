#!/usr/bin/env python3
"""What a grid search finds in the opening-volume family, and what survives.

NOT EVIDENCE. This is a demonstration, run deliberately on partitions the
opening-window lineage (H001-H015, H024, H033) has already consumed, so it
spends nothing that was not already spent and can prove nothing either. The
`forward` partition is never loaded.

The point is the shape of the decay, not any cell in the table: pick the best
configuration on train, then read that exact configuration on validation and on
test, and watch what happens to it. A grid this size will always produce a
train-best that looks tradable.

Parameters are deliberately coarse -- wide gap bands, relative-volume multiples,
delivery and trend terciles -- so that no cell depends on a threshold no trader
could state out loud.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.research_data import frame  # noqa: E402

HORIZON = 5

GAP_LOW = (-3.0, -1.0, 0.0)
GAP_HIGH = (1.0, 2.0, 3.0, 5.0)
REL_VOLUME = (1.0, 1.5, 2.0, 3.0)
DELIVERY = (0.0, 40.0, 55.0)
TREND = ("any", "weak", "strong")


def session_clustered(frame_: pd.DataFrame, column: str) -> tuple[float, float, int]:
    """Mean and t with the session as the unit, because names move together."""
    by_session = frame_.groupby("date")[column].mean()
    values = by_session.to_numpy(float)
    values = values[np.isfinite(values)]
    if len(values) < 3:
        return float("nan"), float("nan"), len(values)
    mean = float(values.mean())
    error = float(values.std(ddof=1) / np.sqrt(len(values)))
    return mean, (mean / error if error > 0 else float("nan")), len(values)


def select(panel: pd.DataFrame, gap_low: float, gap_high: float,
           rel_volume: float, delivery: float, trend: str) -> pd.Series:
    mask = (panel["gap_pct"].between(gap_low, gap_high)
            & panel["rel_volume"].ge(rel_volume)
            & panel["deliv_pct"].ge(delivery))
    if trend == "weak":
        mask &= panel["trend_rank"].le(0.33)
    elif trend == "strong":
        mask &= panel["trend_rank"].ge(0.67)
    return mask


def main() -> int:
    panel = frame.load_daily_panel(
        version="v1",
        columns=["symbol", "date", "gap_pct", "volume", "median_vol_20",
                 "deliv_pct", "ret_20d", "median_tv_20_cr", "series", "is_etf"],
        drop_purged=True)
    panel = panel.loc[
        panel["series"].eq("EQ") & ~panel["is_etf"].fillna(False)
        & panel["median_tv_20_cr"].between(3.0, 25.0)].copy()
    panel["rel_volume"] = panel["volume"] / panel["median_vol_20"].replace(0, np.nan)
    panel["trend_rank"] = panel.groupby("date")["ret_20d"].rank(pct=True)

    outcome = f"excess_ret_{HORIZON}d_pct"
    panel[outcome] = frame.forward_excess_return(panel, HORIZON, version="v1")
    panel = panel.loc[panel[outcome].notna()
                      & panel["rel_volume"].notna()
                      & panel["gap_pct"].notna()]
    print(f"panel {len(panel):,} rows  "
          f"{panel['date'].nunique():,} sessions  "
          f"{panel['symbol'].nunique():,} symbols")
    print(panel["partition"].value_counts().to_dict())

    parts = {name: panel.loc[panel["partition"].eq(name)]
             for name in ("train", "validation", "test")}
    assert "forward" not in panel["partition"].unique(), "forward must stay clean"

    combos = [c for c in itertools.product(
        GAP_LOW, GAP_HIGH, REL_VOLUME, DELIVERY, TREND) if c[0] < c[1]]
    print(f"\ngrid: {len(combos)} configurations\n")

    rows = []
    for gap_low, gap_high, rel_volume, delivery, trend in combos:
        record: dict[str, object] = {
            "gap_low": gap_low, "gap_high": gap_high, "rel_volume": rel_volume,
            "delivery": delivery, "trend": trend}
        keep = True
        for name, part in parts.items():
            chosen = part.loc[select(part, gap_low, gap_high, rel_volume,
                                     delivery, trend)]
            # A configuration nobody could actually trade is not a finding.
            if len(chosen) < 300 or chosen["date"].nunique() < 100:
                keep = False
                break
            mean, t_stat, sessions = session_clustered(chosen, outcome)
            record |= {f"{name}_bps": mean * 100.0, f"{name}_t": t_stat,
                       f"{name}_n": len(chosen), f"{name}_sessions": sessions}
        if keep:
            rows.append(record)

    table = pd.DataFrame(rows)
    if table.empty:
        print("no configuration met the minimum-sample floor")
        return 1
    print(f"{len(table)} configurations cleared the sample floor\n")

    best = table.sort_values("train_bps", ascending=False).head(10)
    show = ["gap_low", "gap_high", "rel_volume", "delivery", "trend",
            "train_bps", "train_t", "validation_bps", "validation_t",
            "test_bps", "test_t", "train_n"]
    print("TOP 10 BY TRAIN, WITH THE SAME CONFIG READ FORWARD:")
    print(best[show].round(2).to_string(index=False))

    winner = table.loc[table["train_bps"].idxmax()]
    print("\nTRAIN-BEST CONFIGURATION, CARRIED THROUGH:")
    for name in ("train", "validation", "test"):
        print(f"  {name:<11} {winner[f'{name}_bps']:+8.1f} bps   "
              f"t={winner[f'{name}_t']:+6.2f}   n={int(winner[f'{name}_n']):,}")

    print("\nWHAT THE WHOLE GRID DOES, NOT JUST ITS BEST CELL:")
    for name in ("train", "validation", "test"):
        column = table[f"{name}_bps"]
        print(f"  {name:<11} median {column.median():+7.1f}   "
              f"best {column.max():+7.1f}   worst {column.min():+7.1f}   "
              f"share positive {float((column > 0).mean()):.0%}")

    rank_decay = table[["train_bps", "validation_bps", "test_bps"]].corr(
        method="spearman")
    print("\nRANK CORRELATION BETWEEN PARTITIONS (does train rank predict?):")
    print(rank_decay.round(3).to_string())

    top_quartile = table.nlargest(max(len(table) // 4, 1), "train_bps")
    print(f"\nTOP TRAIN QUARTILE ({len(top_quartile)} configs) READ FORWARD:")
    for name in ("validation", "test"):
        column = top_quartile[f"{name}_bps"]
        print(f"  {name:<11} mean {column.mean():+7.1f} bps   "
              f"share positive {float((column > 0).mean()):.0%}")

    out = ROOT / "logs" / "volume_grid_demo.csv"
    table.to_csv(out, index=False)
    print(f"\nwrote {out}  ({len(table)} rows) — demonstration only, not evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
