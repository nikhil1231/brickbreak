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
    entry: str = "close",
    bars: pd.DataFrame | None = None,
    max_staleness: int = 3,
) -> pd.Series:
    """Forward return over exactly `horizon` **market sessions**.

    The only way to obtain the future, and it checks the horizon against the
    split's purge budget before computing anything.

    TWO THINGS THIS GETS RIGHT THAT THE OBVIOUS IMPLEMENTATION DOES NOT

    1. **Sessions, not rows.** `groupby("symbol").shift(-horizon)` takes the
       20th *traded bar*, which for a thinly traded or suspended name can be
       months away. Measured on the real panel: 1.49% of rows had a 20-bar
       label spanning more than 20 sessions, the worst spanning 1,404 — and
       3,681 of them reached across a purged boundary into a
       higher-priority partition. The purge is defined in market sessions, so
       the label has to be too, or the purge does not bind.

    2. **The entry is date D's own price.** The as-of panel's `close` column is
       *D-1's* close by construction, so using it made a "5-day" label span six
       sessions and swallow date D's entire move. On RELIANCE 2022-08-02 that
       read +0.2971% where the D-close-to-D+5 return was -0.0832% — opposite
       sign. Entry prices come from the bars here, never from the panel, so the
       label means the same thing whatever frame is passed in.

    Parameters
    ----------
    horizon : int
        Sessions forward. Checked against the split's purge budget.
    entry : {"close", "open"}
        Price on date D to enter at. "close" is the canonical label (AGENTS.md
        quotes the day-D close to D+h segment); "open" is available because a
        signal known as-of the open is tradeable there.
    max_staleness : int
        If the symbol did not trade on session D+horizon, use its last traded
        close within this many sessions. Never looks forward. 0 disables it.

    Returns
    -------
    pd.Series
        Forward return in percent, aligned to df's index, NaN where the label
        cannot be formed.
    """
    manifest = splits.load(version)
    splits.check_horizon(horizon, manifest)
    if entry not in ("close", "open"):
        raise FrameError(f"entry must be 'close' or 'open', got {entry!r}")

    if bars is None:
        if not BARS_ADJ_PATH.exists():
            raise FrameError(
                "daily_bars_adj.parquet missing. Run:\n"
                "  python -m src.cli sync-nse && python -m src.cli "
                "sync-corp-actions")
        bars = pd.read_parquet(
            BARS_ADJ_PATH, columns=["symbol", "date", "open", "close"])

    b = bars.copy()
    b["date"] = pd.to_datetime(b["date"])

    # Dense session x symbol matrices. The market calendar comes from the bars
    # themselves because NSE trades some weekends and skips some weekdays; a
    # generated calendar is wrong in both directions.
    close_px = b.pivot(index="date", columns="symbol", values="close")
    entry_px = close_px if entry == "close" else b.pivot(
        index="date", columns="symbol", values="open")

    # Exits may use the last traded price within `max_staleness` sessions, so a
    # single untraded session does not discard the label. Entries may not: you
    # cannot buy at a price that did not trade.
    exit_src = close_px.ffill(limit=max_staleness) if max_staleness else close_px
    exit_px = exit_src.shift(-horizon)

    cal = close_px.index
    date_ix = pd.Series(np.arange(len(cal)), index=cal)
    sym_ix = pd.Series(np.arange(len(close_px.columns)), index=close_px.columns)

    d = pd.to_datetime(df["date"])
    i = d.map(date_ix).to_numpy()
    j = df["symbol"].map(sym_ix).to_numpy()
    ok = pd.notna(i) & pd.notna(j)

    out = np.full(len(df), np.nan)
    if ok.any():
        ii = i[ok].astype(int)
        jj = j[ok].astype(int)
        e = entry_px.to_numpy()[ii, jj]
        x = exit_px.to_numpy()[ii, jj]
        with np.errstate(invalid="ignore", divide="ignore"):
            out[ok] = np.where(e > 0, (x / e - 1.0) * 100.0, np.nan)

    return pd.Series(out, index=df.index, name=f"fwd_ret_{horizon}d_pct")


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

