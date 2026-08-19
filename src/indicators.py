"""Daily indicators: trend, liquidity, and volatility-contraction measures.

All functions operate on a single symbol's date-sorted frame and return Series
aligned to it. Nothing here decides anything — thresholds live in the screener
config so they can be swept, per the brief: measure first, decide later.

CONTRACTION — the design question.
There is no single right definition, and the trader's description ("preceding
volatility contraction / consolidation, often small-range or doji-like candles")
maps onto several measurable things that do not always agree. So we compute a
family of complementary metrics rather than one composite score:

  1. atr_ratio      ATR(fast)/ATR(slow). The classic squeeze measure. Falls when
                    recent true range is small relative to the longer baseline.
  2. range_pct_ma   Mean of (high-low)/close over k days. Absolute tightness,
                    unlike atr_ratio which is relative.
  3. base_depth     (max high - min low)/close over k days. How tight the whole
                    consolidation is, not just individual candles. This is what
                    a chartist actually sees as "a base".
  4. bb_width       Bollinger width (2σ)/mid, and its percentile rank over a
                    lookback. Percentile matters because a 3% width is tight for
                    a smallcap and loose for a large cap.
  5. nr_k           Is today the narrowest range of the last k days? (NR4/NR7)
  6. body_ratio     |close-open|/(high-low). Small = doji-like indecision.
  7. inside_day     Today's range fully inside yesterday's.
  8. vol_squeeze    mean volume(fast)/mean volume(slow). Volume typically dries
                    up into a proper base; expansion on the breakout is the
                    signal the opening-volume rule is trying to catch.
  9. contraction_steps  Counts successively smaller swings (a VCP-style read):
                    compares range over the last k days vs the k before it vs the
                    k before that. Captures "tightening" rather than "tight".

Percentile-ranked variants are provided because absolute thresholds do not
transfer across price levels or across market regimes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ------------------------------------------------------------------ trend

def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False, min_periods=span).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    a = df["high"] - df["low"]
    b = (df["high"] - prev_close).abs()
    c = (df["low"] - prev_close).abs()
    return pd.concat([a, b, c], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def slope_pct(s: pd.Series, n: int) -> pd.Series:
    """Percent change of a series over n bars — used for EMA slope."""
    return (s / s.shift(n) - 1.0) * 100.0


# ------------------------------------------------------- contraction family

def rolling_percentile(s: pd.Series, window: int) -> pd.Series:
    """Percentile rank of the latest value within its trailing window (0-100)."""
    return s.rolling(window, min_periods=max(5, window // 4)).rank(pct=True) * 100.0


def compute_indicators(
    df: pd.DataFrame,
    ema_fast: int = 20,
    ema_mid: int = 50,
    ema_slow: int = 200,
    atr_fast: int = 5,
    atr_slow: int = 20,
    base_len: int = 10,
    bb_len: int = 20,
    pct_window: int = 250,
    nr_k: int = 7,
    liq_window: int = 20,
) -> pd.DataFrame:
    """Add every indicator column for one symbol's date-sorted history."""
    d = df.sort_values("date").copy()
    c, h, l, o = d["close"], d["high"], d["low"], d["open"]

    # --- trend
    d["ema_fast"] = ema(c, ema_fast)
    d["ema_mid"] = ema(c, ema_mid)
    d["ema_slow"] = ema(c, ema_slow)
    d["ema_fast_slope"] = slope_pct(d["ema_fast"], 10)
    d["ema_mid_slope"] = slope_pct(d["ema_mid"], 20)
    d["px_vs_ema_fast"] = (c / d["ema_fast"] - 1) * 100
    d["px_vs_ema_mid"] = (c / d["ema_mid"] - 1) * 100
    d["ema_stack_up"] = ((d["ema_fast"] > d["ema_mid"]) & (d["ema_mid"] > d["ema_slow"])).astype("Int8")
    d["above_ema_mid"] = (c > d["ema_mid"]).astype("Int8")

    # --- liquidity (traded value, not share count: 100k shares of a Rs.50 stock
    #     and of a Rs.2000 stock are entirely different things)
    if "turnover" in d.columns:
        tv = d["turnover"]
    else:
        tv = c * d["volume"]
    d["traded_value"] = tv
    d["median_tv_20"] = tv.rolling(liq_window, min_periods=max(5, liq_window // 2)).median()
    d["median_tv_20_cr"] = d["median_tv_20"] / 1e7          # rupees -> crore
    d["median_vol_20"] = d["volume"].rolling(liq_window, min_periods=5).median()

    # --- contraction family
    tr = true_range(d)
    d["atr_fast"] = atr(d, atr_fast)
    d["atr_slow"] = atr(d, atr_slow)
    d["atr_ratio"] = d["atr_fast"] / d["atr_slow"]
    d["atr_pct"] = d["atr_slow"] / c * 100

    d["range_pct"] = (h - l) / c * 100
    d["range_pct_ma"] = d["range_pct"].rolling(base_len, min_periods=3).mean()

    base_hi = h.rolling(base_len, min_periods=3).max()
    base_lo = l.rolling(base_len, min_periods=3).min()
    d["base_depth"] = (base_hi - base_lo) / c * 100

    mid = c.rolling(bb_len, min_periods=bb_len // 2).mean()
    sd = c.rolling(bb_len, min_periods=bb_len // 2).std()
    d["bb_width"] = (4 * sd) / mid * 100          # full 2-sigma band width, % of price
    d["bb_width_pctile"] = rolling_percentile(d["bb_width"], pct_window)
    d["atr_ratio_pctile"] = rolling_percentile(d["atr_ratio"], pct_window)
    d["base_depth_pctile"] = rolling_percentile(d["base_depth"], pct_window)

    d["nr_k"] = (d["range_pct"] == d["range_pct"].rolling(nr_k, min_periods=nr_k).min()).astype("Int8")
    rng = (h - l).replace(0, np.nan)
    d["body_ratio"] = ((c - o).abs() / rng * 100)
    d["inside_day"] = ((h <= h.shift(1)) & (l >= l.shift(1))).astype("Int8")
    d["doji_like"] = (d["body_ratio"] < 25).astype("Int8")
    d["n_small_bodies_5"] = d["doji_like"].rolling(5, min_periods=3).sum()

    vf = d["volume"].rolling(5, min_periods=3).mean()
    vs = d["volume"].rolling(20, min_periods=10).mean()
    d["vol_squeeze"] = vf / vs

    # Successive-contraction read: is each block of `base_len` days tighter than
    # the one before it? 2 = steadily tightening, which is the VCP shape.
    r1 = (h.rolling(base_len).max() - l.rolling(base_len).min()) / c
    r2 = r1.shift(base_len)
    r3 = r1.shift(2 * base_len)
    d["contraction_steps"] = ((r1 < r2).astype("Int8") + (r2 < r3).astype("Int8"))

    # --- context used for reporting, never for filtering
    d["ret_20d"] = (c / c.shift(20) - 1) * 100
    d["ret_60d"] = (c / c.shift(60) - 1) * 100
    d["dist_52w_high"] = (c / h.rolling(250, min_periods=60).max() - 1) * 100
    d["gap_pct"] = (o / c.shift(1) - 1) * 100
    return d


def compute_all(bars: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Apply compute_indicators per symbol across the whole panel."""
    out = [compute_indicators(g, **kwargs) for _, g in bars.groupby("symbol", sort=False)]
    return pd.concat(out, ignore_index=True)
