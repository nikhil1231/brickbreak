#!/usr/bin/env bash
# Supervisor for the overnight pull: restarts the fetcher on transient crashes,
# but stops immediately on the exit codes that mean "a human must intervene".
#   2 = auth failed at startup      3 = token expired mid-run
#   4 = a chunk failed all retries  5 = systemic error rate
set -u
cd "$(dirname "$0")/.." || exit 1
LOG="logs/pull.log"
mkdir -p logs data/metadata
MAX_RESTARTS=5
n=0
while : ; do
  echo "=== supervisor: starting attempt $((n+1)) at $(date) ===" >> "$LOG"
  .venv/bin/python scripts/server_pull.py >> "$LOG" 2>&1
  code=$?
  echo "=== supervisor: exited code=$code at $(date) ===" >> "$LOG"
  case $code in
    0) echo "=== supervisor: pull complete ===" >> "$LOG"; break ;;
    2|3|5) echo "=== supervisor: needs human action (code $code), stopping ===" >> "$LOG"; break ;;
    *) n=$((n+1))
       if [ "$n" -ge "$MAX_RESTARTS" ]; then
         echo "=== supervisor: $MAX_RESTARTS restarts exhausted, stopping ===" >> "$LOG"; break
       fi
       echo "=== supervisor: restarting in 60s ===" >> "$LOG"; sleep 60 ;;
  esac
done
