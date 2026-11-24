"""Extrapolate full-dataset cost from what we actually measured.

Every input here is either a measurement from data/metadata/api_calls.jsonl or
a stated, visible assumption. Nothing is a silent guess.
"""
from __future__ import annotations

import json

from ...core import config

TRADING_DAYS_PER_YEAR = 250          # NSE, approx, after holidays
SECONDS_IN_FIRST_5_MIN = 300


def load_call_log() -> list[dict]:
    if not config.CALL_LOG.exists():
        return []
    out = []
    for line in config.CALL_LOG.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def measured_throughput(calls: list[dict], interval: str | None = None) -> dict:
    sel = [c for c in calls if c.get("ok") and (interval is None or c.get("interval") == interval)]
    if not sel:
        return {"n_calls": 0}
    durs = sorted(c["duration_s"] for c in sel)
    rows = [c["n_rows"] for c in sel]
    return {
        "n_calls": len(sel),
        "mean_duration_s": round(sum(durs) / len(durs), 3),
        "median_duration_s": round(durs[len(durs) // 2], 3),
        "p90_duration_s": round(durs[int(len(durs) * 0.9)], 3),
        "max_duration_s": round(durs[-1], 3),
        "mean_rows": round(sum(rows) / len(rows), 1),
        "max_rows": max(rows),
    }


def estimate_full_download(
    n_securities: int,
    years: int,
    bytes_per_row: float,
    mean_call_duration_s: float,
    days_per_call: int,
    min_interval_s: float,
    rows_per_day: int = SECONDS_IN_FIRST_5_MIN,
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR,
) -> dict:
    """days_per_call = how many trading days one API call can cover.

    Effective per-call cost is the larger of measured latency and our
    client-side throttle, since we deliberately do not hammer the API.
    """
    trading_days = years * trading_days_per_year
    total_rows = n_securities * trading_days * rows_per_day
    n_calls = n_securities * max(1, -(-trading_days // days_per_call))  # ceil
    per_call_s = max(mean_call_duration_s, min_interval_s)
    seconds_serial = n_calls * per_call_s
    return {
        "inputs": {
            "n_securities": n_securities,
            "years": years,
            "trading_days": trading_days,
            "rows_per_security_per_day": rows_per_day,
            "days_covered_per_call": days_per_call,
            "measured_bytes_per_row": bytes_per_row,
            "measured_mean_call_duration_s": mean_call_duration_s,
            "client_throttle_s": min_interval_s,
        },
        "total_rows": total_rows,
        "storage_gb_parquet": round(total_rows * bytes_per_row / 1024**3, 2),
        "api_calls": n_calls,
        "serial_hours": round(seconds_serial / 3600, 1),
        "serial_days": round(seconds_serial / 86400, 2),
        "calls_per_day_at_100_per_min": round(n_calls / (100 * 60 * 24), 3),
    }


def estimate_daily_history(n_securities: int, years: int, bytes_per_row: float,
                           mean_call_duration_s: float, years_per_call: int,
                           min_interval_s: float) -> dict:
    total_rows = n_securities * years * TRADING_DAYS_PER_YEAR
    n_calls = n_securities * max(1, -(-years // years_per_call))
    per_call_s = max(mean_call_duration_s, min_interval_s)
    return {
        "total_rows": total_rows,
        "storage_mb_parquet": round(total_rows * bytes_per_row / 1024**2, 1),
        "api_calls": n_calls,
        "serial_hours": round(n_calls * per_call_s / 3600, 2),
    }
