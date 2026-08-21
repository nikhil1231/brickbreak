"""Build the screening metrics panel once, cache it, and reuse it.

Computing indicators over ~2,700 symbols x ~1,150 days takes a while, so it is
done once here and written to data/normalized/screen_metrics.parquet. The
frontend then filters that panel interactively without recomputation.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from ...core import config
from ..sources import nse as nse_archive
from . import asof, corporate_actions
from .indicators import compute_all
from .sector import UNCLASSIFIED, add_sector_breadth, build_sector_series

METRICS_PATH = config.NORMALIZED_DIR / "screen_metrics.parquet"
# The as-of-open panel: the same indicators, each carrying the value from the
# symbol's PREVIOUS session, so a screen for date D cannot read date D's close.
# See H015 and `research_data.pipelines.asof`. This is the panel a morning rule must use.
METRICS_ASOF_PATH = config.NORMALIZED_DIR / "screen_metrics_asof.parquet"
SECTOR_PATH = config.NORMALIZED_DIR / "sector_series.parquet"

# Columns the frontend and screener actually need; keeps the panel small.
KEEP = [
    "symbol", "date", "series", "sector", "size_tier_rank", "size_tier", "is_etf",
    "open", "high", "low", "close", "volume", "turnover", "deliv_pct",
    # The price that actually printed, kept beside the adjusted one: a minimum
    # price screen is a statement about what was tradeable that day.
    "close_raw", "adj_factor",
    "median_tv_20_cr", "median_vol_20",
    "ema_fast", "ema_mid", "ema_slow", "ema_stack_up", "above_ema_mid",
    "ema_fast_slope", "ema_mid_slope", "px_vs_ema_fast", "px_vs_ema_mid",
    "atr_ratio", "atr_ratio_pctile", "atr_pct", "range_pct", "range_pct_ma",
    "base_depth", "base_depth_pctile", "bb_width", "bb_width_pctile",
    "nr_k", "body_ratio", "inside_day", "doji_like", "n_small_bodies_5",
    "vol_squeeze", "contraction_steps",
    "ret_20d", "ret_60d", "dist_52w_high", "gap_pct",
    "sector_index", "sec_ema_fast", "sec_ema_mid", "sec_slope",
    "sector_uptrend_index", "sector_breadth",
]


def build(force: bool = False, min_history: int = 60) -> Path:
    if METRICS_PATH.exists() and not force:
        return METRICS_PATH

    t0 = time.perf_counter()
    print("loading daily bars ...", flush=True)
    # Corporate-action-adjusted bars when they exist. Indicators computed on raw
    # prices are wrong for any symbol that split: a 1:10 split reads as a -90%
    # day, which poisons every EMA, ATR and ret_60d spanning the ex-date.
    if corporate_actions.ADJ_BARS.exists():
        bars = corporate_actions.load_adjusted()
        print(f"  using corporate-action-adjusted bars "
              f"({int((bars['adj_factor'] != 1.0).sum()):,} rows rescaled)", flush=True)
    else:
        bars = nse_archive.load_range()
        print("  WARNING: unadjusted bars — splits/bonuses will corrupt trend "
              "indicators. Run: python -m src.cli sync-corp-actions", flush=True)
    if bars.empty:
        raise RuntimeError("No bhavcopy data. Run: python -m src.cli sync-nse")
    print(f"  {len(bars):,} rows, {bars['symbol'].nunique():,} symbols, "
          f"{bars['date'].nunique():,} dates ({time.perf_counter()-t0:.1f}s)", flush=True)

    meta = nse_archive.build_symbol_metadata()

    # Drop symbols with too little history to form any indicator.
    counts = bars.groupby("symbol")["date"].transform("size")
    bars = bars[counts >= min_history].copy()
    print(f"  after min_history={min_history}: {bars['symbol'].nunique():,} symbols", flush=True)

    print("computing indicators ...", flush=True)
    t1 = time.perf_counter()
    metrics = compute_all(bars)
    print(f"  done ({time.perf_counter()-t1:.1f}s)", flush=True)

    print("building sector series ...", flush=True)
    meta_cols = [c for c in ["symbol", "sector", "size_tier_rank", "size_tier", "is_etf"]
                 if c in meta.columns]
    metrics = metrics.merge(meta[meta_cols], on="symbol", how="left")
    if "is_etf" in metrics.columns:
        metrics["is_etf"] = metrics["is_etf"].fillna(False).astype(bool)
    metrics["sector"] = metrics["sector"].fillna(UNCLASSIFIED)
    metrics["size_tier_rank"] = metrics["size_tier_rank"].fillna(9999).astype(int)

    sector_series = build_sector_series(bars, meta)
    sector_series = add_sector_breadth(metrics, sector_series, meta)
    sector_series.to_parquet(SECTOR_PATH, index=False)

    metrics = metrics.merge(
        sector_series[["sector", "date", "sector_index", "sec_ema_fast", "sec_ema_mid",
                       "sec_slope", "sector_uptrend_index", "sector_breadth"]],
        on=["sector", "date"], how="left")

    keep = [c for c in KEEP if c in metrics.columns]
    metrics = metrics[keep]
    for c in metrics.select_dtypes(include=["float64"]).columns:
        metrics[c] = metrics[c].astype("float32")

    config.NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    metrics.to_parquet(METRICS_PATH, index=False)

    # The same panel, lagged one session. Written alongside rather than instead
    # of the raw one: the raw panel is still the right thing for describing what
    # a day looked like, and the screener is the thing that must not see it.
    print("building the as-of-open panel (H015) ...", flush=True)
    metrics_asof = asof.lag_columns(metrics)
    metrics_asof.to_parquet(METRICS_ASOF_PATH, index=False)
    rep = asof.audit(metrics, metrics_asof, sample_symbol="RELIANCE")
    changed = rep["columns"].get("close", {})
    print(f"  lagged {len(metrics_asof):,} rows; `close` differs on "
          f"{changed.get('differing', 0):,} of {changed.get('compared', 0):,} "
          f"comparable rows", flush=True)
    if rep.get("spot_check") and not rep["spot_check"]["match"]:
        raise RuntimeError(f"as-of lag did not shift correctly: {rep['spot_check']}")
    print(f"wrote {METRICS_PATH} ({METRICS_PATH.stat().st_size/1e6:.1f} MB, "
          f"{len(metrics):,} rows) in {time.perf_counter()-t0:.1f}s", flush=True)
    return METRICS_PATH


def load(asof_open: bool = True) -> pd.DataFrame:
    """The metrics panel. `asof_open=True` is the one a morning rule may screen on.

    Defaults to the lagged panel because the unlagged one is what caused H015:
    it carries date D's own close on the row for date D, and the screener gates
    on it while the entry happens at 09:20 that same morning. Anything
    *describing* a day (the UI, characterisation) legitimately wants the
    unlagged panel and should ask for it explicitly.
    """
    if asof_open:
        if not METRICS_ASOF_PATH.exists():
            raise RuntimeError(
                "screen_metrics_asof.parquet missing. Run: "
                "python -m src.cli build-metrics --force\n"
                "This is the panel that does not read the entry day's own close "
                "(H015); screening on the unlagged panel is the lookahead.")
        return pd.read_parquet(METRICS_ASOF_PATH)
    if not METRICS_PATH.exists():
        raise RuntimeError("screen_metrics.parquet missing. Run: python -m src.cli build-metrics")
    return pd.read_parquet(METRICS_PATH)
