"""Phase 2.4: forward returns for every candidate morning.

WHY THIS EXISTS
Everything before this point describes. This is the first module that lets a
statement be *wrong*: once each candidate morning carries what happened next,
a cut-point can be judged instead of argued about. It is still not a backtest —
there is no position sizing, no stop, no sequencing and no capital constraint.
It answers one question only: conditional on what the morning looked like, what
did the following sessions do?

FOUR THINGS THAT SILENTLY CORRUPT A LABEL, AND WHAT IS DONE ABOUT EACH

1. The entry price is raw, the forward prices are adjusted. Tick prices come
   off Breeze unadjusted, while `daily_bars_adj` carries a per-symbol adjusted
   series. Dividing an adjusted close by a raw entry is correct only while
   `adj_factor` holds still, and it does not: 5.67% of 10-session windows in
   this panel cross a factor change. On a 1:10 split that is a -90% label on a
   day nothing happened. The entry is therefore multiplied onto the adjusted
   basis (`entry_px_adj = close_5m * adj_factor`) before any division.

2. Forward sessions must be counted on the full daily panel, never on the
   candidate panel. A symbol is a candidate on scattered days, so a `shift(-1)`
   over candidate rows can reach across months and label it "+1d". Every
   forward array here is built on `daily_bars_adj` and only then joined back.

3. The entry-day high is not reachable from the entry. Entry is at the end of
   the opening window; bhavcopy's daily high may have printed inside it. On
   13.7% of these mornings the day's high was already set by 09:20 (and the
   low on 11.0%), so an excursion measured from the entry day overstates what
   was catchable. Both are produced: `mfe_*` / `mae_*` start the session
   *after* entry and are clean; the `*_incl_d0` twins include the entry day and
   carry that 13.7% contamination. Neither is deleted, because the entry-day
   afternoon is real and discarding it is its own distortion.

4. A positive mean forward return proves nothing on its own. These are 2023-26
   sessions in a rising market; a rule that picks stocks at random would also
   look profitable. Every horizon therefore carries `bench_fwd_ret_*`, the
   equal-weighted forward return of every symbol trading that same session, and
   the `excess_*` difference. The benchmark is equal-weighted across the whole
   listed panel, not an index — it tilts small, which is the right comparison
   for a pool that is itself mostly small names.

THE STOP IS A FUNCTION OF THE ENTRY TIME
"Slightly below the opening-candle low" only means something once the entry time
is fixed, because the running low must be read at that same moment. This module
labels one specific hypothesis — enter at 09:20, at the close of the window (see
H001 in `HYPOTHESES.md`) — so the running low here is the low *through* 09:20,
and `stop < running_low <= entry` is asserted, not assumed. An earlier version
paired the first-minute low with a 09:20 entry and produced stops above the
entry on 32% of mornings; that was a pairing bug, not a market condition. The
general case, where `t` is a free variable, lives in `entry_window.py`.

WHAT DAILY BARS CANNOT TELL YOU
Whether the high or the low came first. A day whose MFE is +6% and MAE is -3%
is a winner if the target filled before the stop and a loser if it did not, and
nothing in a daily bar resolves it. That ordering is exactly what a stop-and-
target rule turns on, so MFE/MAE here bound the outcome, they do not simulate
it. Honest simulation needs the full-session intraday pull, which is Phase 2.5.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ...core import config
from ...research_data import repository

LABELS_PATH = config.NORMALIZED_DIR / "candidate_labels.parquet"
REPORT_PATH = config.METADATA_DIR / "labelling.json"


@dataclass(frozen=True)
class LabelConfig:
    """No number in here is a strategy choice; they are measurement choices.

    `entry_col` is the one with teeth. `close_5m` is the last tick of the
    opening window — the first price at which a rule reading five-minute
    features could actually have acted. `open_px` (first tick) and `open_raw`
    (the auction print) are available for the counterfactual, and `open_raw` is
    not tradeable by anyone reacting to the opening window.
    """
    horizons: tuple[int, ...] = (1, 3, 5, 10)
    entry_col: str = "close_5m"
    benchmark: bool = True
    # h sessions normally span about 1.4h calendar days. A window that stretches
    # far past that has a suspension or a halt in it: still h sessions, no longer
    # the same kind of measurement. Flagged, not dropped.
    stale_span_multiple: float = 4.0
    bench_min_symbols: int = 50
    bench_series: tuple[str, ...] = ("EQ",)
    # Not a strategy parameter: the target the rules are stated in, carried here
    # only so `mfe_*` can be read against something. Nothing is simulated.
    target_pct: float = 15.0
    # The running low must be read at the SAME time as the entry. `close_5m` is
    # the price at t=09:20, so the low through 09:20 is `low_5m`. Pairing it with
    # a low from any other time breaks `running_low <= entry`. See H004.
    running_low_col: str = "low_5m"
    stop_buffer_pct: float = 0.10


def _forward_arrays(bars: pd.DataFrame, horizons: tuple[int, ...]) -> pd.DataFrame:
    """Per (symbol, date): the close at +h, and the extremes over 1..h.

    Built on the full daily panel so that "+h sessions" means the symbol's next
    h sessions, whether or not it was a candidate on any of them. Walks the lags
    once, folding each into a running max/min, so the peak cost is a handful of
    columns rather than one per lag.
    """
    b = bars.sort_values(["symbol", "date"]).reset_index(drop=True)
    g = b.groupby("symbol", sort=False)
    out = {
        "symbol": b["symbol"].to_numpy(),
        "date": b["date"].to_numpy(),
        # How many sessions actually follow this one. The trailing edge of the
        # panel has no +10d and must not be labelled as though it did.
        "n_fwd_sessions": g.cumcount(ascending=False).to_numpy(),
    }

    hi = np.full(len(b), -np.inf)
    lo = np.full(len(b), np.inf)
    hmax = max(horizons)
    for lag in range(1, hmax + 1):
        fh = g["high"].shift(-lag).to_numpy()
        fl = g["low"].shift(-lag).to_numpy()
        # NaN past the end of a symbol; np.fmax/fmin keep the running value.
        hi = np.fmax(hi, fh)
        lo = np.fmin(lo, fl)
        if lag in horizons:
            out[f"fwd_close_{lag}"] = g["close"].shift(-lag).to_numpy()
            out[f"fwd_high_{lag}"] = hi.copy()
            out[f"fwd_low_{lag}"] = lo.copy()
            out[f"fwd_date_{lag}"] = g["date"].shift(-lag).to_numpy()

    # Entry-day extremes, kept separate so the contaminated variant is opt-in.
    out["d0_high"] = b["high"].to_numpy()
    out["d0_low"] = b["low"].to_numpy()
    return pd.DataFrame(out)


def _benchmark(bars: pd.DataFrame, fwd: pd.DataFrame,
               cfg: LabelConfig) -> pd.DataFrame:
    """Equal-weighted forward return of everything trading that session.

    The comparison that stops a bull market from being read as an edge. Sessions
    with fewer than `bench_min_symbols` priced names are left NaN rather than
    quoted off a handful of stocks.
    """
    base = bars[["symbol", "date", "series", "close"]].merge(
        fwd, on=["symbol", "date"], how="left")
    if cfg.bench_series:
        base = base[base["series"].isin(cfg.bench_series)]

    for h in cfg.horizons:
        base[f"_r{h}"] = (base[f"fwd_close_{h}"] / base["close"] - 1) * 100
    agg = base.groupby("date").agg(
        **{f"bench_fwd_ret_{h}d_pct": (f"_r{h}", "mean") for h in cfg.horizons},
        **{f"_n{h}": (f"_r{h}", "count") for h in cfg.horizons},
    ).reset_index()
    for h in cfg.horizons:
        agg.loc[agg[f"_n{h}"] < cfg.bench_min_symbols,
                f"bench_fwd_ret_{h}d_pct"] = np.nan
    return agg[["date"] + [f"bench_fwd_ret_{h}d_pct" for h in cfg.horizons]]


def attach_labels(panel: pd.DataFrame, bars: pd.DataFrame,
                  cfg: LabelConfig | None = None) -> pd.DataFrame:
    """One row per candidate morning, with what happened next attached."""
    cfg = cfg or LabelConfig()
    if cfg.entry_col not in panel.columns:
        raise KeyError(f"entry column {cfg.entry_col!r} not in the panel")

    fwd = _forward_arrays(bars, cfg.horizons)
    d = panel.merge(fwd, on=["symbol", "date"], how="left")

    # (1) Put the raw tick entry onto the adjusted basis before dividing.
    d["entry_px_raw"] = d[cfg.entry_col]
    d["entry_px_adj"] = d["entry_px_raw"] * d["adj_factor"]
    d["entry_basis"] = cfg.entry_col
    # What waiting for the opening window to finish cost against the print.
    if "open_raw" in d.columns:
        d["entry_slippage_pct"] = (d["entry_px_raw"] / d["open_raw"] - 1) * 100

    e = d["entry_px_adj"].where(d["entry_px_adj"] > 0)
    for h in cfg.horizons:
        complete = d["n_fwd_sessions"] >= h
        d[f"horizon_complete_{h}d"] = complete

        # (2) Truncated windows are NaN, never a short-window number.
        d[f"fwd_ret_{h}d_pct"] = ((d[f"fwd_close_{h}"] / e - 1) * 100).where(complete)
        # (3) Clean excursions: the session after entry onward.
        d[f"mfe_{h}d_pct"] = ((d[f"fwd_high_{h}"] / e - 1) * 100).where(complete)
        d[f"mae_{h}d_pct"] = ((d[f"fwd_low_{h}"] / e - 1) * 100).where(complete)
        # ...and the twins that include the entry day's own extremes.
        d[f"mfe_{h}d_incl_d0_pct"] = (
            (np.fmax(d[f"fwd_high_{h}"], d["d0_high"]) / e - 1) * 100).where(complete)
        d[f"mae_{h}d_incl_d0_pct"] = (
            (np.fmin(d[f"fwd_low_{h}"], d["d0_low"]) / e - 1) * 100).where(complete)

        span = (d[f"fwd_date_{h}"] - d["date"]).dt.days
        d[f"fwd_span_days_{h}d"] = span.where(complete)
        d[f"stale_window_{h}d"] = (
            span > h * cfg.stale_span_multiple).fillna(False) & complete

    # The stop implied by the entry: just below the lowest price seen from the
    # open through the entry time. Read at the same `t` as the entry, so
    # `stop < running_low <= entry` holds by construction and is asserted rather
    # than hoped for. A measurement, not an exit: whether it would have been hit
    # *before* the target is exactly the ordering daily bars cannot say.
    if cfg.running_low_col in d.columns:
        rl = d[cfg.running_low_col] * d["adj_factor"]
        if (rl > e + 1e-9).any():
            raise AssertionError(
                f"running low ({cfg.running_low_col}) sits above the entry "
                f"({cfg.entry_col}) on {int((rl > e + 1e-9).sum())} rows. These "
                f"must be read at the same time within the window; see H004.")
        d["running_low_adj"] = rl
        d["stop_px_adj"] = rl * (1 - cfg.stop_buffer_pct / 100)
        d["stop_dist_pct"] = (d["stop_px_adj"] / e - 1) * 100
        d["low_to_entry_pct"] = (rl / e - 1) * 100
        for h in cfg.horizons:
            # NaN, not False, where the horizon is truncated: a window that has
            # not finished has not "failed to touch" anything, and counting it
            # as False silently deflates every touch rate.
            ok = d[f"horizon_complete_{h}d"]
            d[f"stop_touched_{h}d"] = (
                (d[f"mae_{h}d_pct"] <= d["stop_dist_pct"]).where(ok).astype("boolean"))
            d[f"target_touched_{h}d"] = (
                (d[f"mfe_{h}d_pct"] >= cfg.target_pct).where(ok).astype("boolean"))

    if cfg.benchmark:
        bench = _benchmark(bars, fwd, cfg)
        d = d.merge(bench, on="date", how="left")
        for h in cfg.horizons:
            # (4) The only number that survives a rising market.
            d[f"excess_ret_{h}d_pct"] = (d[f"fwd_ret_{h}d_pct"]
                                         - d[f"bench_fwd_ret_{h}d_pct"])

    drop = [c for c in d.columns
            if c.startswith(("fwd_close_", "fwd_high_", "fwd_low_", "fwd_date_"))
            or c in ("d0_high", "d0_low")]
    return d.drop(columns=drop)


def horizon_summary(labels: pd.DataFrame, cfg: LabelConfig | None = None) -> list[dict]:
    """Per horizon: the outcome, and the outcome net of the market."""
    cfg = cfg or LabelConfig()
    rows = []
    for h in cfg.horizons:
        r = labels[f"fwd_ret_{h}d_pct"].dropna()
        if r.empty:
            continue
        x = labels[f"excess_ret_{h}d_pct"].dropna() if f"excess_ret_{h}d_pct" in labels else pd.Series(dtype=float)
        row = {
            "horizon_d": h,
            "n": int(len(r)),
            "n_incomplete": int((~labels[f"horizon_complete_{h}d"]).sum()),
            "mean_pct": round(float(r.mean()), 4),
            "median_pct": round(float(r.median()), 4),
            "sd_pct": round(float(r.std()), 4),
            "hit_rate_pct": round(float((r > 0).mean() * 100), 2),
            "p10": round(float(r.quantile(0.10)), 3),
            "p90": round(float(r.quantile(0.90)), 3),
            "mean_mfe_pct": round(float(labels[f"mfe_{h}d_pct"].mean()), 4),
            "mean_mae_pct": round(float(labels[f"mae_{h}d_pct"].mean()), 4),
        }
        if not x.empty:
            row |= {
                "mean_excess_pct": round(float(x.mean()), 4),
                "median_excess_pct": round(float(x.median()), 4),
                "excess_hit_rate_pct": round(float((x > 0).mean() * 100), 2),
                # Crude but the right order of magnitude: is the mean excess
                # distinguishable from zero at all?
                "excess_t_stat": round(float(x.mean() / (x.std() / np.sqrt(len(x)))), 2),
            }
        rows.append(row)
    return rows


def by_bucket(labels: pd.DataFrame, col: str, edges: list[float],
              cfg: LabelConfig | None = None) -> list[dict]:
    """Forward outcomes sliced by a morning measure, in that measure's units.

    This is what the cut-point question actually needs answered: not "how many
    days survive this threshold" (that was Phase 2.3) but "did the days above it
    behave differently from the days below".
    """
    cfg = cfg or LabelConfig()
    if col not in labels.columns:
        return []
    b = pd.cut(labels[col], edges)
    rows = []
    for name, sub in labels.groupby(b, observed=True):
        row = {"bucket": str(name), "n": int(len(sub))}
        for h in cfg.horizons:
            r = sub[f"fwd_ret_{h}d_pct"].dropna()
            if r.empty:
                continue
            row[f"mean_{h}d"] = round(float(r.mean()), 3)
            row[f"median_{h}d"] = round(float(r.median()), 3)
            row[f"hit_{h}d"] = round(float((r > 0).mean() * 100), 1)
            if f"excess_ret_{h}d_pct" in sub:
                row[f"excess_{h}d"] = round(float(sub[f"excess_ret_{h}d_pct"].mean()), 3)
        rows.append(row)
    return rows


def slippage_profile(labels: pd.DataFrame, col: str, edges: list[float]) -> list[dict]:
    """What the first five minutes did, sliced by a morning measure.

    This is the mechanism behind the headline result rather than a side note.
    The opening window does not stand still while it is being measured: it
    reverses the gap (mornings gapping below -2% recover a mean +1.16% by 09:20,
    mornings gapping above +5% give back -1.13%) and it runs *with* opening
    volume (+0.73% mean in the heaviest bucket against -0.06% in the lightest).
    Both push the same way — on exactly the mornings the stated entry rules
    select, the price you can actually get is worse than the print that
    selected it, by more than the forward edge is worth.
    """
    if col not in labels.columns or "entry_slippage_pct" not in labels.columns:
        return []
    b = pd.cut(labels[col], edges)
    rows = []
    for name, sub in labels.groupby(b, observed=True):
        s = sub["entry_slippage_pct"].dropna()
        if s.empty:
            continue
        rows.append({
            "bucket": str(name), "n": int(len(s)),
            "mean_pct": round(float(s.mean()), 4),
            "median_pct": round(float(s.median()), 4),
            "pct_up": round(float((s > 0).mean() * 100), 2),
        })
    return rows


def report(labels: pd.DataFrame, cfg: LabelConfig | None = None,
           save: bool = True) -> dict:
    cfg = cfg or LabelConfig()
    from .characterize import GAP_BUCKETS, VOL_BUCKETS
    out = {
        "rows": int(len(labels)),
        "symbols": int(labels["symbol"].nunique()),
        "sessions": int(labels["date"].nunique()),
        "window": [str(labels["date"].min().date()), str(labels["date"].max().date())],
        "entry_basis": cfg.entry_col,
        "horizons": horizon_summary(labels, cfg),
        "by_gap": by_bucket(labels, "gap_pct", list(GAP_BUCKETS), cfg),
        "by_open_volume": by_bucket(labels, "vol_5m_pct_of_median_daily",
                                    list(VOL_BUCKETS), cfg),
        "slippage_by_gap": slippage_profile(labels, "gap_pct", list(GAP_BUCKETS)),
        "slippage_by_open_volume": slippage_profile(
            labels, "vol_5m_pct_of_median_daily", list(VOL_BUCKETS)),
    }
    if "stop_dist_pct" in labels:
        sd = labels["stop_dist_pct"].dropna()
        out["stated_stop"] = {
            "entry_time": "t=09:20 (end of window); see H001",
            "running_low_col": cfg.running_low_col,
            "target_pct": cfg.target_pct,
            "distance_quantiles": {f"p{int(q*100)}": round(float(sd.quantile(q)), 3)
                                   for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
            # Zero by construction. Kept as a live check, not a finding: the
            # Phase 2.4 claim that the stop sat above the entry came from
            # reading the low and the price at different times (H004).
            "pct_above_entry": round(float((sd >= 0).mean() * 100), 2),
            "buffer_pct": cfg.stop_buffer_pct,
            "touched_by_horizon": {
                f"{h}d": round(float(labels[f"stop_touched_{h}d"].mean() * 100), 2)
                for h in cfg.horizons},
            "target_touched_by_horizon": {
                f"{h}d": round(float(labels[f"target_touched_{h}d"].mean() * 100), 2)
                for h in cfg.horizons},
            # The cell H006 turns on: both levels reached, order unknowable.
            "both_touched_by_horizon": {
                f"{h}d": round(float((labels[f"stop_touched_{h}d"]
                                      & labels[f"target_touched_{h}d"]).mean() * 100), 2)
                for h in cfg.horizons},
        }
    if "entry_slippage_pct" in labels:
        s = labels["entry_slippage_pct"].dropna()
        out["entry_slippage_pct"] = {
            "median": round(float(s.median()), 4),
            "mean": round(float(s.mean()), 4),
            "p10": round(float(s.quantile(0.1)), 3),
            "p90": round(float(s.quantile(0.9)), 3),
        }
    if save:
        import json
        config.METADATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(out, indent=2, default=str))
    return out


def build(cfg: LabelConfig | None = None, save: bool = True,
          verbose: bool = True) -> tuple[pd.DataFrame, dict]:
    from . import join as opening_join
    cfg = cfg or LabelConfig()
    panel = opening_join.load_panel()
    bars = repository.daily_bars(
        columns=["symbol", "series", "date", "high", "low", "close"])
    labels = attach_labels(panel, bars, cfg)
    rep = report(labels, cfg, save=save)
    if save:
        config.NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
        labels.to_parquet(LABELS_PATH, index=False)
    if verbose:
        print(f"  labelled {len(labels):,} candidate mornings, "
              f"entry = {cfg.entry_col}")
    return labels, rep


def load_labels() -> pd.DataFrame:
    if not LABELS_PATH.exists():
        raise RuntimeError("candidate_labels.parquet missing. "
                           "Run: python -m src.cli label")
    return repository.candidate_labels()
