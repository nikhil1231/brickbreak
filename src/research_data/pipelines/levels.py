"""Causal support/resistance level books, four detectors, one schema.

WHY THIS REPLACES THE ZONE STATE MACHINE'S SEEDER
`causal_zones.build_zone_state_machine` seeds levels from 2-left/2-right
fractals on five-minute bars. On NSE intraday bars that fires every few bars, so
the "nearest support" is typically a swing low from earlier the same morning.
Two measured consequences followed:

  * H055's PA7 annotation study failed at composite kappa 0.087 with 1.52 ATR
    of centre disagreement. The owner drew *distant, older* levels; the detector
    drew micro-pivots. That is two different objects, not one shared concept
    that a human and a model happened to disagree about.
  * H056's structural preflight rejected 91% of role-reversal retests, dominated
    by `target_room` (2,943) and `reward_risk` (2,890). With a level every few
    bars the nearest opposing level is a fraction of an ATR away, so a
    structural target can essentially never clear 80 bps. The funnel was
    measuring level *density*, not the market.

A LEVEL BOOK, NOT A PER-BAR STATE MACHINE
Each detector emits rows of `LEVEL_COLUMNS`: an explicit `known_at`, price
bounds, and a `significance`. Nothing is recomputed per bar and nothing is
rewritten when later bars arrive. Two things follow that the state machine could
not give:

  * detectors are directly comparable, because they differ only in how a row
    gets into the book; and
  * an *arbitrary* set of price lines can be substituted for a real book, which
    is what the pseudo-level control in `research.families.level_reaction`
    needs. A control that had to be threaded through a stateful loop would not
    be the same code path as the thing it controls.

TIMEFRAME PORTABILITY IS A PROPERTY OF THE DETECTOR
`fractal` is defined by a bar pattern, so its output changes when the bar size
changes: run it on five-minute and on hourly bars over identical history and it
finds different levels. `anchor`, `volume_profile` and `multi_touch` are defined
by *where trading happened*, so they return the same prices at any bar size.
This matters because decisions here are taken on completed hourly bars while the
five-minute series supplies the intra-hour path — a detector that changes
identity between the two timeframes cannot be learned on one and traded on the
other.

CAUSALITY
Three of the four detectors are session-granular: they consume only completed
sessions and their rows become knowable at the next session's first bar. That
makes the point-in-time claim auditable by inspection rather than by trusting a
loop. `fractal` is intraday and becomes knowable at the close of its right-hand
confirmation bar. No detector may consult the session it is knowable in.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Callable

import numpy as np
import pandas as pd

LEVEL_COLUMNS = (
    "level_id", "symbol", "detector", "kind", "origin_at", "known_at",
    "valid_until", "center", "lower", "upper", "significance",
    "source_sessions",
)

# WHY LEVELS EXPIRE, AND WHY IT IS NOT A BAR COUNT
# The incumbent state machine deactivated a zone after `max_age_bars = 240`
# five-minute bars — about 3.2 sessions. Every level a discretionary trader
# actually watches is older than that, which is a large part of why the H055
# annotation study found the machine and the human looking at different
# objects. Validity here is instead a property of how the level was made: the
# session-granular detectors re-emit their book every session, so each row is
# valid for the session it is knowable in and is replaced (not aged out) the
# next morning, while an intraday fractal persists for a declared number of
# sessions. Expiry is also what keeps the approach scan linear: a level is only
# ever compared against bars inside its own validity window.

# Two roles a level can play. `both` is the honest default for a level that has
# not yet been approached from a side: whether it is support or resistance is a
# function of where price is now, which the book does not know when it is built.
KINDS = ("support", "resistance", "both")


class LevelError(RuntimeError):
    pass


@dataclass(frozen=True)
class LevelConfig:
    """Frozen detector priors. Every constant a detector needs lives here."""

    # shared
    atr_window: int = 20
    width_atr: float = 0.25
    minimum_width_bps: float = 8.0
    merge_atr: float = 0.50
    max_age_sessions: int = 60

    # fractal (baseline)
    pivot_left: int = 2
    pivot_right: int = 2

    # anchor
    opening_range_minutes: int = 60
    round_number_steps: tuple[float, ...] = (50.0, 100.0, 500.0, 1000.0)
    round_number_max_distance_atr: float = 6.0

    # volume profile. The grid resolves price finer than a level is wide:
    # a node the size of the level it produces carries no information about
    # where inside that level the volume actually sat.
    profile_lookback_sessions: int = 15
    profile_bin_bps: float = 10.0
    profile_min_bins: int = 20
    profile_min_peak_share: float = 0.60

    # multi touch
    touch_lookback_sessions: int = 30
    touch_cluster_atr: float = 0.40
    touch_min_sessions: int = 2

    def __post_init__(self) -> None:
        if self.atr_window < 2:
            raise ValueError("ATR window must exceed one bar")
        if min(self.width_atr, self.minimum_width_bps, self.merge_atr) <= 0:
            raise ValueError("widths and merge distance must be positive")
        if self.max_age_sessions < 1:
            raise ValueError("levels must survive at least one session")
        if self.pivot_left < 1 or self.pivot_right < 1:
            raise ValueError("pivot confirmation needs a bar on each side")
        if self.opening_range_minutes < 5:
            raise ValueError("opening range must span at least one bar")
        if self.profile_min_bins < 5 or self.profile_lookback_sessions < 1:
            raise ValueError("invalid volume-profile configuration")
        if self.profile_bin_bps <= 0:
            raise ValueError("profile bin width must be positive")
        if not 0 < self.profile_min_peak_share <= 1:
            raise ValueError("peak share is a fraction of the modal bin")
        if self.touch_lookback_sessions < 1 or self.touch_min_sessions < 1:
            raise ValueError("invalid multi-touch configuration")
        if self.touch_cluster_atr <= 0:
            raise ValueError("cluster tolerance must be positive")


SESSION_OPEN = pd.Timedelta(hours=9, minutes=15)
SESSION_CLOSE = pd.Timedelta(hours=15, minutes=30)


def _session_end(known_at: Any) -> pd.Timestamp:
    """End of the session a timestamp falls in."""
    stamp = pd.Timestamp(known_at)
    return stamp.normalize() + SESSION_CLOSE


def _level_id(detector: str, symbol: str, origin_at: pd.Timestamp,
              center: float) -> str:
    payload = f"{detector}|{symbol}|{pd.Timestamp(origin_at).isoformat()}|{center:.6f}"
    return detector[:3].upper() + "_" + hashlib.sha256(
        payload.encode()).hexdigest()[:14].upper()


def _empty_book() -> pd.DataFrame:
    return pd.DataFrame({name: pd.Series(dtype="object")
                         for name in LEVEL_COLUMNS})


def _normalise_bars(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "bar_end", "open", "high", "low", "close", "volume"}
    aliases = {
        "symbol": ("symbol", "symbol_asof"), "bar_end": ("bar_end", "timestamp"),
        "open": ("open", "open_raw"), "high": ("high", "high_raw"),
        "low": ("low", "low_raw"), "close": ("close", "close_raw"),
        "volume": ("volume", "volume_raw"),
    }
    out = pd.DataFrame(index=bars.index)
    for role, choices in aliases.items():
        found = next((name for name in choices if name in bars.columns), None)
        if found is None:
            raise LevelError(f"bars need one of {choices} for {role}")
        out[role] = bars[found]
    out["bar_end"] = pd.to_datetime(out["bar_end"], errors="raise")
    out["session"] = (
        pd.to_datetime(bars["session"], errors="raise").dt.normalize()
        if "session" in bars.columns else out["bar_end"].dt.normalize())
    for column in ("open", "high", "low", "close", "volume"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out["symbol"] = out["symbol"].astype(str)
    missing = required - set(out.columns)
    if missing:
        raise LevelError(f"normalised bars missing {sorted(missing)}")
    return out.sort_values(["symbol", "bar_end"], kind="stable").reset_index(drop=True)


def session_atr(bars: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Lagged session-level ATR: the volatility unit every detector scales by.

    Uses completed sessions only and shifts by one, so the value attached to a
    session was knowable before that session opened.
    """
    work = _normalise_bars(bars)
    daily = work.groupby(["symbol", "session"], sort=True).agg(
        high=("high", "max"), low=("low", "min"), close=("close", "last"),
    ).reset_index()
    previous_close = daily.groupby("symbol", sort=False)["close"].shift(1)
    true_range = pd.concat([
        (daily["high"] - daily["low"]).abs(),
        (daily["high"] - previous_close).abs(),
        (daily["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    daily["session_atr"] = (
        true_range.groupby(daily["symbol"], sort=False)
        .transform(lambda values: values.rolling(window, min_periods=2).mean())
        .groupby(daily["symbol"], sort=False).shift(1))
    daily["prior_close"] = previous_close
    return daily[["symbol", "session", "session_atr", "prior_close",
                  "high", "low", "close"]]


def _width(center: float, atr: float, cfg: LevelConfig) -> float:
    by_atr = cfg.width_atr * atr if np.isfinite(atr) and atr > 0 else 0.0
    by_bps = abs(center) * cfg.minimum_width_bps / 10_000.0
    return float(max(by_atr, by_bps))


def _merge_book(rows: list[dict[str, Any]], cfg: LevelConfig,
                merge: bool = True) -> pd.DataFrame:
    """Collapse near-duplicate levels knowable at the same moment.

    Merging is by symbol, detector, kind and known_at, so a level is never
    merged with one that was not yet knowable — which would import future
    information into an old row's bounds — and a support cluster is never
    averaged into a resistance one sitting at a similar price.

    `merge=False` is not a convenience. A canonical anchor is a *specific fact*:
    yesterday's high is that price and no other. Averaging it with a round
    number that happens to sit half an ATR away produces a level that is neither
    of them and that no trader is watching, which is the same failure mode that
    made the fractal book unrecognisable to a human annotator. Detectors whose
    rows are individually meaningful therefore keep every row; detectors that
    emit many near-duplicate seeds merge them.
    """
    if isinstance(rows, pd.DataFrame):
        book = rows
        if book.empty:
            return _empty_book()
    elif not rows:
        return _empty_book()
    else:
        book = pd.DataFrame(rows)
    if "valid_until" not in book.columns:
        book["valid_until"] = [_session_end(value) for value in book["known_at"]]
    if not merge:
        book["level_id"] = [
            _level_id(str(detector), str(symbol), origin, float(center))
            for detector, symbol, origin, center in zip(
                book["detector"], book["symbol"], book["origin_at"], book["center"])
        ]
        return book[list(LEVEL_COLUMNS)].drop_duplicates(
            subset=["level_id"]).reset_index(drop=True)
    merged: list[dict[str, Any]] = []
    keys = ["symbol", "detector", "kind", "known_at"]
    for _, group in book.groupby(keys, sort=False):
        group = group.sort_values("center", kind="stable")
        current: dict[str, Any] | None = None
        for row in group.to_dict("records"):
            atr = row.get("_atr", np.nan)
            tolerance = cfg.merge_atr * atr if np.isfinite(atr) and atr > 0 else 0.0
            if current is not None and abs(row["center"] - current["center"]) <= tolerance:
                weight = current["source_sessions"] + row["source_sessions"]
                current["center"] = (
                    current["center"] * current["source_sessions"]
                    + row["center"] * row["source_sessions"]) / max(weight, 1)
                current["lower"] = min(current["lower"], row["lower"])
                current["upper"] = max(current["upper"], row["upper"])
                current["significance"] += row["significance"]
                current["source_sessions"] = weight
                current["origin_at"] = min(current["origin_at"], row["origin_at"])
                current["valid_until"] = max(
                    current["valid_until"], row["valid_until"])
                continue
            if current is not None:
                merged.append(current)
            current = dict(row)
        if current is not None:
            merged.append(current)
    out = pd.DataFrame(merged)
    out["level_id"] = [
        _level_id(str(detector), str(symbol), origin, float(center))
        for detector, symbol, origin, center in zip(
            out["detector"], out["symbol"], out["origin_at"], out["center"])
    ]
    return out[list(LEVEL_COLUMNS)].reset_index(drop=True)


# --------------------------------------------------------------------------
# detector 1 — fractal pivots (the H055/H056 baseline, kept for comparison)
# --------------------------------------------------------------------------

def detect_fractal(bars: pd.DataFrame, config: LevelConfig | None = None) -> pd.DataFrame:
    """Bar-pattern pivots with left/right confirmation.

    This is the incumbent detector, reproduced here so that every comparison
    against it runs through identical downstream code. It is bar-size dependent
    by construction and is expected to lose; it is the control, not a candidate.

    A pivot is a bar whose high (or low) is the strict, unique extreme of the
    window spanning `pivot_left` bars before it and `pivot_right` after, and it
    becomes knowable only when that last confirmation bar closes. The test is a
    rolling-window comparison rather than a loop: on a real panel this detector
    fires on the order of a million times, and the loop version dominated the
    whole study's runtime while producing identical output.

    Merging is off. It groups by `known_at`, and a fractal's `known_at` is the
    single bar that confirmed it, so every group holds one row and merging is
    pure overhead that changes nothing.
    """
    cfg = config or LevelConfig()
    work = _normalise_bars(bars)
    atr = session_atr(bars, cfg.atr_window)
    work = work.merge(atr[["symbol", "session", "session_atr"]],
                      on=["symbol", "session"], how="left")
    span = cfg.pivot_left + cfg.pivot_right + 1
    frames: list[pd.DataFrame] = []

    for symbol, group in work.groupby("symbol", sort=False):
        group = group.reset_index(drop=True)
        if len(group) < span:
            continue
        highs = group["high"].to_numpy(float)
        lows = group["low"].to_numpy(float)
        times = group["bar_end"].to_numpy()
        units = group["session_atr"].to_numpy(float)
        seeds = np.arange(cfg.pivot_left, len(group) - cfg.pivot_right)
        confirms = seeds + cfg.pivot_right

        windows_high = np.lib.stride_tricks.sliding_window_view(highs, span)
        windows_low = np.lib.stride_tricks.sliding_window_view(lows, span)
        for values, windows, kind, sign in (
                (highs, windows_high, "resistance", 1),
                (lows, windows_low, "support", -1)):
            pivots = values[seeds]
            extreme = (windows.max(axis=1) if sign > 0 else windows.min(axis=1))
            unique = (windows == pivots[:, None]).sum(axis=1) == 1
            hit = np.isfinite(pivots) & (pivots == extreme) & unique
            if not hit.any():
                continue
            chosen = seeds[hit]
            confirmed = confirms[hit]
            centre = values[chosen]
            unit = units[confirmed]
            width = np.maximum(
                np.where(np.isfinite(unit) & (unit > 0), cfg.width_atr * unit, 0.0),
                np.abs(centre) * cfg.minimum_width_bps / 10_000.0)
            frames.append(pd.DataFrame({
                "symbol": symbol, "detector": "fractal", "kind": kind,
                "origin_at": times[chosen], "known_at": times[confirmed],
                "valid_until": pd.to_datetime(times[confirmed]).normalize()
                    + SESSION_CLOSE + pd.Timedelta(days=cfg.max_age_sessions),
                "center": centre, "lower": centre - width,
                "upper": centre + width, "significance": 1.0,
                "source_sessions": 1,
            }))
    if not frames:
        return _empty_book()
    return _merge_book(pd.concat(frames, ignore_index=True), cfg, merge=False)


# --------------------------------------------------------------------------
# detector 2 — canonical anchors
# --------------------------------------------------------------------------

def detect_anchor(bars: pd.DataFrame, config: LevelConfig | None = None) -> pd.DataFrame:
    """Prior-session and prior-week extremes, opening range, round numbers.

    These are the levels that are actually on a discretionary trader's chart,
    and they need no threshold search at all: a prior session's high is a fact,
    not a parameter. Every anchor below is knowable at the moment stated and
    consumes only completed data.
    """
    cfg = config or LevelConfig()
    work = _normalise_bars(bars)
    atr = session_atr(bars, cfg.atr_window)
    sessions = atr.sort_values(["symbol", "session"], kind="stable").copy()

    first_bar = work.groupby(["symbol", "session"], sort=True)["bar_end"].min() \
        .rename("session_first_bar").reset_index()
    sessions = sessions.merge(first_bar, on=["symbol", "session"], how="left")

    grouped = sessions.groupby("symbol", sort=False)
    for name in ("high", "low", "close"):
        sessions[f"prior_{name}"] = grouped[name].shift(1)
    sessions["prior_atr"] = sessions["session_atr"]

    # Prior week: the completed ISO week before the one this session sits in.
    sessions["iso_week"] = sessions["session"].dt.strftime("%G-%V")
    weekly = sessions.groupby(["symbol", "iso_week"], sort=True).agg(
        week_high=("high", "max"), week_low=("low", "min")).reset_index()
    weekly[["prior_week_high", "prior_week_low"]] = weekly.groupby(
        "symbol", sort=False)[["week_high", "week_low"]].shift(1)
    sessions = sessions.merge(
        weekly[["symbol", "iso_week", "prior_week_high", "prior_week_low"]],
        on=["symbol", "iso_week"], how="left")

    rows: list[dict[str, Any]] = []

    def add(symbol: str, known_at: Any, origin_at: Any, center: float,
            kind: str, unit: float, significance: float, label_sessions: int) -> None:
        if not np.isfinite(center) or center <= 0 or pd.isna(known_at):
            return
        width = _width(center, unit, cfg)
        rows.append({
            "symbol": symbol, "detector": "anchor", "kind": kind,
            "origin_at": origin_at if not pd.isna(origin_at) else known_at,
            "known_at": known_at, "center": float(center),
            "lower": float(center - width), "upper": float(center + width),
            "significance": significance, "source_sessions": label_sessions,
            "_atr": unit,
        })

    prior_session = sessions.groupby("symbol", sort=False)["session"].shift(1)
    for row, origin in zip(sessions.to_dict("records"), prior_session):
        symbol, known_at, unit = row["symbol"], row["session_first_bar"], row["prior_atr"]
        # Prior session high/low/close: knowable from the first bar of this
        # session, because the session that produced them has closed.
        add(symbol, known_at, origin, row["prior_high"], "resistance", unit, 3.0, 1)
        add(symbol, known_at, origin, row["prior_low"], "support", unit, 3.0, 1)
        add(symbol, known_at, origin, row["prior_close"], "both", unit, 2.0, 1)
        add(symbol, known_at, origin, row["prior_week_high"], "resistance", unit, 4.0, 5)
        add(symbol, known_at, origin, row["prior_week_low"], "support", unit, 4.0, 5)
        # Round numbers bracketing the prior close. They are permanent facts
        # about the price grid, so `origin_at` is the moment they became
        # relevant, not the moment they were "created".
        reference = row["prior_close"]
        if np.isfinite(reference) and np.isfinite(unit) and unit > 0:
            for step in cfg.round_number_steps:
                for candidate in (np.floor(reference / step) * step,
                                  np.ceil(reference / step) * step):
                    if candidate <= 0:
                        continue
                    if abs(candidate - reference) > cfg.round_number_max_distance_atr * unit:
                        continue
                    add(symbol, known_at, known_at, float(candidate), "both",
                        unit, 1.0, 1)

    # Opening range: knowable only once the range window has closed.
    span = pd.Timedelta(minutes=cfg.opening_range_minutes)
    opening = work.copy()
    opening["session_open"] = opening["session"] + SESSION_OPEN
    inside = opening.loc[opening["bar_end"] <= opening["session_open"] + span]
    if not inside.empty:
        summary = inside.groupby(["symbol", "session"], sort=True).agg(
            or_high=("high", "max"), or_low=("low", "min"),
            known_at=("bar_end", "max")).reset_index()
        summary = summary.merge(
            atr[["symbol", "session", "session_atr"]],
            on=["symbol", "session"], how="left")
        for row in summary.to_dict("records"):
            add(row["symbol"], row["known_at"], row["known_at"], row["or_high"],
                "resistance", row["session_atr"], 2.0, 1)
            add(row["symbol"], row["known_at"], row["known_at"], row["or_low"],
                "support", row["session_atr"], 2.0, 1)
    return _merge_book(rows, cfg, merge=False)


# --------------------------------------------------------------------------
# detector 3 — volume at price
# --------------------------------------------------------------------------

def _log_bin(prices: np.ndarray, step: float) -> np.ndarray:
    """Global, data-independent log-price bin indices.

    WHY THE GRID CANNOT BE FITTED TO THE DATA
    An earlier version placed bin edges across the symbol's observed min-max
    range. That is lookahead: the range includes future bars, so appending
    tomorrow's session moved every bin centre and therefore moved levels that
    were supposedly already knowable. The append test caught it.

    Bin identity here is a pure function of price — bin *k* is always the prices
    in ``[exp(k·step), exp((k+1)·step))`` — so truncating history changes which
    bins are populated and never what price a bin represents.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.floor(np.log(np.where(prices > 0, prices, np.nan)) / step)


def detect_volume_profile(bars: pd.DataFrame,
                          config: LevelConfig | None = None) -> pd.DataFrame:
    """High- and low-volume nodes from a trailing volume-at-price histogram.

    This is the only detector with a mechanism behind it. A high-volume node is
    a price where a lot of stock changed hands, so a lot of participants hold
    inventory there; a low-volume node is a price the market passed through
    quickly. Whether either matters is exactly what the reaction test asks — but
    unlike a bar pattern, it is at least a statement about participants rather
    than about the shape of a candle.

    Each bar's volume is spread uniformly across its own high-low range, which
    is the standard approximation when the intra-bar path is unknown.

    HOW IT STAYS FAST ENOUGH TO RUN
    The obvious implementation rebuilds a histogram from scratch for every
    symbol-session, which is quadratic in the lookback and takes hundreds of
    millions of Python-level steps on a real panel. Instead each session's
    volume is binned *once* onto a fixed per-symbol log-price grid, and the
    trailing window is a difference of cumulative sums along the session axis.
    The lookback is therefore free, and the result is identical to summing the
    window directly.
    """
    cfg = config or LevelConfig()
    work = _normalise_bars(bars)
    atr = session_atr(bars, cfg.atr_window)
    first_bar = work.groupby(["symbol", "session"], sort=True)["bar_end"].min()
    rows: list[dict[str, Any]] = []

    for symbol, group in work.groupby("symbol", sort=False):
        sessions = np.array(sorted(group["session"].unique()))
        if len(sessions) <= cfg.profile_lookback_sessions:
            continue
        step = cfg.profile_bin_bps / 10_000.0
        lows = group["low"].to_numpy(float)
        highs = group["high"].to_numpy(float)
        start_bin = _log_bin(lows, step)
        stop_bin = _log_bin(highs, step)
        finite = np.isfinite(start_bin) & np.isfinite(stop_bin)
        if not finite.any():
            continue
        base = int(np.nanmin(start_bin))
        n_bins = int(np.nanmax(stop_bin)) - base + 1
        if n_bins < cfg.profile_min_bins:
            continue
        # Centre price of a bin depends only on its global index, so it is
        # invariant to how much history happens to be loaded.
        centers = np.exp((np.arange(n_bins) + base + 0.5) * step)
        session_index = {value: position for position, value in enumerate(sessions)}

        # One histogram row per session, built by spreading each bar's volume
        # across the bins its range covers.
        histograms = np.zeros((len(sessions), n_bins), dtype=float)
        volumes = group["volume"].to_numpy(float)
        positions = np.array([session_index[value]
                              for value in group["session"].to_numpy()])
        valid = finite & np.isfinite(volumes) & (volumes > 0) & (highs >= lows)
        start_bin = np.where(finite, start_bin - base, 0).astype(int)
        stop_bin = np.where(finite, stop_bin - base, 0).astype(int)
        for index in np.flatnonzero(valid):
            first, last = start_bin[index], stop_bin[index]
            if last < first:
                first, last = last, first
            share = volumes[index] / (last - first + 1)
            histograms[positions[index], first:last + 1] += share

        # Trailing window as a difference of cumulative sums: strictly prior
        # sessions only, so the target session never sees itself.
        cumulative = np.vstack([np.zeros((1, n_bins)), np.cumsum(histograms, axis=0)])
        units = atr.loc[atr["symbol"] == symbol].set_index("session")["session_atr"]

        for position in range(cfg.profile_lookback_sessions, len(sessions)):
            target = sessions[position]
            lower = position - cfg.profile_lookback_sessions
            window = cumulative[position] - cumulative[lower]
            peak = window.max()
            if peak <= 0:
                continue
            unit = float(units.get(target, np.nan))
            known_at = first_bar.get((symbol, target), pd.NaT)
            if pd.isna(known_at):
                continue
            interior = window[1:-1]
            candidates = np.flatnonzero(
                (interior >= cfg.profile_min_peak_share * peak)
                & (interior >= window[:-2]) & (interior >= window[2:])) + 1
            for node in candidates:
                center = float(centers[node])
                width = _width(center, unit, cfg)
                rows.append({
                    "symbol": symbol, "detector": "volume_profile",
                    "kind": "both", "origin_at": sessions[lower],
                    "known_at": known_at, "center": center,
                    "lower": center - width, "upper": center + width,
                    "significance": float(window[node] / peak),
                    "source_sessions": cfg.profile_lookback_sessions,
                    "_atr": unit,
                })
    return _merge_book(rows, cfg)


# --------------------------------------------------------------------------
# detector 4 — multi-touch clusters
# --------------------------------------------------------------------------

def detect_multi_touch(bars: pd.DataFrame,
                       config: LevelConfig | None = None) -> pd.DataFrame:
    """Prices that several *distinct completed sessions* turned at.

    The significance of a level here is how many separate days reacted to it,
    which is the closest formalisation of what a trader means by "this level has
    been respected". A cluster seen on one day is not a level however sharp the
    pivot was; the same price turning on four different days is the claim.
    """
    cfg = config or LevelConfig()
    work = _normalise_bars(bars)
    atr = session_atr(bars, cfg.atr_window)
    first_bar = work.groupby(["symbol", "session"], sort=True)["bar_end"].min()

    # Session extremes are the touch candidates: they are unambiguous, they are
    # bar-size independent, and there are exactly two per session.
    extremes = work.groupby(["symbol", "session"], sort=True).agg(
        high=("high", "max"), low=("low", "min")).reset_index()

    rows: list[dict[str, Any]] = []
    for symbol, group in extremes.groupby("symbol", sort=False):
        group = group.sort_values("session", kind="stable").reset_index(drop=True)
        units = atr.loc[atr["symbol"] == symbol].set_index("session")["session_atr"]
        sessions = group["session"].to_list()
        for index in range(cfg.touch_min_sessions, len(sessions)):
            target = sessions[index]
            unit = float(units.get(target, np.nan))
            if not np.isfinite(unit) or unit <= 0:
                continue
            window = group.iloc[max(0, index - cfg.touch_lookback_sessions):index]
            if window.empty:
                continue
            known_at = first_bar.get((symbol, target), pd.NaT)
            for column, kind in (("high", "resistance"), ("low", "support")):
                points = window[["session", column]].dropna().to_numpy()
                if len(points) == 0:
                    continue
                order = np.argsort(points[:, 1].astype(float))
                points = points[order]
                cluster_sessions: list[Any] = []
                cluster_prices: list[float] = []

                def flush() -> None:
                    if len(set(cluster_sessions)) < cfg.touch_min_sessions:
                        return
                    center = float(np.mean(cluster_prices))
                    width = _width(center, unit, cfg)
                    rows.append({
                        "symbol": symbol, "detector": "multi_touch", "kind": kind,
                        "origin_at": min(cluster_sessions), "known_at": known_at,
                        "center": center,
                        "lower": min(center - width, float(min(cluster_prices))),
                        "upper": max(center + width, float(max(cluster_prices))),
                        "significance": float(len(set(cluster_sessions))),
                        "source_sessions": len(set(cluster_sessions)),
                        "_atr": unit,
                    })

                for session_value, price in points:
                    price = float(price)
                    if cluster_prices and price - cluster_prices[0] > cfg.touch_cluster_atr * unit:
                        flush()
                        cluster_sessions, cluster_prices = [], []
                    cluster_sessions.append(session_value)
                    cluster_prices.append(price)
                flush()
    return _merge_book(rows, cfg, merge=False)


DETECTORS: dict[str, Callable[..., pd.DataFrame]] = {
    "fractal": detect_fractal,
    "anchor": detect_anchor,
    "volume_profile": detect_volume_profile,
    "multi_touch": detect_multi_touch,
}


def build_level_book(bars: pd.DataFrame, detectors: tuple[str, ...] | None = None,
                     config: LevelConfig | None = None) -> pd.DataFrame:
    """Run the named detectors and stack their books."""
    cfg = config or LevelConfig()
    names = detectors or tuple(DETECTORS)
    unknown = set(names) - set(DETECTORS)
    if unknown:
        raise LevelError(f"unknown detectors: {sorted(unknown)}")
    books = [DETECTORS[name](bars, cfg) for name in names]
    books = [book for book in books if not book.empty]
    if not books:
        return _empty_book()
    return pd.concat(books, ignore_index=True)


def resample_hourly(bars: pd.DataFrame) -> pd.DataFrame:
    """Session-aligned hourly bars derived from the canonical five-minute series.

    Decisions are taken on completed hourly bars. The buckets are anchored to
    09:15, not to the wall clock, so the first bucket is 09:15--10:15 and a
    partial bucket at the end of a session is *kept* but marked incomplete: the
    close is a real price a decision could use, while `complete` records that
    the bucket did not run its full hour.
    """
    work = _normalise_bars(bars)
    session_open = work["session"] + SESSION_OPEN
    elapsed = (work["bar_end"] - session_open).dt.total_seconds().div(60)
    bucket = np.ceil(elapsed / 60.0) - 1
    work = work.loc[bucket.ge(0)].copy()
    bucket = bucket.loc[bucket.ge(0)]
    work["bucket_start"] = (work["session"] + SESSION_OPEN
                            + pd.to_timedelta(bucket * 60, unit="m"))
    hourly = work.groupby(["symbol", "session", "bucket_start"], sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"),
        bar_end=("bar_end", "max"), five_minute_bars=("close", "size"),
    ).reset_index()
    expected = hourly["bucket_start"] + pd.Timedelta(minutes=60)
    hourly["complete"] = hourly["bar_end"].ge(expected)
    return hourly.sort_values(["symbol", "bar_end"], kind="stable") \
        .reset_index(drop=True)


__all__ = [
    "DETECTORS", "KINDS", "LEVEL_COLUMNS", "LevelConfig", "LevelError",
    "build_level_book", "detect_anchor", "detect_fractal", "detect_multi_touch",
    "detect_volume_profile", "resample_hourly", "session_atr",
]
