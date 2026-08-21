"""Data-quality checks over a normalized frame. Output is JSON-serializable.

Checks cover the questions the spike has to answer: are timestamps sane and in
what zone, are OHLC internally consistent, is per-bar volume actually present
(as opposed to zero-filled or cumulative), are there duplicate or missing
intervals, and can first-five-minute volume be reconstructed.
"""
from __future__ import annotations

from datetime import time as dtime
from typing import Any

import pandas as pd

MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
STEP_SECONDS = {"1second": 1, "1minute": 60, "5minute": 300, "30minute": 1800, "1day": None}


def _py(v: Any) -> Any:
    """Make numpy/pandas scalars JSON-safe."""
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            return str(v)
    return v


def check(df: pd.DataFrame, interval: str, raw_columns: list[str] | None = None) -> dict:
    n = len(df)
    out: dict[str, Any] = {
        "interval": interval,
        "n_rows": n,
        "raw_columns": raw_columns or [],
    }
    if n == 0:
        out["empty"] = True
        return out

    ts = df["timestamp"]
    out["timestamp"] = {
        "dtype": str(ts.dtype),
        "tz_aware": ts.dt.tz is not None if hasattr(ts.dt, "tz") else False,
        "n_null": int(ts.isna().sum()),
        "min": _py(ts.min()),
        "max": _py(ts.max()),
        "monotonic_increasing": bool(ts.is_monotonic_increasing),
        "n_duplicates": int(ts.duplicated().sum()),
        # If values are IST wall-clock, intraday stamps land in 09:15-15:30.
        "distinct_dates": [str(d) for d in sorted(ts.dt.date.unique())[:10]],
        "n_distinct_dates": int(ts.dt.date.nunique()),
        "min_time_of_day": str(ts.dt.time.min()),
        "max_time_of_day": str(ts.dt.time.max()),
    }

    if interval != "1day":
        in_session = ts.dt.time.between(MARKET_OPEN, MARKET_CLOSE)
        out["timestamp"]["n_outside_0915_1530_IST"] = int((~in_session).sum())
        out["timestamp"]["reads_as_IST_wallclock"] = bool(in_session.all())

    ohlc = df[["open", "high", "low", "close"]]
    out["ohlc"] = {
        "n_null_any": int(ohlc.isna().any(axis=1).sum()),
        "n_nonpositive": int((ohlc <= 0).any(axis=1).sum()),
        "n_high_lt_low": int((df["high"] < df["low"]).sum()),
        "n_open_outside_hl": int(((df["open"] > df["high"]) | (df["open"] < df["low"])).sum()),
        "n_close_outside_hl": int(((df["close"] > df["high"]) | (df["close"] < df["low"])).sum()),
        "n_flat_bars": int((df["high"] == df["low"]).sum()),
    }

    vol = df["volume"]
    out["volume"] = {
        "n_missing_sentinel": int((vol < 0).sum()),
        "n_zero": int((vol == 0).sum()),
        "pct_zero": round(float((vol == 0).mean() * 100), 2),
        "min": _py(vol.min()),
        "max": _py(vol.max()),
        "sum": _py(vol.sum()),
        # A monotonically non-decreasing series would mean cumulative, not per-bar.
        "looks_cumulative": bool(vol.is_monotonic_increasing and n > 3 and vol.min() != vol.max()),
    }

    step = STEP_SECONDS.get(interval)
    if step and out["timestamp"]["n_distinct_dates"] >= 1:
        out["continuity"] = _continuity(ts, step)

    if interval in ("1second", "1minute"):
        out["first_five_minutes"] = _first_five(df, interval, step or 1)
    return out


def _continuity(ts: pd.Series, step: int) -> dict:
    """Gap analysis per day, so the overnight jump isn't counted as a gap."""
    per_day = {}
    total_missing = 0
    for d, grp in ts.groupby(ts.dt.date):
        s = grp.sort_values()
        deltas = s.diff().dt.total_seconds().dropna()
        expected = int((s.max() - s.min()).total_seconds() // step) + 1
        missing = expected - len(s)
        total_missing += max(missing, 0)
        per_day[str(d)] = {
            "n_bars": int(len(s)),
            "expected_bars_in_span": expected,
            "missing_in_span": int(missing),
            "n_gaps": int((deltas > step).sum()),
            "largest_gap_s": _py(deltas.max()) if len(deltas) else None,
        }
    return {"step_seconds": step, "total_missing_in_span": int(total_missing), "per_day": per_day}


def _first_five(df: pd.DataFrame, interval: str, step: int) -> dict:
    """Can we reconstruct 09:15:00-09:19:59 volume, and is the window complete?"""
    res = {}
    for d, grp in df.groupby(df["timestamp"].dt.date):
        win = grp[grp["timestamp"].dt.time.between(dtime(9, 15), dtime(9, 19, 59))]
        expected = 300 if interval == "1second" else 5
        res[str(d)] = {
            "n_bars_in_window": int(len(win)),
            "expected_bars": expected,
            "coverage_pct": round(len(win) / expected * 100, 2),
            "total_volume": _py(win["volume"].clip(lower=0).sum()),
            "n_zero_volume_bars": int((win["volume"] == 0).sum()),
            "first_bar": _py(win["timestamp"].min()) if len(win) else None,
            "last_bar": _py(win["timestamp"].max()) if len(win) else None,
            "opening_bar_ohlc": (
                win.sort_values("timestamp").iloc[0][["open", "high", "low", "close", "volume"]]
                .apply(_py).to_dict() if len(win) else None
            ),
            "reconstructable": bool(len(win) > 0 and (win["volume"] >= 0).all()),
        }
    return res
