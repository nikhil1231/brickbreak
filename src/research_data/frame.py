"""Point-in-time frame API — the main interface experiments use to get data.

Every experiment gets its data through this module. Nothing else opens a
parquet file. If something is missing, it is added here rather than worked
around.

The API enforces three things the old code relied on convention for:

1. **Partitions, never date ranges.** An experiment names a dataset version and
   a partition; hand-written windows are how a holdout gets read twice.
2. **PIT by default.** The daily panel is served as-of the open (lagged)
   unless explicitly requested otherwise with a logged reason.
3. **Forward labels are labelled.** `forward_return()` is the only way to get
   the future, and it checks the horizon against the split's purge budget.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config
from . import catalogue as cat_mod
from . import splits

logger = logging.getLogger(__name__)

# Paths to the on-disk parquet files this module wraps.
METRICS_ASOF_PATH = config.NORMALIZED_DIR / "screen_metrics_asof.parquet"
METRICS_PATH = config.NORMALIZED_DIR / "screen_metrics.parquet"
CONTEXT_PATH = config.NORMALIZED_DIR / "daily_context.parquet"
MARKET_PATH = config.NORMALIZED_DIR / "market_regime.parquet"
BARS_ADJ_PATH = config.NORMALIZED_DIR / "daily_bars_adj.parquet"


class FrameError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# daily panel
# ---------------------------------------------------------------------------

def load_daily_panel(
    version: str = "v1",
    partition: str | None = None,
    asof_open: bool = True,
    include_context: bool = False,
    columns: list[str] | None = None,
    drop_purged: bool = True,
) -> pd.DataFrame:
    """The daily panel with split partitions attached.

    This is the only way an experiment should get daily data. It wraps
    the existing parquet files and enforces PIT guarantees.

    Parameters
    ----------
    version : str
        Split version to use. Default "v1".
    partition : str or None
        If given, filter to this partition ("train", "validation", "test",
        "forward"). None returns all partitions.
    asof_open : bool
        If True (default, and the safe choice), loads the as-of panel where
        every indicator carries D-1 values. False loads the unlagged panel —
        which is what caused H015 — and logs a warning.
    include_context : bool
        If True, merge breakout location, relative strength and market regime.
    columns : list[str] or None
        If given, select only these columns (plus symbol, date, partition).
        Rejects any column marked ``available_as_of="future"`` in the
        catalogue, because forward labels are not features.
    drop_purged : bool
        If True (default), drop rows in the purge zone.

    Returns
    -------
    pd.DataFrame
        Dated panel with a ``partition`` column attached.
    """
    # Validate requested columns against the catalogue.
    catalogue = cat_mod.DEFAULT
    if columns:
        for col in columns:
            if col in catalogue:
                spec = catalogue[col]
                if spec.available_as_of == "future":
                    raise FrameError(
                        f"column {col!r} is a forward label "
                        f"(available_as_of='future'). Use forward_return() "
                        f"to obtain the future — it is never a feature.")

    # Load the metrics panel.
    if asof_open:
        if not METRICS_ASOF_PATH.exists():
            raise FrameError(
                "screen_metrics_asof.parquet missing. Run:\n"
                "  python -m src.cli build-metrics --force\n"
                "This is the as-of panel that does not read the entry day's "
                "own close (H015).")
        df = pd.read_parquet(METRICS_ASOF_PATH)
    else:
        logger.warning(
            "Loading UNLAGGED metrics panel. Date D's close, high, low and "
            "volume are visible. This is the lookahead that caused H015. "
            "Only use this for describing what a day looked like, never for "
            "screening or scoring.")
        if not METRICS_PATH.exists():
            raise FrameError(
                "screen_metrics.parquet missing. Run:\n"
                "  python -m src.cli build-metrics")
        df = pd.read_parquet(METRICS_PATH)

    # Merge context if requested.
    if include_context:
        ctx, mkt = _load_context()
        # Context columns are per (symbol, date); merge them in.
        ctx_cols = [c for c in ctx.columns if c not in df.columns
                    or c in ("symbol", "date")]
        df = df.merge(ctx[ctx_cols], on=["symbol", "date"], how="left")
        # Market regime is per date.
        mkt_cols = [c for c in mkt.columns if c not in df.columns
                    or c == "date"]
        df = df.merge(mkt[mkt_cols], on="date", how="left")

    # Attach partition labels via the split module.
    df = splits.assign(df, version=version, drop_purged=drop_purged)

    # Filter to requested partition.
    if partition:
        valid = splits.SETS + ("forward",)
        if partition not in valid:
            raise FrameError(f"unknown partition {partition!r}; "
                             f"choose from {valid}")
        df = df[df["partition"] == partition].copy()
        if df.empty:
            logger.warning(f"partition {partition!r} returned 0 rows")

    # Select columns.
    if columns:
        keep = ["symbol", "date", "partition"]
        keep += [c for c in columns if c not in keep and c in df.columns]
        df = df[keep]

    n = len(df)
    n_sym = df["symbol"].nunique() if "symbol" in df else 0
    logger.info(
        f"load_daily_panel: {n:,} rows, {n_sym:,} symbols, "
        f"version={version}, partition={partition}, asof={asof_open}, "
        f"context={include_context}")

    return df


def _load_context() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load context and market regime parquets."""
    if not CONTEXT_PATH.exists():
        raise FrameError(
            "daily_context.parquet missing. Run:\n"
            "  python -m src.cli context")
    if not MARKET_PATH.exists():
        raise FrameError(
            "market_regime.parquet missing. Run:\n"
            "  python -m src.cli context")
    return pd.read_parquet(CONTEXT_PATH), pd.read_parquet(MARKET_PATH)


