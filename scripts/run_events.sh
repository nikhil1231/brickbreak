#!/usr/bin/env bash
# Supervisor for the overnight corporate-event pull. Mirrors run_pull.sh:
# restarts on transient crashes, stops immediately on the codes that mean
# "a human must intervene".
#   2 = NSE is not answering this host at all (preflight failed)
#   4 = a stage failed all its retries
#   5 = systemic block rate mid-run
# There is no token to expire here, so there is no equivalent of code 3.
set -u
cd "$(dirname "$0")/.." || exit 1
LOG="logs/events.log"
mkdir -p logs data/metadata
MAX_RESTARTS=5
n=0
while : ; do
  echo "=== supervisor: starting attempt $((n+1)) at $(date) ===" >> "$LOG"
  .venv/bin/python scripts/server_events.py "$@" >> "$LOG" 2>&1
  code=$?
  echo "=== supervisor: exited code=$code at $(date) ===" >> "$LOG"
  case $code in
    0) echo "=== supervisor: event pull complete ===" >> "$LOG"; break ;;
    2|5) echo "=== supervisor: needs human action (code $code), stopping ===" >> "$LOG"; break ;;
    *) n=$((n+1))
       if [ "$n" -ge "$MAX_RESTARTS" ]; then
         echo "=== supervisor: $MAX_RESTARTS restarts exhausted, stopping ===" >> "$LOG"; break
       fi
       echo "=== supervisor: restarting in 60s ===" >> "$LOG"; sleep 60 ;;
  esac
done
