"""Causal support/resistance geometry over canonical intraday bars.

A pivot becomes a zone only when its right-hand confirmation bars have closed;
breaks and retests likewise become facts only at the closing timestamp of the
bar that establishes them. No row is rewritten when later bars arrive.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


class ZoneError(RuntimeError):
    pass


@dataclass(frozen=True)
class ZoneConfig:
    pivot_left: int = 2
    pivot_right: int = 2
    atr_window: int = 20
    width_atr: float = 0.25
    minimum_width_bps: float = 10.0
    merge_atr: float = 0.50
    break_atr: float = 0.10
    max_age_bars: int = 240

    def __post_init__(self) -> None:
        if self.pivot_left < 1 or self.pivot_right < 1:
            raise ValueError("pivot confirmation needs at least one bar on each side")
        if self.atr_window < 2 or self.max_age_bars < 1:
            raise ValueError("invalid ATR window or zone age")
        if min(self.width_atr, self.minimum_width_bps, self.merge_atr) <= 0:
            raise ValueError("zone widths and merge distance must be positive")


FEATURE_COLUMNS = (
    "atr_20", "rolling_hour_trend_pct", "tod_volume_median_20",
    "lagged_time_of_day_volume_surprise", "support_zone_kind",
    "support_zone_lower", "support_zone_upper", "support_zone_center",
    "support_origin_at", "support_known_at", "support_broken_at",
    "support_age_bars", "support_touch_count", "zone_distance_atr",
    "zone_overlap_frac", "approach_speed_atr_per_bar", "close_location",
    "rejection_strength_atr", "support_touch", "bullish_rejection",
    "bullish_flip_retest", "resistance_zone_lower", "resistance_zone_upper",
    "resistance_zone_center", "resistance_known_at",
)


def _required(frame: pd.DataFrame) -> dict[str, str]:
    aliases = {
        "symbol": ("symbol_asof", "symbol"),
        "time": ("bar_end", "timestamp"),
        "open": ("open_raw", "open"),
        "high": ("high_raw", "high"),
        "low": ("low_raw", "low"),
        "close": ("close_raw", "close"),
        "volume": ("volume_raw", "volume"),
    }
    selected: dict[str, str] = {}
    for role, choices in aliases.items():
        found = next((column for column in choices if column in frame.columns), None)
        if found is None:
            raise ZoneError(f"bars need one of {choices} for {role}")
        selected[role] = found
    return selected


def _infer_minutes(values: pd.Series) -> int:
    diffs = values.sort_values().diff().dt.total_seconds().div(60)
    diffs = diffs[(diffs > 0) & (diffs <= 60)]
    return int(round(float(diffs.median()))) if not diffs.empty else 5


def _context(frame: pd.DataFrame, columns: dict[str, str], cfg: ZoneConfig) -> pd.DataFrame:
    out = frame.copy()
    symbol, timestamp = columns["symbol"], columns["time"]
    high, low, close, volume = (columns[k] for k in ("high", "low", "close", "volume"))
    out[timestamp] = pd.to_datetime(out[timestamp], errors="raise")
    if "session" in out.columns:
        out["_session"] = pd.to_datetime(
            out["session"], errors="raise").dt.normalize()
    else:
        out["_session"] = out[timestamp].dt.normalize()
    out = out.sort_values([symbol, timestamp], kind="stable").reset_index(drop=False) \
        .rename(columns={"index": "_input_index"})
    grouped = out.groupby(symbol, sort=False, group_keys=False)
    previous_close = grouped[close].shift(1)
    true_range = pd.concat([
        (out[high] - out[low]).abs(),
        (out[high] - previous_close).abs(),
        (out[low] - previous_close).abs(),
    ], axis=1).max(axis=1)
    out["atr_20"] = true_range.groupby(out[symbol], sort=False).transform(
        lambda values: values.rolling(cfg.atr_window, min_periods=2).mean())
    base_bars = max(1, round(60 / _infer_minutes(out[timestamp])))
    out["rolling_hour_trend_pct"] = out.groupby(
        [symbol, "_session"], sort=False)[close].transform(
        lambda values: (values / values.shift(base_bars) - 1.0) * 100.0)
    out["_minute_of_day"] = out[timestamp].dt.hour * 60 + out[timestamp].dt.minute
    out["tod_volume_median_20"] = out.groupby(
        [symbol, "_minute_of_day"], sort=False)[volume].transform(
            lambda values: values.shift(1).rolling(20, min_periods=5).median())
    denominator = out["tod_volume_median_20"].replace(0, np.nan)
    out["lagged_time_of_day_volume_surprise"] = out[volume] / denominator
    return out


def _overlap_fraction(bar_low: float, bar_high: float,
                      zone_low: float, zone_high: float) -> float:
    overlap = max(0.0, min(bar_high, zone_high) - max(bar_low, zone_low))
    width = max(zone_high - zone_low, 1e-12)
    return min(1.0, overlap / width)


def annotate_corporate_actions(
    intraday_bars: pd.DataFrame,
    daily_adjustments: pd.DataFrame,
) -> pd.DataFrame:
    """Flag the first bar of sessions where the known adjustment changes."""
    required_daily = {"symbol", "date", "adj_factor"}
    if missing := required_daily - set(daily_adjustments.columns):
        raise ZoneError(f"daily adjustment frame missing: {sorted(missing)}")
    columns = _required(intraday_bars)
    out = intraday_bars.copy()
    if "session" not in out.columns:
        out["session"] = pd.to_datetime(out[columns["time"]]).dt.normalize()
    else:
        out["session"] = pd.to_datetime(out["session"]).dt.normalize()
    daily = daily_adjustments[list(required_daily)].copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily = daily.sort_values(["symbol", "date"], kind="stable")
    factor = pd.to_numeric(daily["adj_factor"], errors="coerce")
    previous = factor.groupby(daily["symbol"], sort=False).shift(1)
    changed = factor.notna() & previous.notna() & ~np.isclose(factor, previous)
    action_keys = set(zip(
        daily.loc[changed, "symbol"].astype(str),
        daily.loc[changed, "date"],
    ))
    quality = out.get("quality_flags", pd.Series("", index=out.index)).fillna("").astype(str)
    ordered = out.sort_values([columns["symbol"], "session", columns["time"]], kind="stable")
    first_indices = ordered.groupby(
        [columns["symbol"], "session"], sort=False).head(1).index
    for index in first_indices:
        key = (str(out.at[index, columns["symbol"]]), out.at[index, "session"])
        if key in action_keys:
            quality.at[index] = "|".join(
                item for item in (quality.at[index], "corporate_action") if item)
    out["quality_flags"] = quality
    return out


def _new_zone(kind: str, center: float, width: float, origin_at: pd.Timestamp,
              known_at: pd.Timestamp, known_index: int) -> dict[str, Any]:
    return {
        "kind": kind, "center": float(center),
        "lower": float(center - width), "upper": float(center + width),
        "origin_at": origin_at, "known_at": known_at,
        "known_index": known_index, "broken_at": pd.NaT,
        "touch_count": 0, "was_touching": False, "active": True,
        "seeds": 1, "retest_now": False, "age": 0,
    }


def _merge_or_add(zones: list[dict[str, Any]], candidate: dict[str, Any],
                  atr: float, cfg: ZoneConfig) -> None:
    eligible = [
        zone for zone in zones
        if zone["active"] and zone["kind"] == candidate["kind"]
        and abs(zone["center"] - candidate["center"]) <= cfg.merge_atr * atr
    ]
    if not eligible:
        zones.append(candidate)
        return
    zone = min(eligible, key=lambda value: abs(value["center"] - candidate["center"]))
    weight = int(zone["seeds"])
    zone["center"] = (zone["center"] * weight + candidate["center"]) / (weight + 1)
    zone["lower"] = min(zone["lower"], candidate["lower"])
    zone["upper"] = max(zone["upper"], candidate["upper"])
    zone["seeds"] = weight + 1


def _zone_snapshot(zone: dict[str, Any] | None, prefix: str) -> dict[str, Any]:
    if zone is None:
        values = {
            f"{prefix}_zone_kind": "", f"{prefix}_zone_lower": np.nan,
            f"{prefix}_zone_upper": np.nan, f"{prefix}_zone_center": np.nan,
            f"{prefix}_known_at": pd.NaT,
        }
    else:
        values = {
            f"{prefix}_zone_kind": zone["kind"],
            f"{prefix}_zone_lower": zone["lower"],
            f"{prefix}_zone_upper": zone["upper"],
            f"{prefix}_zone_center": zone["center"],
            f"{prefix}_known_at": zone["known_at"],
        }
    if prefix == "support":
        values.update({
            "support_origin_at": pd.NaT if zone is None else zone["origin_at"],
            "support_broken_at": pd.NaT if zone is None else zone["broken_at"],
            "support_age_bars": np.nan if zone is None else zone["age"],
            "support_touch_count": 0 if zone is None else zone["touch_count"],
        })
    return values


def build_zone_state_machine(
    bars: pd.DataFrame,
    config: ZoneConfig | None = None,
) -> pd.DataFrame:
    """Attach the nearest causal support and resistance state to every bar."""
    cfg = config or ZoneConfig()
    columns = _required(bars)
    work = _context(bars, columns, cfg)
    features: list[dict[str, Any]] = []

    for _, group in work.groupby(columns["symbol"], sort=False):
        group = group.reset_index(drop=True)
        zones: list[dict[str, Any]] = []
        highs = pd.to_numeric(group[columns["high"]], errors="coerce").to_numpy(float)
        lows = pd.to_numeric(group[columns["low"]], errors="coerce").to_numpy(float)
        closes = pd.to_numeric(group[columns["close"]], errors="coerce").to_numpy(float)
        times = pd.to_datetime(group[columns["time"]]).to_list()
        atrs = pd.to_numeric(group["atr_20"], errors="coerce").to_numpy(float)

        for i, row in group.iterrows():
            current_time = times[i]
            high, low, close = highs[i], lows[i], closes[i]
            atr = atrs[i]
            if not np.isfinite(atr) or atr <= 0:
                atr = max(abs(close) * 0.005, 1e-9)
            action = "corporate_action" in str(row.get("quality_flags", ""))
            for zone in zones:
                zone["retest_now"] = False
                if not zone["active"]:
                    continue
                zone["age"] = i - int(zone["known_index"])
                if action or zone["age"] > cfg.max_age_bars:
                    zone["active"] = False
                    continue
                buffer = cfg.break_atr * atr
                if zone["kind"] == "resistance" and close > zone["upper"] + buffer:
                    zone["kind"] = "flip_support"
                    zone["broken_at"] = current_time
                    zone["was_touching"] = False
                elif zone["kind"] in ("support", "flip_support") \
                        and close < zone["lower"] - buffer:
                    zone["active"] = False
                    continue
                touching = high >= zone["lower"] and low <= zone["upper"]
                if touching and not zone["was_touching"] and i > zone["known_index"]:
                    zone["touch_count"] += 1
                    if zone["kind"] == "flip_support" \
                            and pd.notna(zone["broken_at"]) \
                            and current_time > zone["broken_at"]:
                        zone["retest_now"] = True
                # The breakout bar can overlap the old resistance on its way
                # through.  That is not a later retest and must not suppress a
                # genuine touch on the following completed bar.
                zone["was_touching"] = bool(
                    touching and not (
                        zone["kind"] == "flip_support"
                        and current_time == zone["broken_at"]))

            seed_i = i - cfg.pivot_right
            if seed_i >= cfg.pivot_left:
                left = seed_i - cfg.pivot_left
                window_high = highs[left:i + 1]
                window_low = lows[left:i + 1]
                seed_at = times[seed_i]
                width = max(cfg.width_atr * atr,
                            closes[seed_i] * cfg.minimum_width_bps / 10_000.0)
                if np.isfinite(highs[seed_i]) and highs[seed_i] == np.nanmax(window_high) \
                        and int(np.sum(window_high == highs[seed_i])) == 1:
                    _merge_or_add(
                        zones, _new_zone("resistance", highs[seed_i], width,
                                         seed_at, current_time, i), atr, cfg)
                if np.isfinite(lows[seed_i]) and lows[seed_i] == np.nanmin(window_low) \
                        and int(np.sum(window_low == lows[seed_i])) == 1:
                    _merge_or_add(
                        zones, _new_zone("support", lows[seed_i], width,
                                         seed_at, current_time, i), atr, cfg)

            supports = [
                zone for zone in zones if zone["active"]
                and zone["kind"] in ("support", "flip_support")
                and zone["center"] <= close + (zone["upper"] - zone["center"])
            ]
            resistances = [
                zone for zone in zones if zone["active"]
                and zone["kind"] == "resistance"
                and zone["center"] >= close - (zone["center"] - zone["lower"])
            ]
            support = min(supports, key=lambda z: abs(close - z["center"]), default=None)
            resistance = min(resistances, key=lambda z: abs(close - z["center"]), default=None)
            record: dict[str, Any] = {"_input_index": row["_input_index"]}
            record.update(_zone_snapshot(support, "support"))
            record.update(_zone_snapshot(resistance, "resistance"))
            record["close_location"] = (
                (close - low) / (high - low) if high > low else 0.5)
            if support is None:
                record.update({
                    "zone_distance_atr": np.nan, "zone_overlap_frac": 0.0,
                    "approach_speed_atr_per_bar": np.nan,
                    "rejection_strength_atr": 0.0, "support_touch": False,
                    "bullish_rejection": False, "bullish_flip_retest": False,
                })
            else:
                overlap = _overlap_fraction(low, high, support["lower"], support["upper"])
                touch = overlap > 0
                old_i = max(0, i - 3)
                old_distance = abs(closes[old_i] - support["center"])
                current_distance = abs(close - support["center"])
                rejection = max(0.0, (close - low) / atr) if touch else 0.0
                bullish = bool(touch and record["close_location"] >= 0.65
                               and close >= support["center"])
                record.update({
                    "zone_distance_atr": (close - support["center"]) / atr,
                    "zone_overlap_frac": overlap,
                    "approach_speed_atr_per_bar": (
                        (old_distance - current_distance) / atr / max(i - old_i, 1)),
                    "rejection_strength_atr": rejection,
                    "support_touch": touch,
                    "bullish_rejection": bullish and support["kind"] == "support",
                    "bullish_flip_retest": bullish and bool(support["retest_now"]),
                })
            features.append(record)

    feature_frame = pd.DataFrame(features).set_index("_input_index")
    context = work.set_index("_input_index")[[
        "atr_20", "rolling_hour_trend_pct", "tod_volume_median_20",
        "lagged_time_of_day_volume_surprise",
    ]]
    combined = context.join(feature_frame, how="left")
    result = bars.copy()
    for column in FEATURE_COLUMNS:
        result[column] = combined.reindex(result.index)[column].to_numpy()
    return result


__all__ = [
    "FEATURE_COLUMNS", "ZoneConfig", "ZoneError", "annotate_corporate_actions",
    "build_zone_state_machine",
]