# ---------------------------------------------------------------------------
# forward returns — the only way to obtain the future
# ---------------------------------------------------------------------------

def forward_return(
    df: pd.DataFrame,
    horizon: int,
    version: str = "v1",
    entry_col: str = "close",
    bars: pd.DataFrame | None = None,
) -> pd.Series:
    """Compute forward returns for a dated panel.

    This is the only way to obtain the future, and it checks the horizon
    against the split's purge budget before computing anything.

    Parameters
    ----------
    df : pd.DataFrame
        Must have 'symbol' and 'date' columns.
    horizon : int
        Number of sessions forward.
    version : str
        Split version — used to check the horizon is within purge budget.
    entry_col : str
        Column in `df` to use as the entry price. Default "close".
    bars : pd.DataFrame or None
        Adjusted daily bars. Loaded from disk if not provided.

    Returns
    -------
    pd.Series
        Forward return in percent, aligned to df's index. NaN where
        incomplete.
    """
    manifest = splits.load(version)
    splits.check_horizon(horizon, manifest)

    if bars is None:
        if not BARS_ADJ_PATH.exists():
            raise FrameError(
                "daily_bars_adj.parquet missing. Run:\n"
                "  python -m src.cli sync-nse && python -m src.cli "
                "sync-corp-actions")
        bars = pd.read_parquet(
            BARS_ADJ_PATH,
            columns=["symbol", "date", "close"])

    b = bars.sort_values(["symbol", "date"]).reset_index(drop=True)
    fwd_close = b.groupby("symbol", sort=False)["close"].shift(-horizon)

    fwd = pd.DataFrame({
        "symbol": b["symbol"].to_numpy(),
        "date": b["date"].to_numpy(),
        f"fwd_close_{horizon}": fwd_close.to_numpy(),
        "n_fwd": b.groupby("symbol", sort=False).cumcount(
            ascending=False).to_numpy(),
    })

    d = df.merge(fwd, on=["symbol", "date"], how="left")
    complete = d["n_fwd"] >= horizon
    entry = d[entry_col].where(d[entry_col] > 0)
    ret = ((d[f"fwd_close_{horizon}"] / entry - 1) * 100).where(complete)

    return pd.Series(ret.to_numpy(), index=df.index,
                     name=f"fwd_ret_{horizon}d_pct")


# ---------------------------------------------------------------------------
# market regime
# ---------------------------------------------------------------------------

def market(version: str = "v1") -> pd.DataFrame:
    """Market regime series, partitioned.

    One row per session with regime labels and partition assignment.
    """
    if not MARKET_PATH.exists():
        raise FrameError(
            "market_regime.parquet missing. Run:\n"
            "  python -m src.cli context")
    mkt = pd.read_parquet(MARKET_PATH)
    return splits.assign(mkt, version=version)


# ---------------------------------------------------------------------------
# adjusted bars
# ---------------------------------------------------------------------------

def bars(
    version: str = "v1",
    partition: str | None = None,
    adjusted: bool = True,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Daily OHLCV bars, partitioned.

    Parameters
    ----------
    adjusted : bool
        True (default) = corporate-action adjusted. False = raw tape prices.
    """
    if adjusted:
        path = BARS_ADJ_PATH
    else:
        path = config.NORMALIZED_DIR / "daily_bars.parquet"

    if not path.exists():
        raise FrameError(f"{path.name} missing. Run: python -m src.cli sync-nse")

    read_cols = columns if columns else None
    if read_cols:
        # Always include symbol + date for the join
        for c in ("symbol", "date"):
            if c not in read_cols:
                read_cols = [c] + list(read_cols)
    df = pd.read_parquet(path, columns=read_cols)
    df = splits.assign(df, version=version)

    if partition:
        df = df[df["partition"] == partition].copy()

    return df


# ---------------------------------------------------------------------------
# point-in-time universe
# ---------------------------------------------------------------------------

def universe(
    asof_date: str | pd.Timestamp | None = None,
    version: str = "v1",
    partition: str | None = None,
    exclude_etf: bool = True,
    series: tuple[str, ...] = ("EQ",),
    min_median_tv_cr: float | None = None,
) -> pd.DataFrame:
    """Point-in-time universe of tradeable securities.

    Parameters
    ----------
    asof_date : str, Timestamp, or None
        If given, filter to securities trading on this specific date.
    version : str
        Split version to use. Default "v1".
    partition : str or None
        Filter to a specific partition ("train", "validation", "test", "forward").
    exclude_etf : bool
        If True (default), exclude ETF securities.
    series : tuple[str, ...]
        Permitted settlement series (default ("EQ",)).
    min_median_tv_cr : float or None
        If given, minimum 20-session median traded value in Rs Crore.

    Returns
    -------
    pd.DataFrame
        Point-in-time universe panel.
    """
    cols = ["symbol", "date", "series", "is_etf", "close", "close_raw"]
    if min_median_tv_cr is not None:
        cols.append("median_tv_20_cr")

    df = load_daily_panel(
        version=version,
        partition=partition,
        asof_open=True,
        columns=cols,
    )

    if asof_date is not None:
        target = pd.to_datetime(asof_date)
        df = df[pd.to_datetime(df["date"]) == target].copy()

    if exclude_etf and "is_etf" in df.columns:
        df = df[~df["is_etf"].astype(bool)]

    if series and "series" in df.columns:
        df = df[df["series"].isin(series)]

    if min_median_tv_cr is not None and "median_tv_20_cr" in df.columns:
        df = df[df["median_tv_20_cr"] >= min_median_tv_cr]

    return df

