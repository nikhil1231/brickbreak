"""Deterministic, past-only price-action cases for the sealed replay loop."""
from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw


class PriceActionCaseError(RuntimeError):
    pass


CASE_SCHEMA_VERSION = "price_action_case.v1"
DECISION_SCHEMA = {
    "action": ["TAKE", "SKIP"],
    "confidence": "number between 0 and 1",
    "invalidation": "past-only price condition or null",
    "observed_reasons": "short list of facts visible in the case",
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str).encode()


def _first(frame: pd.DataFrame, choices: tuple[str, ...]) -> str:
    found = next((name for name in choices if name in frame.columns), None)
    if found is None:
        raise PriceActionCaseError(f"case bars need one of {choices}")
    return found


@dataclass(frozen=True)
class PriceActionAdapter:
    width: int = 800
    height: int = 450
    max_bars: int = 156

    @property
    def schema_hash(self) -> str:
        return hashlib.sha256(_canonical_json({
            "version": CASE_SCHEMA_VERSION,
            "decision": DECISION_SCHEMA,
            "width": self.width,
            "height": self.height,
            "max_bars": self.max_bars,
        })).hexdigest()[:16]

    def render_case(
        self,
        bars: pd.DataFrame,
        *,
        decision_at: Any | None = None,
        anonymised: bool = True,
    ) -> dict[str, Any]:
        """Render exactly the bars available at ``decision_at``.

        Passing a full frame containing future rows is safe: those rows are
        discarded using both ``bar_end`` and ``available_at`` before any
        normalisation, range calculation, or drawing occurs.
        """
        if not isinstance(bars, pd.DataFrame) or bars.empty:
            raise PriceActionCaseError("a price-action case needs non-empty bars")
        time_col = _first(bars, ("bar_end", "timestamp"))
        available_col = "available_at" if "available_at" in bars else time_col
        symbol_col = _first(bars, ("symbol_asof", "symbol"))
        price_cols = {
            key: _first(bars, (f"{key}_raw", key))
            for key in ("open", "high", "low", "close")
        }
        volume_col = _first(bars, ("volume_raw", "volume"))

        frame = bars.copy()
        frame[time_col] = pd.to_datetime(frame[time_col], errors="raise")
        frame[available_col] = pd.to_datetime(frame[available_col], errors="raise")
        cutoff = pd.Timestamp(decision_at) if decision_at is not None else frame[available_col].max()
        frame = frame[(frame[time_col] <= cutoff) & (frame[available_col] <= cutoff)]
        frame = frame.sort_values(time_col, kind="stable").tail(self.max_bars).reset_index(drop=True)
        if frame.empty:
            raise PriceActionCaseError("no bars were available at the decision timestamp")
        if frame[symbol_col].astype(str).nunique() != 1:
            raise PriceActionCaseError("one case may contain exactly one instrument")
        values = frame[[*price_cols.values(), volume_col]].apply(
            pd.to_numeric, errors="coerce")
        if values[list(price_cols.values())].isna().any().any():
            raise PriceActionCaseError("case contains missing OHLC values")
        invalid_quality = frame.get(
            "quality_flags", pd.Series("", index=frame.index)).astype(str).str.contains(
                "invalid_price|invalid_ohlc|negative_volume", regex=True)
        if invalid_quality.any() or (values[volume_col] < 0).any():
            raise PriceActionCaseError(
                "case contains a source-quality failure; retain it as a failed case")
        base = float(values[price_cols["close"]].iloc[0])
        if not np.isfinite(base) or base <= 0:
            raise PriceActionCaseError("case cannot be rebased from a non-positive close")

        rebased = pd.DataFrame({
            key: values[column].astype(float) / base * 100.0
            for key, column in price_cols.items()
        })
        rebased["volume"] = values[volume_col].astype(float)
        chart = self._draw(rebased, frame.iloc[-1])
        identity = "ASSET" if anonymised else str(frame[symbol_col].iloc[0])
        decision_label = "t=0" if anonymised else cutoff.isoformat()
        latest = frame.iloc[-1]
        sidecar = {
            "schema_version": CASE_SCHEMA_VERSION,
            "instrument": identity,
            "decision_at": decision_label,
            "bars": int(len(frame)),
            "last_close_rebased": round(float(rebased["close"].iloc[-1]), 6),
            "rolling_hour_trend_pct": _finite(latest.get("rolling_hour_trend_pct")),
            "zone_distance_atr": _finite(latest.get("zone_distance_atr")),
            "zone_overlap_frac": _finite(latest.get("zone_overlap_frac")),
            "rejection_strength_atr": _finite(latest.get("rejection_strength_atr")),
            "support_zone_kind": str(latest.get("support_zone_kind", "")),
            "support_touch_count": _integer(latest.get("support_touch_count")),
            "volume_surprise": _finite(
                latest.get("lagged_time_of_day_volume_surprise")),
            "relative_bars": [
                {
                    "t": int(i - len(rebased) + 1),
                    "o": round(float(row.open), 5),
                    "h": round(float(row.high), 5),
                    "l": round(float(row.low), 5),
                    "c": round(float(row.close), 5),
                    "v": round(float(row.volume), 2),
                }
                for i, row in enumerate(rebased.tail(24).itertuples(index=False))
            ],
        }
        sidecar_bytes = _canonical_json(sidecar)
        case_hash = hashlib.sha256(
            self.schema_hash.encode() + b"\0" + chart + b"\0" + sidecar_bytes
        ).hexdigest()
        return {
            "chart_bytes": chart,
            "chart_mime_type": "image/png",
            "sidecar": sidecar,
            "sidecar_bytes": sidecar_bytes,
            "decision_schema": DECISION_SCHEMA,
            "schema_hash": self.schema_hash,
            "case_hash": case_hash,
            "decision_at": cutoff,
        }

    def _draw(self, bars: pd.DataFrame, latest: pd.Series) -> bytes:
        image = Image.new("RGB", (self.width, self.height), "#0b1020")
        draw = ImageDraw.Draw(image)
        left, right, top, price_bottom = 42, self.width - 16, 18, int(self.height * 0.76)
        volume_top, bottom = price_bottom + 12, self.height - 24
        low = float(bars["low"].min())
        high = float(bars["high"].max())
        padding = max((high - low) * 0.05, 0.05)
        low, high = low - padding, high + padding

        def y_price(value: float) -> int:
            return int(price_bottom - (value - low) / max(high - low, 1e-9)
                       * (price_bottom - top))

        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = int(top + fraction * (price_bottom - top))
            draw.line((left, y, right, y), fill="#27324d", width=1)
        n = len(bars)
        step = (right - left) / max(n, 1)
        candle_width = max(1, min(5, int(step * 0.55)))
        max_volume = max(float(bars["volume"].max()), 1.0)
        for i, row in enumerate(bars.itertuples(index=False)):
            x = int(left + (i + 0.5) * step)
            colour = "#42d392" if row.close >= row.open else "#ff6b6b"
            draw.line((x, y_price(row.high), x, y_price(row.low)), fill=colour, width=1)
            y1, y2 = y_price(row.open), y_price(row.close)
            draw.rectangle((x - candle_width, min(y1, y2), x + candle_width,
                            max(max(y1, y2), min(y1, y2) + 1)), fill=colour)
            volume_height = int((bottom - volume_top) * row.volume / max_volume)
            draw.rectangle((x - candle_width, bottom - volume_height,
                            x + candle_width, bottom), fill=colour)

        zone_low = _finite(latest.get("support_zone_lower"))
        zone_high = _finite(latest.get("support_zone_upper"))
        if zone_low is not None and zone_high is not None:
            base_raw = float(latest.get("close_raw", latest.get("close", 1.0)))
            last_rebased = float(bars["close"].iloc[-1])
            scale = last_rebased / base_raw if base_raw else 1.0
            zl, zh = zone_low * scale, zone_high * scale
            draw.rectangle((left, y_price(zh), right, y_price(zl)),
                           outline="#ffd166", fill="#3b3522", width=1)
        draw.line((left, price_bottom, right, price_bottom), fill="#7080a0", width=1)
        draw.line((left, bottom, right, bottom), fill="#7080a0", width=1)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=False, compress_level=9)
        return buffer.getvalue()


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return round(result, 8) if np.isfinite(result) else None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if pd.notna(value) else None
    except (TypeError, ValueError):
        return None


__all__ = [
    "CASE_SCHEMA_VERSION", "DECISION_SCHEMA", "PriceActionAdapter",
    "PriceActionCaseError",
]
