#!/usr/bin/env bash
# Runs the intraday pull on hp-ts inside tmux
set -euo pipefail
cd "$(dirname "$0")/.."
echo "Starting intraday pull inside tmux (simulated)..."
./.venv/bin/python scripts/server_intraday_pull.py
