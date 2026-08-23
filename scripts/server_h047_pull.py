#!/usr/bin/env python3
"""Remote, resumable H047 fixed-window Breeze pull.

Run via ``scripts/run_h047_pull.sh`` inside tmux. The request list is frozen
locally before upload; this process only resolves codes, resumes the manifest,
fetches 15:15 windows, and writes durable status.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.research_data.pipelines import bulk_intraday  # noqa: E402
from src.research_data.sources.breeze import BreezeClient  # noqa: E402

REQUESTS = ROOT / "data" / "metadata" / "h047_requests.parquet"
STATUS = ROOT / "data" / "metadata" / "h047_pull_status.json"
CHUNK = 1000
WORKERS = 16
MIN_INTERVAL = 0.25  # measured safe: ~4 req/s; 429s began near 7.5/s
SYSTEMIC_ERROR_RATE = 0.90


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}",
          flush=True)


def write_status(**values) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    values["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATUS.write_text(json.dumps(values, indent=2, default=str))


def main() -> int:
    if not REQUESTS.exists():
        log(f"FATAL: frozen request list missing: {REQUESTS}")
        return 2
    requests = pd.read_parquet(REQUESTS)
    requests["date"] = pd.to_datetime(requests["date"])
    log(f"frozen requests: {len(requests):,} pairs, "
        f"{requests['symbol'].nunique():,} symbols, "
        f"{requests['date'].nunique():,} sessions")

    try:
        client = BreezeClient(config.load_credentials(),
                              min_interval_s=MIN_INTERVAL, max_retries=4)
        client.authenticate()
        log("authenticated ok")
    except Exception as exc:
        log(f"FATAL: authentication failed: {type(exc).__name__}: {exc}")
        write_status(status="auth_failed", error=str(exc))
        return 2

    totals = {"attempted": 0, "with_data": 0, "empty": 0,
              "errors": 0, "rows": 0}
    started = time.perf_counter()
    chunk_no = 0
    while True:
        work, mapping = bulk_intraday.resolve_requests(requests)
        if work.empty:
            break
        chunk_no += 1
        chunk = work.sort_values(["date", "symbol"]).head(CHUNK)
        settled = mapping["requested_pairs"] - mapping["pending_pairs"]
        log(f"chunk {chunk_no}: {len(chunk):,} calls; "
            f"{settled:,} settled, {mapping['pending_pairs']:,} pending, "
            f"{mapping['unmapped_pairs']:,} unmapped")
        stats = bulk_intraday.fetch_batch(
            chunk, client, workers=WORKERS, checkpoint_every=250, verbose=False)
        for key in totals:
            totals[key] += stats.get(key, 0)
        attempted = max(stats["attempted"], 1)
        error_rate = stats["errors"] / attempted
        elapsed = time.perf_counter() - started
        rate = totals["attempted"] / max(elapsed, 1e-9)
        log(f"  chunk done: {stats['with_data']:,} data / "
            f"{stats['empty']:,} empty / {stats['errors']:,} errors; "
            f"{rate:.2f} calls/s overall")
        write_status(status="running", chunk=chunk_no, totals=totals,
                     mapping=mapping, calls_per_s=round(rate, 2))
        if error_rate >= SYSTEMIC_ERROR_RATE and attempted > 50:
            log("FATAL: systemic error rate; refresh token/check network, then rerun")
            write_status(status="systemic_errors", chunk=chunk_no,
                         totals=totals, mapping=mapping)
            return 5

    years = sorted(set(pd.to_datetime(requests["date"]).dt.year.tolist()))
    nifty = bulk_intraday.fetch_nifty_daily(client, years)
    elapsed_h = (time.perf_counter() - started) / 3600
    final_work, mapping = bulk_intraday.resolve_requests(requests)
    status = "complete" if final_work.empty else "incomplete"
    log(f"{status.upper()}: {totals}; NIFTY={nifty}; {elapsed_h:.2f}h")
    write_status(status=status, totals=totals, mapping=mapping,
                 nifty_daily=nifty, elapsed_hours=round(elapsed_h, 3))
    return 0 if status == "complete" else 4


if __name__ == "__main__":
    raise SystemExit(main())
