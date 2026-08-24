#!/usr/bin/env bash
# Remote supervisor. Usage: scripts/run_intraday_pull.sh /path/to/acquisition
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT_ARG="${1:?usage: $0 ACQUISITION_ROOT}"
mkdir -p "$ROOT_ARG" logs
LOG="logs/intraday_pull_$(basename "$ROOT_ARG").log"
MAX_RESTARTS=5
n=0
while :; do
  echo "=== starting attempt $((n+1)) at $(date -Is) ===" >> "$LOG"
  .venv/bin/python scripts/server_intraday_pull.py --root "$ROOT_ARG" >> "$LOG" 2>&1
  code=$?
  echo "=== exited code=$code at $(date -Is) ===" >> "$LOG"
  case "$code" in
    0) break ;;
    2|3|5) echo "=== human action required; stopping ===" >> "$LOG"; break ;;
    *) n=$((n+1))
       if [ "$n" -ge "$MAX_RESTARTS" ]; then
         echo "=== restart budget exhausted ===" >> "$LOG"; break
       fi
       sleep 60 ;;
  esac
done
exit "$code"
