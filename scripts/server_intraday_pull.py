#!/usr/bin/env python3
"""Remote, resumable worker for a frozen generic intraday manifest."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core import config  # noqa: E402
from src.research_data.pipelines import intraday  # noqa: E402
from src.research_data.sources.breeze import BreezeClient  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True,
                        help="directory containing frozen requests.parquet/json")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--min-interval", type=float, default=0.25)
    parser.add_argument("--max-calls", type=int)
    return parser.parse_args()


def write_status(root: Path, **values) -> None:
    values["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = root / "pull_status.json"
    tmp = root / ".pull_status.tmp"
    tmp.write_text(json.dumps(values, indent=2, sort_keys=True, default=str) + "\n")
    tmp.replace(path)


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    try:
        requests = intraday.load_request_manifest(root)
        code_hash = intraday.assert_acquisition_code(root)
    except Exception as exc:
        print(f"FATAL manifest: {type(exc).__name__}: {exc}", flush=True)
        return 2
    print(
        f"manifest={intraday.manifest_fingerprint(requests)} "
        f"code={code_hash} requests={len(requests):,} "
        f"interval={requests['interval'].iloc[0]}",
        flush=True)
    try:
        client = BreezeClient(
            config.load_credentials(), min_interval_s=args.min_interval,
            max_retries=4)
        client.authenticate()
    except Exception as exc:
        write_status(root, status="auth_failed", error=f"{type(exc).__name__}: {exc}")
        print(f"FATAL authentication: {type(exc).__name__}: {exc}", flush=True)
        return 3

    def progress(snapshot: dict) -> None:
        write_status(root, status="running", **snapshot)
        if snapshot["attempted"] % 100 == 0:
            print(json.dumps(snapshot, sort_keys=True), flush=True)

    try:
        totals = intraday.fetch_requests(
            requests, client, root, workers=max(1, args.workers),
            max_calls=args.max_calls, progress=progress)
    except Exception as exc:
        write_status(root, status="worker_failed",
                     error=f"{type(exc).__name__}: {exc}")
        print(f"FATAL worker: {type(exc).__name__}: {exc}", flush=True)
        return 4

    attempts = intraday.load_attempts(root)
    systemic = False
    if not attempts.empty:
        recent = attempts.sort_values("attempted_at").tail(100)
        systemic = len(recent) >= 20 and (~recent["status"].isin(["ok", "empty"])).mean() >= 0.90
    if totals.get("auth_failed"):
        status, code = "auth_failed", 3
    elif systemic:
        status, code = "systemic_errors", 5
    elif totals["remaining"]:
        status, code = "incomplete", 4
    else:
        status, code = "complete", 0
    write_status(root, status=status, totals=totals,
                 manifest_hash=intraday.manifest_fingerprint(requests),
                 acquisition_code_hash=code_hash)
    print(f"{status.upper()}: {json.dumps(totals, sort_keys=True)}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
