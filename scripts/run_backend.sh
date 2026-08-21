#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${BRICKBREAK_PYTHON:-$repo_root/.venv/bin/python}"

if [[ ! -x "$python_bin" ]]; then
  echo "brickbreak Python is not executable: $python_bin" >&2
  echo "Create .venv or set BRICKBREAK_PYTHON to the project Python executable." >&2
  exit 1
fi

cd "$repo_root"
exec "$python_bin" -m src.cli serve "$@"
