#!/usr/bin/env python3
"""Unattended bulk pull of NSE corporate-event data. Start it in tmux and leave.

Same shape as `server_pull.py`, and for the same reason: the result-filing
collector is per-symbol — NSE publishes no date-range form — so a full backfill
is roughly three requests per symbol plus one download per linked XBRL. Against
a ~2,000-symbol universe that is ~6,000 metadata requests and, historically,
north of 200,000 filings. At a polite throttle that is hours for the metadata
and days for the archive. It does not belong on a laptop that closes.

WHAT IS AND IS NOT WORTH OFFLOADING
  filings + xbrl   hours to days      offload this
  announcements    ~270 monthly requests, ~10 min   either
  deals            ~66 yearly requests, ~2 min      just run it locally

RESUMPTION IS FREE, AND THAT IS THE DESIGN
Every collector caches its raw payload on disk before parsing, keyed by the
request, and skips what it already holds. So this script has no checkpoint of
its own: killing it and restarting it resumes exactly where it stopped. The
status file exists to be read from another shell, not to drive recovery.

NO AUTH, ONE NEW FAILURE MODE
Unlike the Breeze pull there is no session token to expire, so the overnight
death that framework guards against cannot happen here. The failure that
replaces it is **blocking**: NSE is fronted by Akamai, and a datacenter IP is
judged more harshly than a residential one. The endpoints were verified from a
laptop; if the server's address is treated differently the symptom is a run
that fetches nothing while looking busy. So a sustained block is detected and
the run stops with a distinct exit code rather than grinding through the whole
universe writing empty files.

EXIT CODES (matching run_pull.sh's convention)
  0 complete   2 blocked at startup   4 a stage failed all retries
  5 systemic block rate mid-run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core import config                                        # noqa: E402
from src.research_data.sources import (                            # noqa: E402
    announcements, deals, filings, nse_api, xbrl,
)

STATUS = ROOT / "data" / "metadata" / "events_pull_status.json"

# NSE is unthrottled in the sense that it publishes no limit, and unforgiving
# in the sense that it answers a challenge page instead of a 429. 1.5s is the
# rate the collectors were verified at; the server has no reason to go faster.
THROTTLE = 1.5
XBRL_THROTTLE = 0.75
# A stage that blocks on this fraction of its requests is not unlucky.
SYSTEMIC_BLOCK_RATE = 0.5
MAX_STAGE_RETRIES = 3


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def write_status(**kw) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    kw["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATUS.write_text(json.dumps(kw, indent=2, default=str))


def preflight() -> bool:
    """One cheap request. If the server cannot reach NSE at all, say so now.

    A backfill that discovers this on request 6,000 has wasted two hours and
    left a directory of empty payloads that look like "no data for that
    symbol" rather than "we were blocked".
    """
    client = nse_api.Client(area="deals", throttle=THROTTLE, max_retries=2)
    today = date.today()
    try:
        df = deals.fetch_window(client, "bulk_deals",
                                today.replace(day=1), today, force=True)
    except nse_api.NSEBlocked as exc:
        log(f"PREFLIGHT FAILED: {exc}")
        log("NSE is not answering this host. A datacenter IP is judged more "
            "harshly than a residential one; try from the laptop, or via a "
            "residential egress.")
        return False
    log(f"preflight ok: {len(df):,} bulk deals month-to-date")
    return True


def universe(symbols_file: str | None = None) -> list[str]:
    """Symbols to fetch filings for, taken from the tape rather than a list.

    The traded universe is what the panel can join against; NSE's full listing
    includes symbols the bars never carried, and each one is three wasted
    requests.

    A pull server does not need the whole tape just to enumerate tickers, so
    `--symbols-file` accepts the list directly — one symbol per line, as
    written by `python -m src.cli ...` on the machine that holds the bars.
    Shipping a 134 MB parquet to answer a question whose answer is 30 KB is
    also a second copy of the panel to keep in step, which is worse.
    """
    if symbols_file:
        path = Path(symbols_file)
        if not path.exists():
            log(f"symbols file {path} not found")
            return []
        return sorted({line.strip().upper()
                       for line in path.read_text().splitlines() if line.strip()})

    import pandas as pd

    path = config.NORMALIZED_DIR / "daily_bars.parquet"
    if not path.exists():
        log("daily_bars.parquet missing and no --symbols-file given — "
            "either sync-nse here or hand over the symbol list")
        return []
    syms = pd.read_parquet(path, columns=["symbol"])["symbol"].dropna().unique()
    return sorted(str(s).upper() for s in syms)


def run_stage(name: str, fn, state: dict) -> bool:
    """Run one collector with retries, recording progress into `state`."""
    for attempt in range(1, MAX_STAGE_RETRIES + 1):
        log(f"--- {name} (attempt {attempt}/{MAX_STAGE_RETRIES}) ---")
        state["stage"] = name
        write_status(**state)
        try:
            result = fn()
        except nse_api.NSEBlocked as exc:
            log(f"{name}: blocked — {exc}")
            state.setdefault("errors", []).append({"stage": name, "error": str(exc)})
            time.sleep(30 * attempt)
            continue
        except Exception:
            log(f"{name}: unhandled error\n{traceback.format_exc()}")
            state.setdefault("errors", []).append(
                {"stage": name, "error": traceback.format_exc(limit=3)})
            time.sleep(30 * attempt)
            continue
        state.setdefault("stages", {})[name] = result
        write_status(**state)
        log(f"{name}: done — {json.dumps(result, default=str)[:300]}")
        return True
    log(f"{name}: failed after {MAX_STAGE_RETRIES} attempts")
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-deals", action="store_true")
    ap.add_argument("--skip-announcements", action="store_true")
    ap.add_argument("--skip-filings", action="store_true")
    ap.add_argument("--skip-xbrl", action="store_true",
                    help="fetch filing metadata but not the filings themselves")
    ap.add_argument("--limit-symbols", type=int, default=None,
                    help="cap the filing universe — for a smoke run")
    ap.add_argument("--xbrl-from", default="2018-01-01",
                    help="skip filings whose period ends before this when "
                         "archiving. NSE serves no XBRL for period ends before "
                         "2018-03-31 — 556 of 556 pre-2018 URLs 404'd when "
                         "measured, with no exceptions — so the default avoids "
                         "tens of thousands of requests whose answer is known. "
                         "Pass 1900-01-01 to attempt everything; "
                         "tests/test_event_endpoints_live.py fails if NSE ever "
                         "restores the old archive.")
    ap.add_argument("--symbols-file", default=None,
                    help="newline-delimited symbols for the filing stage; "
                         "avoids shipping the whole tape to a pull server")
    args = ap.parse_args(argv)

    started = datetime.now(timezone.utc).isoformat()
    state: dict = {"started_at": started, "status": "running", "stages": {}}
    write_status(**state)

    if not preflight():
        state["status"] = "blocked_at_startup"
        write_status(**state)
        return 2

    ok = True
    if ok and not args.skip_deals:
        ok = run_stage("deals", lambda: deals.sync(throttle=THROTTLE), state)
    if ok and not args.skip_announcements:
        ok = run_stage("announcements",
                       lambda: announcements.sync(throttle=THROTTLE), state)
    if ok and not args.skip_filings:
        syms = universe(args.symbols_file)
        if args.limit_symbols:
            syms = syms[:args.limit_symbols]
        log(f"filings: {len(syms):,} symbols (~{len(syms) * 3:,} requests)")
        ok = run_stage("filings",
                       lambda: filings.sync(syms, throttle=THROTTLE), state)
        if ok:
            failed = state["stages"]["filings"].get("failed", [])
            rate = len(failed) / max(len(syms) * 3, 1)
            if rate > SYSTEMIC_BLOCK_RATE:
                log(f"filings: {rate:.0%} of requests blocked — stopping")
                state["status"] = "systemic_block"
                write_status(**state)
                return 5

    if ok and not args.skip_xbrl:
        import pandas as pd

        df = filings.load()
        total = int(df["xbrl_url"].notna().sum())
        floor = pd.Timestamp(args.xbrl_from)
        df = df[df["period_end"] >= floor]
        rows = [{"filing_id": r.filing_id, "symbol": r.symbol, "url": r.xbrl_url}
                for r in df.itertuples() if isinstance(r.xbrl_url, str)]
        log(f"xbrl: {len(rows):,} linked filings from {floor.date()} onward "
            f"({total - len(rows):,} older ones skipped — NSE serves no XBRL "
            f"for them)")
        ok = run_stage(
            "xbrl",
            lambda: _archive_summary(xbrl.archive(rows, throttle=XBRL_THROTTLE)),
            state)

    state["status"] = "complete" if ok else "failed"
    state["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_status(**state)
    if not ok:
        return 4
    log("all stages complete. Sync down with scripts/sync_events_from_server.sh, "
        "then run `python -m src.cli build-events` locally.")
    return 0


def _archive_summary(manifest) -> dict:
    return {"rows": int(len(manifest)),
            "stored": int((manifest["status"] == "ok").sum()),
            "distinct_payloads": int(manifest["sha256"].nunique()),
            "bytes": int(manifest["n_bytes"].sum())}


if __name__ == "__main__":
    raise SystemExit(main())
