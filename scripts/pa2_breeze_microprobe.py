#!/usr/bin/env python3
"""Measure Breeze intraday behaviour with real, bounded source calls.

This report is deliberately descriptive.  It cannot mark PA2 passed because
point-in-time identity coverage is measured separately from the daily panel.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.research_data.pipelines import storage  # noqa: E402
from src.research_data.sources.breeze import BreezeClient, fmt_ts  # noqa: E402


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock-code", default="RELIND")
    parser.add_argument("--symbol", default="RELIANCE")
    parser.add_argument("--sample-session", default="2025-02-03")
    parser.add_argument("--output", type=Path,
                        default=Path("data/metadata/research_store/price_action/pa2_source_probe.json"))
    return parser.parse_args()


def stamp(day: str, clock: str) -> str:
    return fmt_ts(datetime.fromisoformat(f"{day}T{clock}"))


def payload_hash(rows: list[dict] | None) -> str | None:
    if not rows:
        return None
    text = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def describe(result, symbol: str) -> dict[str, Any]:
    frame = storage.normalize(result.raw or [], result.stock_code, symbol)
    return {
        **result.log_record(),
        "payload_sha256": payload_hash(result.raw),
        "first_timestamp": None if frame.empty else str(frame["timestamp"].min()),
        "last_timestamp": None if frame.empty else str(frame["timestamp"].max()),
        "negative_volume_rows": int((frame["volume"] < 0).sum()) if not frame.empty else 0,
        "duplicate_timestamps": int(frame["timestamp"].duplicated().sum()) if not frame.empty else 0,
    }


def main() -> int:
    options = args()
    client = BreezeClient(config.load_credentials(), min_interval_s=0.6, max_retries=2)
    auth = client.authenticate()
    calls: list[dict[str, Any]] = []
    day = options.sample_session
    one_day: dict[str, Any] = {}
    one_day_frames: dict[str, pd.DataFrame] = {}
    for interval in ("1minute", "5minute", "30minute"):
        result = client.raw(
            interval, options.stock_code, stamp(day, "09:15:00"),
            stamp(day, "15:30:00"), endpoint="v2")
        description = describe(result, options.symbol)
        calls.append(description)
        one_day[interval] = description
        one_day_frames[interval] = storage.normalize(
            result.raw or [], options.stock_code, options.symbol)

    repeat = client.raw(
        "5minute", options.stock_code, stamp(day, "09:15:00"),
        stamp(day, "15:30:00"), endpoint="v2")
    repeat_description = describe(repeat, options.symbol)
    calls.append(repeat_description)

    cap = client.raw(
        "5minute", options.stock_code, stamp("2025-01-01", "09:15:00"),
        stamp("2025-03-31", "15:30:00"), endpoint="v2")
    cap_description = describe(cap, options.symbol)
    calls.append(cap_description)
    if cap.n_rows >= 1000:
        first = pd.Timestamp(cap_description["first_timestamp"])
        last = pd.Timestamp(cap_description["last_timestamp"])
        midpoint = pd.Timestamp("2025-02-15")
        cap_side = "tail" if first >= midpoint else ("head" if last <= midpoint else "unknown")
    else:
        cap_side = "not_observed"

    history: dict[str, Any] = {}
    for probe_day in ("2017-04-03", "2018-04-02", "2020-01-02"):
        result = client.raw(
            "5minute", options.stock_code, stamp(probe_day, "09:15:00"),
            stamp(probe_day, "15:30:00"), endpoint="v2")
        description = describe(result, options.symbol)
        calls.append(description)
        history[probe_day] = description

    minute = one_day_frames["1minute"].set_index("timestamp")
    five = one_day_frames["5minute"].set_index("timestamp")
    alignment_checks = []
    for timestamp in five.index:
        if timestamp.time() >= datetime.strptime("15:30", "%H:%M").time():
            continue
        window = minute.loc[timestamp:timestamp + pd.Timedelta(minutes=4)]
        if len(window) != 5:
            continue
        aggregated = {
            "open": float(window["open"].iloc[0]),
            "high": float(window["high"].max()),
            "low": float(window["low"].min()),
            "close": float(window["close"].iloc[-1]),
            "volume": int(window["volume"].sum()),
        }
        observed = {name: float(five.loc[timestamp, name])
                    for name in ("open", "high", "low", "close", "volume")}
        alignment_checks.append({
            "timestamp": str(timestamp),
            "matches_start_label": all(
                abs(observed[name] - aggregated[name]) < 1e-9
                for name in observed),
        })
    timestamps_are_starts = bool(
        alignment_checks and all(item["matches_start_label"]
                                 for item in alignment_checks))
    terminal_rows = {
        interval: frame[frame["timestamp"].dt.time
                        == datetime.strptime("15:30", "%H:%M").time()].to_dict("records")
        for interval, frame in one_day_frames.items()
    }

    reconciliation = {"available": False}
    daily_path = config.NORMALIZED_DIR / "daily_bars.parquet"
    if daily_path.exists():
        daily = pd.read_parquet(daily_path)
        row = daily[
            daily["symbol"].astype(str).eq(options.symbol)
            & pd.to_datetime(daily["date"]).eq(pd.Timestamp(day))
        ]
        regular_five = five[five.index.time < datetime.strptime("15:30", "%H:%M").time()]
        if len(row) == 1 and not regular_five.empty:
            aggregate = {
                "open": float(regular_five["open"].iloc[0]),
                "high": float(regular_five["high"].max()),
                "low": float(regular_five["low"].min()),
                "close": float(regular_five["close"].iloc[-1]),
                "volume": int(regular_five["volume"].sum()),
            }
            expected = {name: float(row.iloc[0][name])
                        for name in ("open", "high", "low", "close", "volume")}
            reconciliation = {
                "available": True, "intraday": aggregate, "daily": expected,
                "ohlc_exact": all(abs(aggregate[name] - expected[name]) < 1e-9
                                  for name in ("open", "high", "low", "close")),
                "volume_ratio": aggregate["volume"] / expected["volume"],
            }

    stable = (
        one_day["5minute"]["payload_sha256"] is not None
        and one_day["5minute"]["payload_sha256"] == repeat_description["payload_sha256"])
    source_usable = bool(
        one_day["5minute"]["n_rows"] > 0
        and one_day["5minute"]["error"] is None
        and stable
        and timestamps_are_starts
        and cap_side in ("tail", "head"))
    report = {
        "stage": "PA2_SOURCE_PROBE",
        "status": "measured",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "stock_code": options.stock_code,
        "symbol": options.symbol,
        "sample_session": day,
        "authentication_status": auth.get("Status") if isinstance(auth, dict) else None,
        "one_day": one_day,
        "repeat_5minute": repeat_description,
        "repeat_payload_stable": stable,
        "timestamp_semantics": {
            "five_minute_labels_bar_start": timestamps_are_starts,
            "checked_windows": len(alignment_checks),
            "terminal_1530_rows": terminal_rows,
            "canonical_rule": "bar_end = source timestamp + interval; exclude zero-volume 15:30 terminal rows",
        },
        "daily_reconciliation": reconciliation,
        "cap_probe": cap_description,
        "cap_side_observed": cap_side,
        "history_probe": history,
        "source_usable_for_bootstrap": source_usable,
        "pa2_verdict": "PENDING_IDENTITY_AND_RECONCILIATION",
        "calls": calls,
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({
        "output": str(options.output), "source_usable": source_usable,
        "cap_side": cap_side, "repeat_stable": stable,
        "rows_5minute": one_day["5minute"]["n_rows"],
    }, indent=2))
    return 0 if source_usable else 4


if __name__ == "__main__":
    raise SystemExit(main())
