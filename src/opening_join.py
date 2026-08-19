"""Join opening-window features to daily screener candidates.

WHY THIS EXISTS
The screener says which names were interesting the night before; the 1-second
opening data says what they did in the first five minutes. Neither is a signal
on its own. This module puts them on one row per candidate symbol-day so the
distributions in the next phase can be looked at, and it deliberately stops
there — nothing here filters, scores or decides.

THE GAP IS NOT THE TICK OPEN, AND THIS COST A MEASUREMENT TO ESTABLISH
The obvious way to compute the morning gap is `first_tick_price / prev_close`.
It is wrong. Bhavcopy's OPEN and the first price in Breeze's 1-second series
are two different prices, and they disagree on 64% of symbol-days:

  * the tick open sits inside bhavcopy's daily [low, high] on 99.98% of days,
    so the ticks are real trades — just not the opening one;
  * bhavcopy's OPEN sits outside the first five minutes' tick range on 26% of
    days, split almost evenly below (14.0%) and above (11.9%);
  * agreement decays monotonically with how late Breeze's first bar is —
    45.8% exact when the first bar is at 09:15:00, 30.7% at 09:15:05 — and
    the median deviation grows 0.008% -> 0.091% across the same span;
  * agreement is *best* on the thinnest names (59% exact in the bottom
    turnover quintile, 17% in the top), because a stock that does not trade in
    the first seconds has nothing to drift.

That is the signature of a missing first print rather than bad data. NSE opens
with a call auction: orders collected from 09:00 are matched and the
equilibrium price is disseminated as the opening price at 09:15:00. Breeze's
1-second series begins at the first *continuous-session* trade it captured,
which is frequently a few seconds later and a few ticks away.

MINDACORP on 2024-05-21 shows what the difference is worth. Bhavcopy opened it
at 405.05 against a 430.75 previous close — a -6.0% gap down. Breeze's first
bar is 09:15:03 at 434.00, which reads as a +0.8% gap *up*. Same morning,
opposite sign. A gap computed off the tick open would have mislabelled it.

So `gap_pct` comes from the daily panel, computed on adjusted prices so a split
is not read as a gap. `gap_pct_tick` is carried alongside for diagnosis only,
and `open_drift_pct` — the move from the opening print to the first tradeable
tick — is kept as a feature in its own right, since it is exactly the slippage
between the price that defines the gap and the price you could actually get.

OPENING VOLUME NEEDS A DENOMINATOR THAT EXISTS EVERY DAY
"Strong opening volume" wants opening volume against its own recent average,
but opening ticks were only ever fetched for days a symbol was already a
candidate, so a per-symbol rolling average of `vol_5m` is an average over an
irregular, selection-biased subset. `vol_5m_pct_of_median_daily` — the first
five minutes as a percentage of the symbol's median 20-day full-day volume —
uses a denominator defined on every session and is the primary measure here.
The self-referential version is still computed as `vol_5m_rel_own`, with
`n_prior_open_obs` beside it so its shakiness is visible rather than implied.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import config, renames

FEATURES_PATH = config.NORMALIZED_DIR / "opening_features.parquet"
PANEL_PATH = config.NORMALIZED_DIR / "candidate_panel.parquet"

# Daily columns carried onto each candidate row. Deliberately small: this is a
# join, not a second metrics panel.
DAILY_CONTEXT = [
    "symbol", "date", "open_raw", "high_raw", "low_raw", "close_raw",
    "prev_close_raw", "volume", "turnover", "adj_factor",
]


def load_features(path: Path = FEATURES_PATH,
                  rmap: pd.DataFrame | None = None) -> pd.DataFrame:
    """Load opening features with symbols folded to canonical tickers.

    The daily panel is keyed on post-rename tickers but the opening pull ran
    against whatever ticker was current when each day was fetched, so without
    this the renamed symbols drop out of the join without a word.
    """
    df = pd.read_parquet(path)
    if df.empty:
        return df
    df = df.rename(columns={"day": "date"})
    df["date"] = pd.to_datetime(df["date"])

    rmap = renames.load_map() if rmap is None else rmap
    cmap = renames.canonical_map(rmap)
    if cmap:
        df["symbol_as_fetched"] = df["symbol"]
        df["symbol"] = df["symbol"].map(lambda s: cmap.get(s, s))
    return df


def add_gap_fields(features: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Attach the daily open/prev-close context and the three gap measures.

    `gap_pct` is recomputed here on raw prices rather than taken from the
    metrics panel so that this function is honest on its own inputs; it agrees
    with the panel's adjusted `gap_pct` everywhere except a corporate-action
    ex-date, where the panel's is the correct one and this one is left to be
    caught by `adj_factor != 1`.
    """
    cols = [c for c in DAILY_CONTEXT if c in bars.columns]
    d = features.merge(bars[cols], on=["symbol", "date"], how="left")

    # The gap a trader sees: the opening print against the previous close.
    d["gap_pct"] = (d["open_raw"] / d["prev_close_raw"] - 1) * 100
    # The same arithmetic on the first captured tick. Kept only to measure the
    # disagreement, never as the gap. See the module docstring.
    d["gap_pct_tick"] = (d["open_px"] / d["prev_close_raw"] - 1) * 100
    # What the opening print cost you by the time you could trade it.
    d["open_drift_pct"] = (d["open_px"] / d["open_raw"] - 1) * 100
    return d


