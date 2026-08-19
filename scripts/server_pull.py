#!/usr/bin/env python3
"""Unattended bulk pull of 09:15-09:20 one-second bars for screened candidates.

Designed to be started in tmux and left alone. Everything that can reasonably
be recovered from is recovered from; everything that cannot is reported clearly
and exits non-zero rather than burning through the work list marking rows dead.

Recoverable  : 429 rate limits (client retries), transient network errors,
               a chunk that throws (retried with backoff).
Not recoverable: an expired Breeze session token. Tokens expire ~midnight IST,
               so an overnight run can outlive its token. On detection the run
               stops cleanly with status=token_expired; restarting after
               refreshing BREEZE_SESSION_TOKEN resumes from the manifest.

Progress is written to data/metadata/pull_status.json every chunk so it can be
inspected from another shell without touching the tmux session.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config, fetch_opening as fo          # noqa: E402
from src.breeze_client import BreezeClient           # noqa: E402

WORK_LIST = ROOT / "data" / "metadata" / "work_list.parquet"
STATUS = ROOT / "data" / "metadata" / "pull_status.json"

CHUNK = 2000              # pairs per chunk; a chunk boundary is a checkpoint
WORKERS = 4
MIN_INTERVAL = 0.25       # ~4 req/s; measured safe (429s began near 7.5/s)
MAX_CHUNK_RETRIES = 3
# If a chunk comes back almost entirely errors, something systemic is wrong
# (token, network, upstream outage) — stop rather than churn.
SYSTEMIC_ERROR_RATE = 0.9


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def write_status(**kw) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    kw["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATUS.write_text(json.dumps(kw, indent=2, default=str))


def looks_like_auth_failure(exc: BaseException) -> bool:
    s = str(exc).lower()
    return any(k in s for k in ("session", "authenticate", "not logged", "invalid token"))


def main() -> int:
    if not WORK_LIST.exists():
        log(f"FATAL: work list missing at {WORK_LIST}")
        return 2

    work = pd.read_parquet(WORK_LIST)
    work["date"] = pd.to_datetime(work["date"])
    code_map = dict(zip(work["symbol"], work["isec_code"]))
    log(f"work list: {len(work):,} pairs, {work['symbol'].nunique():,} symbols, "
        f"{work['date'].nunique():,} dates")

    try:
        client = BreezeClient(config.load_credentials(), min_interval_s=MIN_INTERVAL)
        client.authenticate()
        log("authenticated ok")
    except Exception as exc:
        log(f"FATAL: authentication failed: {exc}")
        write_status(status="auth_failed", error=str(exc))
        return 2

    t_start = time.perf_counter()
    totals = {"attempted": 0, "with_data": 0, "empty": 0, "errors": 0, "rows": 0}
    chunk_no = 0

    while True:
        pending = fo.pending_pairs(work, fo.load_manifest())
        if pending.empty:
            break
        chunk_no += 1
        # newest_first so the most recent (most useful) data lands first.
        chunk = pending.sort_values(["date", "symbol"],
                                    ascending=[False, True]).head(CHUNK)
        done_before = len(work) - len(pending)
        log(f"chunk {chunk_no}: {len(chunk):,} pairs  "
            f"({done_before:,}/{len(work):,} settled, {len(pending):,} left)")

        stats = None
        for attempt in range(1, MAX_CHUNK_RETRIES + 1):
            try:
                stats = fo.fetch_batch(chunk, client, workers=WORKERS,
                                       code_map=code_map, newest_first=True,
                                       checkpoint_every=250, verbose=False)
                break
            except Exception as exc:
                if looks_like_auth_failure(exc):
                    log(f"FATAL: session token appears expired: {exc}")
                    write_status(status="token_expired", chunk=chunk_no,
                                 totals=totals, hint="refresh BREEZE_SESSION_TOKEN and rerun")
                    return 3
                back = 30 * attempt
                log(f"  chunk error (attempt {attempt}/{MAX_CHUNK_RETRIES}): "
                    f"{type(exc).__name__}: {exc} — retrying in {back}s")
                log(traceback.format_exc(limit=3))
                time.sleep(back)
        if stats is None:
            log("FATAL: chunk failed all retries")
            write_status(status="chunk_failed", chunk=chunk_no, totals=totals)
            return 4

        for k in totals:
            totals[k] += stats.get(k, 0)

        att = max(stats["attempted"], 1)
        err_rate = stats["errors"] / att
        if err_rate >= SYSTEMIC_ERROR_RATE and att > 50:
            log(f"FATAL: {err_rate:.0%} of the chunk errored — stopping (systemic problem). "
                f"Most likely an expired session token.")
            write_status(status="systemic_errors", chunk=chunk_no, totals=totals,
                         last_chunk=stats, hint="check token, then rerun to resume")
            return 5

        elapsed = time.perf_counter() - t_start
        rate = totals["attempted"] / max(elapsed, 1e-9)
        remaining = max(len(work) - (done_before + stats["attempted"]), 0)
        eta_h = remaining / rate / 3600 if rate > 0 else None
        log(f"  chunk done: {stats['with_data']:,} data / {stats['empty']:,} empty / "
            f"{stats['errors']:,} err / {stats['rows']:,} rows @ {stats['calls_per_s']:.2f}/s"
            + (f" | ETA {eta_h:.1f}h" if eta_h is not None else ""))
        write_status(status="running", chunk=chunk_no, totals=totals,
                     settled=done_before + stats["attempted"], total=len(work),
                     overall_calls_per_s=round(rate, 2), eta_hours=round(eta_h, 2) if eta_h else None)

    elapsed = time.perf_counter() - t_start
    log(f"COMPLETE: {totals} in {elapsed/3600:.2f}h")
    write_status(status="complete", totals=totals, elapsed_hours=round(elapsed / 3600, 2),
                 total=len(work))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
