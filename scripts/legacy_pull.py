#!/usr/bin/env python3
"""Unattended pull of the pre-delivery NSE bhavcopy archive (1995 -> 2020).

The modern `sec_bhavdata_full` archive 404s before ~2020, which is why the
panel floors at 2020-01-01. The legacy `cmDDMMMYYYYbhav.csv.zip` archive has
no delivery columns but does carry price, volume, trades and ISIN, and it
reaches back to 1995. Every price-only family — momentum, reversal,
volatility, sector diffusion — is confined to the delivery era for no reason
other than that nobody pulled this.

Verified against the modern archive on overlapping sessions (2020-07-15,
2021-03-15): OHLC and volume agree to the bit. Turnover differs only because
the modern file rounds to whole lakhs while this one is exact rupees.

Resumable by construction: each session is a parquet under
data/raw/bhavcopy_legacy/YYYY/, non-trading days are empty markers, and a
rerun requests only what is missing. Killing this and restarting it costs
nothing but the chunk in flight.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.research_data.sources import nse            # noqa: E402

STATUS = ROOT / "data" / "metadata" / "legacy_pull_status.json"

# NSE's first archived session. 1994 and earlier 404 across the board.
FLOOR = date(1995, 1, 1)


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def write_status(**kw) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    kw["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATUS.write_text(json.dumps(kw, indent=2, default=str))


def held(year: int) -> tuple[int, int]:
    """(sessions, markers) already on disk for a year."""
    import pandas as pd
    d = nse.LEGACY_BHAV_DIR / str(year)
    if not d.exists():
        return 0, 0
    s = m = 0
    for p in d.glob("*.parquet"):
        try:
            if len(pd.read_parquet(p, columns=["symbol"])):
                s += 1
            else:
                m += 1
        except Exception:
            m += 1
    return s, m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, default=FLOOR)
    ap.add_argument("--end", type=date.fromisoformat, default=date(2019, 12, 31))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--throttle", type=float, default=0.25)
    args = ap.parse_args()

    log(f"legacy bhavcopy pull {args.start} -> {args.end} "
        f"({args.workers} workers, {args.throttle}s throttle)")
    log(f"target: {nse.LEGACY_BHAV_DIR}")

    t0 = time.perf_counter()
    totals = {"requested": 0, "downloaded": 0, "missing": 0, "rows": 0}

    # Year at a time: bounded memory, and a checkpoint every ~250 sessions so
    # an interrupted run loses at most one year of in-flight work.
    years = list(range(args.start.year, args.end.year + 1))
    for i, y in enumerate(years, 1):
        lo = max(args.start, date(y, 1, 1))
        hi = min(args.end, date(y, 12, 31))
        s0, m0 = held(y)
        try:
            st = nse.sync_legacy(lo, hi, workers=args.workers,
                                 throttle=args.throttle, verbose=False)
        except Exception as exc:
            log(f"FATAL: {y}: {type(exc).__name__}: {exc}")
            write_status(status="error", year=y, error=str(exc), totals=totals)
            return 1

        for k in totals:
            totals[k] += st.get(k, 0)
        s1, m1 = held(y)
        el = time.perf_counter() - t0
        eta = (el / i) * (len(years) - i) / 60
        log(f"{y}: +{st['downloaded']:3d} sessions, +{st['missing']:3d} non-trading, "
            f"{st['rows']:>9,} rows | held {s1} sessions "
            f"| {i}/{len(years)} years, ETA {eta:.0f}m")
        if st["relocated"]:
            log(f"     relocated: {', '.join(st['relocated'][:5])}")
        write_status(status="running", year=y, done_years=i, total_years=len(years),
                     totals=totals, elapsed_min=round(el / 60, 1))

    el = time.perf_counter() - t0
    log(f"COMPLETE: {totals} in {el/60:.1f}m")
    write_status(status="complete", totals=totals, elapsed_min=round(el / 60, 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
