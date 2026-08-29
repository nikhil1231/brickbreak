"""Sector index and breadth construction.

THE MODULE DOCSTRING USED TO SAY "POINT-IN-TIME". IT IS NOT, AND H059 DIED OF IT.

`meta.sector` is read from `nse_archive.build_symbol_metadata()`, which
downloads **today's** NSE index constituent CSVs. Two things follow, and callers
must know which of them applies to their question:

  * MEMBERSHIP SURVIVORSHIP. A symbol absent from today's index lists has no
    sector at all. It is therefore missing from every historical breadth
    denominator, and any caller that does `dropna(subset=["sector_breadth"])`
    has silently conditioned its universe on surviving to the present. Of 3,348
    symbols that traded 2020-2026, today's lists label 537.
  * CLASSIFICATION DRIFT. A symbol reclassified since carries today's label
    backwards through all of history.

`announcements.industry` repairs the first (1,042 of those 3,348, delisted names
included) and cannot repair the second — it is itself a per-symbol snapshot, as
`assert_label_is_not_a_snapshot` below will tell you.

This is the same today-snapshot source as `size_tier_rank`, which produced this
project's fourth lookahead (H033), and it reached H059 through `sector` after
that hypothesis had explicitly disabled the size-rank screen to avoid it.

SEPARATELY, AND WORSE FOR ANY `argmin` CALLER: breadth is a noisy statistic.
Two faithful implementations of "share of members above their 50-session EMA"
correlate 0.968 and still disagree about **which sector is weakest on 39% of
sessions**. A rule that selects on `sector_breadth.idxmin()` is not identified
by this data. Rank-based and multi-name uses are fine; `k=1` argmin is not.
"""
from __future__ import annotations

import pandas as pd

UNCLASSIFIED = "UNCLASSIFIED"


def assert_label_is_not_a_snapshot(labels: pd.DataFrame,
                                  symbol_col: str = "symbol",
                                  label_col: str = "sector",
                                  date_col: str = "date") -> None:
    """Raise if a per-symbol label never changes — a snapshot wearing a panel.

    Cheap, and it is the check whose absence cost H059. A genuinely
    point-in-time classification has *some* symbols reclassified over a
    multi-year window; if not one symbol in the frame ever changes label, the
    column is a present-day snapshot broadcast backwards, whatever its shape.
    """
    if date_col not in labels.columns:
        return
    changed = labels.groupby(symbol_col)[label_col].nunique(dropna=True)
    n_multi = int((changed > 1).sum())
    if len(changed) and n_multi == 0:
        raise ValueError(
            f"{label_col!r} never changes for any of {len(changed)} symbols: "
            "this is a present-day snapshot, not point-in-time membership. "
            "See this module's docstring before using it for selection."
        )


def build_sector_series(
    bars: pd.DataFrame,
    meta: pd.DataFrame,
    ema_fast: int = 20,
    ema_mid: int = 50,
    min_members: int = 5,
) -> pd.DataFrame:
    """Build an equal-weight synthetic sector index per sector and date."""
    df = bars.merge(meta[["symbol", "sector"]], on="symbol", how="left")
    df["sector"] = df["sector"].fillna(UNCLASSIFIED)
    df = df[df["prev_close"] > 0].copy()
    df["ret"] = df["close"] / df["prev_close"] - 1.0
    df = df[df["ret"].between(-0.6, 0.6)]

    grp = df.groupby(["sector", "date"], sort=True)
    agg = grp.agg(mean_ret=("ret", "mean"), n_members=("ret", "size")).reset_index()
    agg = agg[agg["n_members"] >= min_members].copy()

    out = []
    for _sector, group in agg.groupby("sector", sort=False):
        group = group.sort_values("date").copy()
        group["sector_index"] = (1.0 + group["mean_ret"]).cumprod() * 100.0
        group["sec_ema_fast"] = group["sector_index"].ewm(
            span=ema_fast, adjust=False, min_periods=ema_fast
        ).mean()
        group["sec_ema_mid"] = group["sector_index"].ewm(
            span=ema_mid, adjust=False, min_periods=ema_mid
        ).mean()
        group["sec_slope"] = (
            group["sec_ema_fast"] / group["sec_ema_fast"].shift(10) - 1
        ) * 100
        group["sector_uptrend_index"] = (
            (group["sec_ema_fast"] > group["sec_ema_mid"])
            & (group["sector_index"] > group["sec_ema_mid"])
        ).astype("Int8")
        out.append(group)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def add_sector_breadth(
    metrics: pd.DataFrame,
    sector_series: pd.DataFrame,
    meta: pd.DataFrame,
) -> pd.DataFrame:
    """Attach the share of sector constituents above their medium EMA."""
    if "sector" in metrics.columns:
        panel = metrics[["symbol", "date", "sector", "above_ema_mid"]].copy()
    else:
        panel = metrics.merge(meta[["symbol", "sector"]], on="symbol", how="left")
    panel["sector"] = panel["sector"].fillna(UNCLASSIFIED)
    breadth = (
        panel.groupby(["sector", "date"])["above_ema_mid"]
        .mean()
        .mul(100)
        .rename("sector_breadth")
        .reset_index()
    )
    return sector_series.merge(breadth, on=["sector", "date"], how="left")


__all__ = ["UNCLASSIFIED", "add_sector_breadth", "build_sector_series",
           "assert_label_is_not_a_snapshot"]
