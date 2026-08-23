#!/usr/bin/env bash
# Remote tmux supervisor for the resumable H047 Breeze pull.
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs data/metadata
LOG="logs/h047_pull.log"
MAX_RESTARTS=3
n=0
while : ; do
  echo "=== supervisor: starting attempt $((n+1)) at $(date) ===" >> "$LOG"
  .venv/bin/python scripts/server_h047_pull.py >> "$LOG" 2>&1
  code=$?
  echo "=== supervisor: exited code=$code at $(date) ===" >> "$LOG"
  case $code in
    0) echo "=== supervisor: pull complete ===" >> "$LOG"; break ;;
    2|5) echo "=== supervisor: needs human action (code $code) ===" >> "$LOG"; break ;;
    *) n=$((n+1))
       if [ "$n" -ge "$MAX_RESTARTS" ]; then
         echo "=== supervisor: retries exhausted ===" >> "$LOG"; break
       fi
       echo "=== supervisor: restarting in 30s ===" >> "$LOG"; sleep 30 ;;
  esac
done
