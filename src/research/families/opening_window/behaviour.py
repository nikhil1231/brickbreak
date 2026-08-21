"""The opening window as developing *behaviour*, not as a snapshot of levels.

WHY THIS EXISTS
`entry_window.py` answers "what is the price and the running low at `t`". That
is enough to place a stop and not enough to recognise a setup. The discretionary
strategy is not plausibly `enter at t=120s if volume > X and gap > Y`; it is a
person watching a stock that has contracted, opens constructively, attracts
unusually strong demand that *keeps arriving*, refuses to be pushed below its
open, and starts to look like sustained accumulation rather than one print. This
module turns that description into features that can be wrong.

Everything here is computed **causally at each `t`**: a feature at t=90s uses no
bar after 09:16:30. That is asserted structurally (cumulative statistics sampled
at `t`), not by convention.

WHAT THE DATA ACTUALLY SUPPORTS, WHICH IS LESS THAN IT LOOKS LIKE
Breeze's `1second` endpoint is not the tape. Measured on this panel:

- **Median inter-bar gap is 5s** (p90 8s, p99 15s); a median morning has ~54
  bars across 300 seconds. There is no 1-second resolution to exploit and any
  feature claiming sub-30s structure is reading sampling noise.
- **~50% of bars carry `volume == 0`**, and 94% have OHLC all equal — they are
  price snapshots, not trades. 27.8% of zero-volume bars are followed
  immediately by a bar at the *same price* carrying volume, i.e. **volume is
  smeared several seconds behind price**. Window totals are trustworthy;
  1-second volume timing is not.

Both facts point the same way, so every volume-shape feature here is computed on
**30-second buckets** and never on raw bars.

THE DECAY TRAP
Opening volume decays by default. Pool-mean shares by 30s bucket run 15.4%,
9.6%, 13.2%, 12.0%, 10.2%, 9.0%, 9.9%, 7.3%, 7.1%, 6.4%. Measured against a flat
prior, *every* morning is a "fading spike" and the feature just re-encodes the
clock. Persistence is therefore only meaningful **relative to the pool on the
same day**, which is what the `_xr` cross-sectional ranks are for. Use those, not
the raw values, whenever the question is "was this morning unusual".

THE CENSORING TRAP, CARRIED FORWARD
Phase 2.3 found `om_low_vs_open_pct` censored at zero, with 36.2% of mornings
exactly on the boundary and the rate rising to 55% in the thinnest turnover
quintile. The mechanism is here in plain sight: a stock that prints 12 ticks in
five minutes has a running low equal to its open because nothing traded below
it, not because buyers defended it. `n_ticks_t` and `tick_rate_t` are therefore
on every row, and any occupancy or low-based feature must be read conditional on
them. `time_above_open_frac` is the intended replacement (H010): it asks how
long price *stayed* above the open rather than how far it dipped, and it is
weighted by dwell time so a thin morning cannot score highly by sitting still —
sitting still above the open is exactly the state being measured, and sitting
still below it scores zero.

WHAT THIS MODULE DOES NOT DO
It does not score a morning, rank one against another, or define an entry. It
produces a causally-evaluated feature panel. Scoring lives in `archetypes.py`
(interpretable) and `explore.py` (statistical), and neither is a strategy.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ....core import config
from ....research_data import repository
from ....research_data.pipelines import renames

TICKS_DIR = config.NORMALIZED_DIR / "opening_1s"
BEHAVIOUR_PATH = config.NORMALIZED_DIR / "opening_behaviour.parquet"

# Features whose meaning is "unusual compared with other mornings", which is
# only answerable against the same session's cross-section. Ranked within date.
CROSS_SECTIONAL = (
    "vol_rel_daily_pct", "tick_rate_t", "vol_hhi", "active_bucket_frac",
    "vol_late_early_ratio", "path_efficiency", "abs_path_efficiency",
    "chaos_vs_atr", "churn_vs_atr", "time_above_open_frac", "px_vs_vwap_pct",
    "uptick_vol_share", "dd_from_high_pct", "range_pos", "low_slope_pct_per_min",
    "move_per_vol", "ret_after_peak_vol_pct", "entry_vs_open_pct",
)


@dataclass(frozen=True)
class BehaviourConfig:
    """Measurement choices. None of these is a strategy parameter.

    `bucket_s` is floored at 30 by the sampling rate of the feed, not chosen:
    at a median 5s inter-bar gap a 30s bucket holds ~5 observations and a 10s
    bucket holds ~2, which is not enough to say anything about shape.
    """
    offsets_s: tuple[int, ...] = (30, 60, 90, 120, 150, 180, 210, 240, 270, 300)
    bucket_s: int = 30
    session_start: str = "09:15:00"
    # Below this many bars through `t`, shape features are meaningless and are
    # emitted as NaN rather than as a confident-looking zero. Not a filter: the
    # row is kept, and `sparse_t` marks it so the thin cohort can be studied
    # rather than silently dropped.
    min_bars_for_shape: int = 8


def load_ticks(ticks_dir: Path = TICKS_DIR,
               dates: list[pd.Timestamp] | None = None,
               date_min: pd.Timestamp | None = None,
               date_max: pd.Timestamp | None = None,
               rmap: pd.DataFrame | None = None) -> pd.DataFrame:
    """1-second opening bars, canonical tickers, with `elapsed` seconds.

    `date_min`/`date_max` exist so the holdout fence in `explore.py` can be
    applied at load time. Symbols fold through `renames.canonical_map()` for the
    same reason as everywhere else: the pull ran against whatever ticker was
    current that day and the daily panel is keyed on the post-rename one.
    """
    files = sorted(ticks_dir.glob("*.parquet"))
    if dates is not None:
        want = {pd.Timestamp(d).strftime("%Y-%m-%d") for d in dates}
        files = [f for f in files if f.stem in want]
    if date_min is not None:
        files = [f for f in files if f.stem >= pd.Timestamp(date_min).strftime("%Y-%m-%d")]
    if date_max is not None:
        files = [f for f in files if f.stem <= pd.Timestamp(date_max).strftime("%Y-%m-%d")]
    if not files:
        return pd.DataFrame()

    df = repository.opening_ticks(files)
    rmap = renames.load_map() if rmap is None else rmap
    cmap = renames.canonical_map(rmap)
    if cmap:
        df["symbol"] = df["symbol"].map(lambda s: cmap.get(s, s))
    df["date"] = df["timestamp"].dt.normalize()
    df["elapsed"] = (df["timestamp"] - df["date"]
                     - pd.Timedelta("09:15:00")).dt.total_seconds()
    # A handful of bars land outside the window on halted or odd sessions.
    return df[(df["elapsed"] >= 0) & (df["elapsed"] <= 300)].reset_index(drop=True)


def _prepare(ticks: pd.DataFrame, day_open: pd.DataFrame,
             cfg: BehaviourConfig) -> pd.DataFrame:
    """Per-tick quantities that only need to be computed once.

    Everything downstream is a cumulative sum, min or max of one of these
    columns, which is what makes "no information after `t`" structural: a
    cumulative statistic sampled at the last bar with `elapsed <= t` cannot see
    past `t` even if the sampling is wrong.
    """
    d = ticks.sort_values(["symbol", "date", "timestamp"]).reset_index(drop=True)
    d = d.merge(day_open, on=["symbol", "date"], how="left")

    g = d.groupby(["symbol", "date"], sort=False)
    prev_close = g["close"].shift(1)

    # Dwell time: how long this price stood before the next observation.
    #
    # CAREFUL — this column peeks. The gap to the *next* bar is only known once
    # that bar has printed, and for the last bar at or before `t` the next bar
    # lies after `t`. Summing this naively makes an occupancy feature depend on
    # when the market next traded, which is information from the future: a
    # morning that goes quiet after 09:16:30 and one that keeps trading get
    # different answers at t=90s for the same first 90 seconds.
    #
    # It is kept in this form because it is the cheap cumulative primitive, and
    # `features_at` corrects the final bar's contribution against `t` exactly.
    # Nothing else may use it directly.
    d["dwell_s"] = (-g["elapsed"].diff(-1)).fillna(0.0).clip(lower=0)

    d["dpx"] = (d["close"] - prev_close).fillna(0.0)
    d["abs_dpx"] = d["dpx"].abs()

    # Tick rule for signed volume. A zero-volume bar carries no trade, and the
    # direction of a bar whose price did not change is the direction of the last
    # change that did happen — the standard forward-fill, which matters here
    # because the feed smears volume a few seconds behind price.
    sign = np.sign(d["dpx"]).replace(0, np.nan)
    d["tick_dir"] = sign.groupby([d["symbol"], d["date"]]).ffill().fillna(0.0)
    vol = d["volume"].clip(lower=0)          # negative volume is an archive defect
    d["up_vol"] = np.where(d["tick_dir"] > 0, vol, 0.0)
    d["signed_vol"] = d["tick_dir"] * vol
    d["pxvol"] = d["close"] * vol
    d["vol_c"] = vol

    above = (d["close"] >= d["day_open"]).astype(float)
    d["above_open_dwell"] = above * d["dwell_s"]
    d["above_open_tick"] = above

    d["bucket"] = (d["elapsed"] // cfg.bucket_s).astype(int).clip(
        upper=300 // cfg.bucket_s - 1)
    return d


def _bucket_table(prep: pd.DataFrame, cfg: BehaviourConfig) -> pd.DataFrame:
    """Volume and price extremes per 30s bucket — the finest honest resolution.

    Dense over all buckets in the window so that cumulative shape statistics at
    each `t` have a fixed denominator and an empty bucket reads as "nothing
    traded", which is information, rather than as a missing row.
    """
    n_buckets = 300 // cfg.bucket_s
    b = prep.groupby(["symbol", "date", "bucket"], sort=True).agg(
        b_vol=("vol_c", "sum"),
        b_low=("low", "min"),
        b_high=("high", "max"),
        b_close=("close", "last"),
        b_open=("close", "first"),
        b_n=("close", "size"),
    ).reset_index()

    keys = b[["symbol", "date"]].drop_duplicates()
    full = keys.merge(pd.DataFrame({"bucket": range(n_buckets)}), how="cross")
    b = full.merge(b, on=["symbol", "date", "bucket"], how="left")
    b["b_vol"] = b["b_vol"].fillna(0.0)
    b["b_n"] = b["b_n"].fillna(0).astype(int)
    return b.sort_values(["symbol", "date", "bucket"]).reset_index(drop=True)


def _shape_at(bt: pd.DataFrame, k: int, cfg: BehaviourConfig) -> pd.DataFrame:
    """Volume-shape and higher-low statistics over the first `k` buckets.

    Written as closed-form group sums rather than a per-morning apply: this runs
    once per entry time over ~64k mornings, and a Python-level lambda over
    640k groups is minutes of nothing.

    Herfindahl is normalised to [0, 1] against the number of buckets *elapsed*,
    so t=60s (two buckets) and t=300s (ten) are on the same scale: 0 is volume
    spread perfectly evenly, 1 is all of it in one bucket. Without that
    normalisation the statistic would fall with `t` mechanically and every
    comparison across `t` would be reading the clock rather than the stock.
    """
    sub = bt[bt["bucket"] < k].copy()
    key = ["symbol", "date"]

    sub["_v2"] = sub["b_vol"] ** 2
    agg = sub.groupby(key, sort=False).agg(
        _vsum=("b_vol", "sum"), _v2sum=("_v2", "sum")).reset_index()
    tot = agg["_vsum"].where(agg["_vsum"] > 0)
    hhi_raw = agg["_v2sum"] / (tot ** 2)
    agg["vol_hhi"] = ((hhi_raw - 1.0 / k) / (1.0 - 1.0 / k)) if k > 1 else np.nan

    # Buckets carrying a non-trivial share of the morning's flow. "Non-trivial"
    # is a fifth of the even-split rate: the question is whether flow kept
    # arriving at all, not whether it arrived evenly, which `vol_hhi` covers.
    sub = sub.merge(agg[key + ["_vsum"]], on=key, how="left")
    sub["_active"] = (sub["b_vol"] > 0.2 * sub["_vsum"] / k) & (sub["_vsum"] > 0)
    act = sub.groupby(key, sort=False)["_active"].mean().rename(
        "active_bucket_frac").reset_index()

    # Late-vs-early volume *rate*, in logs. The pseudo-count is a fraction of
    # the morning's own volume rather than a fixed number of shares: a flat "+1"
    # is scale-dependent and makes a 500-share stock and a 5-million-share stock
    # incomparable. Read against the pool's own ratio, which sits well below
    # zero by construction (see the module docstring), never against zero.
    half = max(k // 2, 1)
    early = sub[sub["bucket"] < half].groupby(key, sort=False)["b_vol"].sum()
    late = sub[sub["bucket"] >= half].groupby(key, sort=False)["b_vol"].sum()
    tot_v = sub.groupby(key, sort=False)["b_vol"].sum()
    eps = 0.01 * tot_v
    ler = np.log((late.reindex(tot_v.index).fillna(0) + eps)
                 / (early.reindex(tot_v.index).fillna(0) + eps))
    ler = ler.where(tot_v > 0).rename("vol_late_early_ratio").reset_index()

    # "Higher lows": OLS slope of the per-bucket low against bucket index, from
    # group sums. Buckets that did not trade have no low and are skipped rather
    # than interpolated — an invented low would manufacture the very trend the
    # feature is looking for.
    v = sub.dropna(subset=["b_low"]).copy()
    v["_x"] = v["bucket"].astype(float)
    v["_y"] = v["b_low"].astype(float)
    v["_xy"] = v["_x"] * v["_y"]
    v["_xx"] = v["_x"] ** 2
    s = v.groupby(key, sort=False).agg(
        _n=("_x", "size"), _sx=("_x", "sum"), _sy=("_y", "sum"),
        _sxy=("_xy", "sum"), _sxx=("_xx", "sum")).reset_index()
    denom = s["_n"] * s["_sxx"] - s["_sx"] ** 2
    slope = (s["_n"] * s["_sxy"] - s["_sx"] * s["_sy"]) / denom.where(denom != 0)
    s["low_slope_price_per_min"] = slope.where(s["_n"] >= 3) * (60.0 / cfg.bucket_s)

    v = v.sort_values(key + ["bucket"])
    prev_low = v.groupby(key, sort=False)["_y"].shift(1)
    v["_up"] = (v["_y"] >= prev_low)
    mono = v[prev_low.notna()].groupby(key, sort=False)["_up"].agg(
        ["mean", "size"]).reset_index()
    mono["low_higher_frac"] = mono["mean"].where(mono["size"] >= 2)

    # Where the heaviest bucket sat, and what price did after it. "Do gains hold
    # once the volume arrives" needs the volume located before it can be asked.
    peak = sub.loc[sub.groupby(key, sort=False)["b_vol"].idxmax(),
                   key + ["bucket", "b_close"]].rename(
        columns={"bucket": "peak_vol_bucket", "b_close": "peak_vol_close"})

    out = agg[key + ["vol_hhi"]]
    for part, cols in ((act, ["active_bucket_frac"]),
                       (ler, ["vol_late_early_ratio"]),
                       (s, ["low_slope_price_per_min"]),
                       (mono, ["low_higher_frac"]),
                       (peak, ["peak_vol_bucket", "peak_vol_close"])):
        out = out.merge(part[key + cols], on=key, how="left")
    return out


def features_at(prep: pd.DataFrame, bt: pd.DataFrame, t: int,
                cfg: BehaviourConfig) -> pd.DataFrame:
    """Every behavioural feature, as of `t` seconds after 09:15:00.

    Built from cumulative statistics over bars with `elapsed <= t`. No column
    here can see past `t`; that is a property of the construction rather than a
    discipline applied afterwards.
    """
    sub = prep[prep["elapsed"] <= t]
    if sub.empty:
        return pd.DataFrame()
    g = sub.groupby(["symbol", "date"], sort=False)

    f = g.agg(
        day_open=("day_open", "first"),
        first_px=("close", "first"),
        price_t=("close", "last"),
        running_low_t=("low", "min"),
        running_high_t=("high", "max"),
        n_ticks_t=("close", "size"),
        vol_t=("vol_c", "sum"),
        up_vol_t=("up_vol", "sum"),
        pxvol_t=("pxvol", "sum"),
        abs_path=("abs_dpx", "sum"),
        dwell_total=("dwell_s", "sum"),
        dwell_above=("above_open_dwell", "sum"),
        ticks_above=("above_open_tick", "sum"),
        px_sd=("dpx", "std"),
        last_elapsed=("elapsed", "last"),
        first_elapsed=("elapsed", "first"),
        last_dwell=("dwell_s", "last"),
        last_above=("above_open_tick", "last"),
    ).reset_index()

    # Undo the final bar's forward-looking dwell and replace it with the time
    # actually remaining to `t`. Without this the occupancy features below read
    # the arrival time of a trade that has not happened yet — see `_prepare`.
    f["dwell_above"] = (f["dwell_above"]
                        - f["last_above"] * f["last_dwell"]
                        + f["last_above"] * (t - f["last_elapsed"]))
    f["dwell_total"] = t - f["first_elapsed"]

    f["t_offset_s"] = t
    f["tick_rate_t"] = f["n_ticks_t"] / t
    f["sparse_t"] = f["n_ticks_t"] < cfg.min_bars_for_shape

    # --- price path -------------------------------------------------------
    o = f["day_open"].where(f["day_open"] > 0)
    f["entry_vs_open_pct"] = (f["price_t"] / o - 1) * 100
    f["low_vs_open_pct"] = (f["running_low_t"] / o - 1) * 100
    f["high_vs_open_pct"] = (f["running_high_t"] / o - 1) * 100
    f["dd_from_high_pct"] = (f["price_t"] / f["running_high_t"] - 1) * 100
    rng = (f["running_high_t"] - f["running_low_t"])
    f["range_t_pct"] = (rng / o) * 100
    # Where in the developing range the price sits. Undefined on a morning that
    # has not moved at all, which is a real state and is left NaN, not 0.5.
    f["range_pos"] = ((f["price_t"] - f["running_low_t"]) / rng.where(rng > 0))

    # Orderly vs chaotic: net move over total absolute movement. Signed, so a
    # clean decline scores -1 and churn scores ~0.
    f["path_efficiency"] = ((f["price_t"] - f["first_px"])
                            / f["abs_path"].where(f["abs_path"] > 0))
    # Total distance travelled, kept so churn can be scaled by the stock's own
    # ATR downstream rather than compared across names in price units.
    f["abs_path_efficiency"] = f["path_efficiency"].abs()

    # --- occupancy: "refuses to trade below the open" (H010) ---------------
    f["time_above_open_frac"] = (f["dwell_above"]
                                 / f["dwell_total"].where(f["dwell_total"] > 0))
    f["ticks_above_open_frac"] = f["ticks_above"] / f["n_ticks_t"]
    f["low_at_open_exact"] = (f["running_low_t"] >= f["day_open"] - 1e-9)

    # --- volume-price coupling (H011) -------------------------------------
    f["vwap_t"] = f["pxvol_t"] / f["vol_t"].where(f["vol_t"] > 0)
    f["px_vs_vwap_pct"] = (f["price_t"] / f["vwap_t"] - 1) * 100
    f["uptick_vol_share"] = f["up_vol_t"] / f["vol_t"].where(f["vol_t"] > 0)

    # --- shape over 30s buckets -------------------------------------------
    k = max(int(t // cfg.bucket_s), 1)
    f = f.merge(_shape_at(bt, k, cfg), on=["symbol", "date"], how="left")
    f["low_slope_pct_per_min"] = f["low_slope_price_per_min"] / o * 100
    # Return since the heaviest volume bucket closed: did the move hold?
    f["ret_after_peak_vol_pct"] = (f["price_t"] / f["peak_vol_close"] - 1) * 100
    f["peak_vol_bucket_frac"] = f["peak_vol_bucket"] / max(k - 1, 1)

    # Shape statistics on a morning with a handful of prints describe the
    # sampling, not the stock. Emitted as NaN so they cannot be averaged in.
    shape_cols = ["vol_hhi", "active_bucket_frac", "vol_late_early_ratio",
                  "low_slope_pct_per_min", "low_higher_frac", "path_efficiency",
                  "abs_path_efficiency", "ret_after_peak_vol_pct"]
    f.loc[f["sparse_t"], shape_cols] = np.nan

    f = f.rename(columns={"abs_path": "path_len"})
    drop = ["pxvol_t", "up_vol_t", "dwell_total", "dwell_above",
            "ticks_above", "low_slope_price_per_min", "peak_vol_close",
            "last_elapsed", "first_elapsed", "last_dwell", "last_above"]
    return f.drop(columns=[c for c in drop if c in f.columns])


def add_context_scaled(f: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """Scale raw activity by what is normal for the symbol, not for the pool.

    `median_vol_20` comes off the full daily panel, so it is the one normaliser
    in this project that is not selection-biased: a trailing average built from
    the opening ticks themselves would only ever average days that already
    passed the screen (Phase 2.3).
    """
    cols = [c for c in ("symbol", "date", "median_vol_20", "atr_pct",
                        "median_tv_20_cr") if c in daily.columns]
    d = f.merge(daily[cols], on=["symbol", "date"], how="left")

    mv = d["median_vol_20"].where(d["median_vol_20"] > 0)
    d["vol_rel_daily_pct"] = d["vol_t"] / mv * 100
    # Volume arriving per elapsed minute, as a share of a normal day. Separates
    # "a lot of volume because it is late" from "a lot of volume".
    d["vol_rate_rel_daily"] = d["vol_rel_daily_pct"] / (d["t_offset_s"] / 60.0)

    # Churn relative to the stock's own normal daily range: the same absolute
    # movement means different things on a 1% ATR name and a 6% one. Two
    # variants, because they fail differently. `churn_vs_atr` is total path
    # length and answers "how much of a normal day did this stock travel in the
    # first `t` seconds", but it grows with the number of prints and so carries
    # a liquidity tilt. `chaos_vs_atr` is the per-print dispersion and does not,
    # but it says nothing about how far the stock actually went. Both are kept
    # and `tick_rate_t` is on every row so either can be conditioned.
    atr = d["atr_pct"].where(d["atr_pct"] > 0)
    d["chaos_vs_atr"] = (d["px_sd"] / d["day_open"] * 100) / atr
    d["churn_vs_atr"] = (d["path_len"] / d["day_open"] * 100) / atr
    # Heavy volume with little price progress (H011): progress per unit of
    # unusual volume. Small values are the absorption/supply state.
    d["move_per_vol"] = (d["entry_vs_open_pct"].abs()
                         / d["vol_rel_daily_pct"].where(d["vol_rel_daily_pct"] > 0.05))
    return d


def add_cross_sectional_ranks(f: pd.DataFrame,
                              cols: tuple[str, ...] = CROSS_SECTIONAL) -> pd.DataFrame:
    """Percentile rank within (date, t) — the only scale on which "unusual" means anything.

    Two problems disappear at once. Market-wide days (every stock heavy, every
    stock quiet) stop masquerading as stock-specific signal. And the pool's
    built-in volume decay stops making every morning look like a fading spike,
    because the comparison is against other mornings at the same point in the
    same session rather than against a flat prior.
    """
    d = f.copy()
    have = [c for c in cols if c in d.columns]
    g = d.groupby(["date", "t_offset_s"], sort=False)
    for c in have:
        d[c + "_xr"] = g[c].rank(pct=True)
    return d


def build(cfg: BehaviourConfig | None = None,
          date_min: pd.Timestamp | None = None,
          date_max: pd.Timestamp | None = None,
          save: bool = True, verbose: bool = True) -> pd.DataFrame:
    """The full behavioural panel: one row per (symbol, date, t)."""
    cfg = cfg or BehaviourConfig()
    daily = repository.daily_bars(
        columns=["symbol", "date", "open_raw", "adj_factor"])
    metrics_cols = ["symbol", "date", "median_vol_20", "atr_pct", "median_tv_20_cr"]
    # The **as-of** panel, not the raw one. `median_vol_20` and `atr_pct` are
    # rolling windows that *include* date D, so normalising an opening-window
    # feature by the raw column divides by a number containing date D's own
    # full-day volume and range — a lookahead hidden inside a denominator,
    # which is the easiest kind to miss. See H015 / `asof.py`.
    metrics = repository.screen_metrics(columns=metrics_cols)

    ticks = load_ticks(date_min=date_min, date_max=date_max)
    if ticks.empty:
        raise RuntimeError("no opening tick files in range")

    day_open = daily.rename(columns={"open_raw": "day_open"})[
        ["symbol", "date", "day_open"]]
    prep = _prepare(ticks, day_open, cfg)
    bt = _bucket_table(prep, cfg)

    out = []
    for t in cfg.offsets_s:
        f = features_at(prep, bt, t, cfg)
        if not f.empty:
            out.append(f)
        if verbose:
            print(f"    t={t:>3}s  {len(f):,} mornings")
    panel = pd.concat(out, ignore_index=True)
    panel = add_context_scaled(panel, metrics)
    panel = add_cross_sectional_ranks(panel)
    panel = panel.merge(daily[["symbol", "date", "adj_factor"]],
                        on=["symbol", "date"], how="left")

    if save:
        config.NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(BEHAVIOUR_PATH, index=False)
    if verbose:
        print(f"  {len(panel):,} rows, {panel['symbol'].nunique():,} symbols, "
              f"{panel['date'].nunique():,} sessions -> "
              f"{BEHAVIOUR_PATH.relative_to(config.PROJECT_ROOT)}")
    return panel


def check_causality(panel: pd.DataFrame, prep: pd.DataFrame,
                    sample: int = 200, seed: int = 0) -> dict:
    """Recompute a sample of rows from truncated ticks and require an exact match.

    The guarantee that no feature sees past `t` rests on cumulative statistics
    being sampled at `t`. This tests it the only way worth testing: rebuild the
    row from a tick series that has been physically truncated at `t`, so a
    lookahead would have nothing to leak from, and require the same numbers.
    """
    rows = panel.sample(min(sample, len(panel)), random_state=seed)
    cfg = BehaviourConfig()
    bad = []
    for _, r in rows.iterrows():
        t = int(r["t_offset_s"])
        cut = prep[(prep["symbol"] == r["symbol"]) & (prep["date"] == r["date"])
                   & (prep["elapsed"] <= t)]
        if cut.empty:
            continue
        for col, val in (("price_t", cut["close"].iloc[-1]),
                         ("running_low_t", cut["low"].min()),
                         ("running_high_t", cut["high"].max()),
                         ("n_ticks_t", len(cut)),
                         ("vol_t", cut["vol_c"].sum())):
            if not np.isclose(float(r[col]), float(val), rtol=1e-9, atol=1e-9):
                bad.append((r["symbol"], str(r["date"]), t, col,
                            float(r[col]), float(val)))
    return {"checked": int(len(rows)), "mismatches": len(bad),
            "examples": bad[:5], "ok": not bad}


def load() -> pd.DataFrame:
    if not BEHAVIOUR_PATH.exists():
        raise RuntimeError("opening_behaviour.parquet missing. "
                           "Run: python -m src.cli behaviour")
    return repository.behaviour_panel()
