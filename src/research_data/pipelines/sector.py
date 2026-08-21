"""Point-in-time sector index and breadth construction."""
from __future__ import annotations

import pandas as pd

UNCLASSIFIED = "UNCLASSIFIED"


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


__all__ = ["UNCLASSIFIED", "add_sector_breadth", "build_sector_series"]
