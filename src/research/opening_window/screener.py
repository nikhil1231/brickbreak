"""Phase 1: the historical daily screener.

Implements the funnel:

    point-in-time universe (bhavcopy)
      -> tradeability (price / series sanity)
      -> size bucket        (exclude the largest N, configurable)
      -> liquidity          (median daily traded VALUE, not share count)
      -> sector in uptrend
      -> stock in uptrend
      -> preceding volatility contraction
      -> candidate

Nothing is hard-coded as a belief. Every threshold is a field on ScreenConfig so
it can be swept, and every stage records how many names survived it so the
funnel can be inspected rather than trusted.

SECTOR UPTREND — the design question.
NSE publishes no free market-cap file and no per-day sector index history that
covers the smaller names, so sector trend is computed from the bars we already
have, two independent ways:

  1. Equal-weight synthetic sector index. For each sector and date, take the
     mean simple return of its constituents that traded that day, then compound.
     Equal-weight (not cap-weight) because (a) we have no caps, and (b) a
     cap-weighted sector index is really a proxy for its two largest members,
     which is not what "the sector is moving" means to a discretionary trader.
  2. Sector breadth: the fraction of constituents trading above their own
     medium EMA. This is robust to one megacap dragging the index around, and
     is often the better read of broad participation.

Both are exposed; `ScreenConfig.sector_mode` picks which one gates the funnel
(or 'either' / 'both'). Sector labels come from NSE index constituent lists and
cover ~750 symbols; everything else is UNCLASSIFIED and handled per
`sector_require_labelled`.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

from ...research_data.pipelines.sector import UNCLASSIFIED


@dataclass
class ScreenConfig:
    # This is a PRELIMINARY noise filter, not the trading decision. False
    # positives are cheap (one wasted 1-second call); false negatives are
    # expensive (a real setup that never gets looked at). Defaults are therefore
    # deliberately loose — tighten later, once real setups can be scored.

    # --- stage 1: tradeability
    min_price: float = 15.0
    max_price: float = 1e9
    allowed_series: tuple[str, ...] = ("EQ",)
    # ETFs trade in EQ and pass a contraction screen trivially (a liquid/debt
    # ETF has near-zero volatility by design), so they are excluded by default.
    exclude_etfs: bool = True

    # --- stage 2: size. Tiers are the smallest NSE broad index containing the
    # symbol: 50, 100, 200, 500, 750, or 9999 (outside NIFTY Total Market).
    # "generally below the largest ~250" => min_size_rank=250 by default.
    min_size_rank: int = 200
    max_size_rank: int = 100000

    # --- stage 3: liquidity, in rupees crore of median daily traded value
    min_median_tv_cr: float = 0.5
    liq_window: int = 20

    # --- stage 4: sector trend
    sector_mode: str = "either"         # index | breadth | either | both | off
    sector_ema_fast: int = 20
    sector_ema_mid: int = 50
    sector_min_slope: float = -1.0      # % change of fast EMA over 10 bars
    sector_min_breadth: float = 45.0    # % of constituents above their own EMA
    # Only ~750 symbols carry an NSE sector label. Requiring one silently drops
    # ~1,950 mostly-smaller names — exactly the pool this strategy hunts in — so
    # it defaults off and UNCLASSIFIED is treated as its own (broad) sector.
    sector_require_labelled: bool = False
    sector_min_members: int = 5

    # --- stage 5: stock trend
    # EMA stack is a strong condition: a stock consolidating after a run often
    # breaks it briefly. Too strict for a first-pass filter.
    require_ema_stack: bool = False    # ema20 > ema50 > ema200
    require_above_ema_mid: bool = True
    min_ret_60d: float = -100.0

    # --- stage 6: contraction. Each is applied only if not None.
    # contraction_mode="any" means a name passes if it looks contracted on ANY
    # measure. ANDing several measures is the main source of false negatives,
    # since they disagree about what "tight" means.
    contraction_mode: str = "any"       # any | all
    max_atr_ratio: float | None = 0.70
    max_base_depth: float | None = 7.0
    max_bb_width_pctile: float | None = 15.0
    min_contraction_steps: int | None = None
    require_nr_k: bool = False
    max_range_pct_ma: float | None = None
    min_small_bodies_5: int | None = None
    max_vol_squeeze: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------- funnel

STAGES = ["universe", "tradeable", "size", "liquidity", "sector_trend",
          "stock_trend", "contraction"]


def _sector_pass(df: pd.DataFrame, cfg: ScreenConfig) -> pd.Series:
    if cfg.sector_mode == "off":
        return pd.Series(True, index=df.index)
    idx_ok = (df["sector_uptrend_index"].fillna(0) == 1) & (
        df["sec_slope"].fillna(-999) >= cfg.sector_min_slope)
    brd_ok = df["sector_breadth"].fillna(-1) >= cfg.sector_min_breadth
    if cfg.sector_mode == "index":
        ok = idx_ok
    elif cfg.sector_mode == "breadth":
        ok = brd_ok
    elif cfg.sector_mode == "both":
        ok = idx_ok & brd_ok
    else:
        ok = idx_ok | brd_ok
    if cfg.sector_require_labelled:
        ok = ok & (df["sector"] != UNCLASSIFIED)
    return ok


def _contraction_pass(df: pd.DataFrame, cfg: ScreenConfig) -> pd.Series:
    """Combine the contraction family under `contraction_mode`.

    "all" = every enabled measure must agree (strict, many false negatives).
    "any" = one enabled measure is enough (lax, the first-pass default).
    """
    tests: list[pd.Series] = []
    if cfg.max_atr_ratio is not None:
        tests.append(df["atr_ratio"] <= cfg.max_atr_ratio)
    if cfg.max_base_depth is not None:
        tests.append(df["base_depth"] <= cfg.max_base_depth)
    if cfg.max_bb_width_pctile is not None:
        tests.append(df["bb_width_pctile"] <= cfg.max_bb_width_pctile)
    if cfg.min_contraction_steps is not None:
        tests.append(df["contraction_steps"] >= cfg.min_contraction_steps)
    if cfg.require_nr_k:
        tests.append(df["nr_k"] == 1)
    if cfg.max_range_pct_ma is not None:
        tests.append(df["range_pct_ma"] <= cfg.max_range_pct_ma)
    if cfg.min_small_bodies_5 is not None:
        tests.append(df["n_small_bodies_5"] >= cfg.min_small_bodies_5)
    if cfg.max_vol_squeeze is not None:
        tests.append(df["vol_squeeze"] <= cfg.max_vol_squeeze)

    if not tests:
        return pd.Series(True, index=df.index)
    acc = tests[0].fillna(False)
    for t in tests[1:]:
        t = t.fillna(False)
        acc = (acc & t) if cfg.contraction_mode == "all" else (acc | t)
    return acc


def run_screen(metrics: pd.DataFrame, cfg: ScreenConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the funnel. Returns (candidates, per-date stage counts)."""
    d = metrics
    masks: dict[str, pd.Series] = {}

    masks["universe"] = pd.Series(True, index=d.index)
    # Price bounds apply to the price that actually traded that day. Back
    # adjustment scales history down — TATASTEEL trades at ~95 pre-split in
    # adjusted terms but printed ~950 — so screening on the adjusted price
    # would silently rewrite which names were ever cheap enough to exclude.
    px = d["close_raw"] if "close_raw" in d.columns else d["close"]
    tradeable = (
        px.between(cfg.min_price, cfg.max_price)
        & d["series"].isin(cfg.allowed_series)
        & d["volume"].gt(0)
    )
    if cfg.exclude_etfs and "is_etf" in d.columns:
        tradeable &= ~d["is_etf"].fillna(False).astype(bool)
    masks["tradeable"] = tradeable
    masks["size"] = d["size_tier_rank"].between(cfg.min_size_rank + 1, cfg.max_size_rank)
    masks["liquidity"] = d["median_tv_20_cr"] >= cfg.min_median_tv_cr
    masks["sector_trend"] = _sector_pass(d, cfg)

    stock_ok = pd.Series(True, index=d.index)
    if cfg.require_ema_stack:
        stock_ok &= d["ema_stack_up"] == 1
    if cfg.require_above_ema_mid:
        stock_ok &= d["above_ema_mid"] == 1
    stock_ok &= d["ret_60d"].fillna(-999) >= cfg.min_ret_60d
    masks["stock_trend"] = stock_ok.fillna(False)
    masks["contraction"] = _contraction_pass(d, cfg)

    # Cumulative funnel: each stage counted among survivors of all prior stages.
    cum = pd.Series(True, index=d.index)
    counts = []
    for stage in STAGES:
        cum = cum & masks[stage].fillna(False)
        counts.append(pd.DataFrame({"date": d["date"], "stage": stage, "pass": cum}))

    stage_counts = (pd.concat(counts)
                    .groupby(["date", "stage"])["pass"].sum().unstack(fill_value=0))
    stage_counts = stage_counts.reindex(columns=STAGES, fill_value=0).reset_index()

    return d[cum].copy(), stage_counts


def summarize(stage_counts: pd.DataFrame) -> dict:
    tail = stage_counts.tail(250)
    cand = tail["contraction"]
    return {
        "n_dates": int(len(stage_counts)),
        "mean_per_stage": {s: round(float(stage_counts[s].mean()), 1) for s in STAGES},
        "candidates_per_day": {
            "mean": round(float(cand.mean()), 2),
            "median": float(cand.median()),
            "p90": float(cand.quantile(0.9)),
            "max": int(cand.max()),
            "zero_days_pct": round(float((cand == 0).mean() * 100), 1),
        },
    }