def add_volume_context(features: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    """Opening volume against a denominator that exists on every session."""
    cols = ["symbol", "date", "median_vol_20", "median_tv_20_cr"]
    have = [c for c in cols if c in metrics.columns]
    d = features.merge(metrics[have], on=["symbol", "date"], how="left")

    if "median_vol_20" in d.columns:
        d["vol_5m_pct_of_median_daily"] = (
            d["vol_5m"] / d["median_vol_20"].replace(0, pd.NA) * 100)

    # Self-referential fallback. Only ever computed over days this symbol was
    # already a candidate, so `n_prior_open_obs` is carried with it.
    d = d.sort_values(["symbol", "date"])
    g = d.groupby("symbol")["vol_5m"]
    prior_mean = g.transform(lambda s: s.shift(1).rolling(20, min_periods=5).mean())
    d["n_prior_open_obs"] = g.transform(lambda s: s.shift(1).expanding().count())
    d["vol_5m_rel_own"] = d["vol_5m"] / prior_mean.replace(0, pd.NA)
    return d


def build_panel(candidates: pd.DataFrame, features: pd.DataFrame,
                bars: pd.DataFrame, metrics: pd.DataFrame,
                how: str = "inner") -> pd.DataFrame:
    """One row per candidate symbol-day that has opening data.

    Defaults to an inner join: a candidate with no ticks is not a candidate
    with zero opening volume, and letting those rows through as NaN invites
    exactly that misreading downstream. `how="left"` is available for coverage
    accounting, which is what `coverage()` uses it for.
    """
    feat = add_gap_fields(features, bars)
    feat = add_volume_context(feat, metrics)
    drop = [c for c in feat.columns
            if c in candidates.columns and c not in ("symbol", "date")]
    panel = candidates.merge(feat.drop(columns=drop), on=["symbol", "date"], how=how)
    return panel.sort_values(["date", "symbol"]).reset_index(drop=True)


def coverage(candidates: pd.DataFrame, features: pd.DataFrame,
             manifest: pd.DataFrame | None = None,
             rmap: pd.DataFrame | None = None) -> dict:
    """Account for every candidate symbol-day in the tick window.

    Coverage is reported only inside the window the tick data actually spans.
    Quoting a percentage against candidates from years with no pull at all
    would describe the pull's date range, not the join.
    """
    if features.empty or candidates.empty:
        return {}
    lo, hi = features["date"].min(), features["date"].max()
    inside = candidates[candidates["date"].between(lo, hi)]

    j = inside.merge(features[["symbol", "date"]].assign(_hit=1),
                     on=["symbol", "date"], how="left")
    matched = int(j["_hit"].notna().sum())

    out = {
        "tick_window": [str(lo.date()), str(hi.date())],
        "candidates_total": int(len(candidates)),
        "candidates_in_window": int(len(inside)),
        "matched": matched,
        "matched_pct": round(matched / len(inside) * 100, 2) if len(inside) else 0.0,
        "unmatched": int(len(inside)) - matched,
    }

    if manifest is not None and not manifest.empty:
        man = manifest.copy()
        man["date"] = pd.to_datetime(man["date"])
        cmap = renames.canonical_map(renames.load_map() if rmap is None else rmap)
        man["symbol"] = man["symbol"].map(lambda s: cmap.get(s, s))
        miss = j[j["_hit"].isna()][["symbol", "date"]]
        why = miss.merge(man[["symbol", "date", "status"]], on=["symbol", "date"],
                         how="left")["status"].fillna("never_requested")
        out["unmatched_reasons"] = {k: int(v) for k, v in why.value_counts().items()}
    return out


def build(cfg=None, save: bool = True, verbose: bool = True) -> tuple[pd.DataFrame, dict]:
    """Screen, join, report. Returns (panel, coverage)."""
    from . import build_screen
    from .screener import ScreenConfig, run_screen

    # Screen on the as-of-open panel: the selection for date D must not read
    # date D's close (H015). The unlagged panel is still loaded below, because
    # the candidate row should record what the day actually looked like — it
    # just must not have been *chosen* on it.
    metrics = build_screen.load(asof_open=True)
    cands, _ = run_screen(metrics, cfg or ScreenConfig())
    feats = load_features()
    bars = pd.read_parquet(config.NORMALIZED_DIR / "daily_bars_adj.parquet",
                           columns=DAILY_CONTEXT)

    man_path = config.METADATA_DIR / "opening_manifest.parquet"
    man = pd.read_parquet(man_path) if man_path.exists() else None
    cov = coverage(cands, feats, man)
    panel = build_panel(cands, feats, bars, metrics)

    if save:
        config.NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(PANEL_PATH, index=False)
    if verbose:
        print(f"  candidates {cov.get('candidates_total', 0):,} "
              f"({cov.get('candidates_in_window', 0):,} in the tick window), "
              f"panel {len(panel):,} rows, {panel['symbol'].nunique():,} symbols")
    return panel, cov


def load_panel() -> pd.DataFrame:
    if not PANEL_PATH.exists():
        raise RuntimeError("candidate_panel.parquet missing. "
                           "Run: python -m src.cli candidate-panel")
    return pd.read_parquet(PANEL_PATH)
