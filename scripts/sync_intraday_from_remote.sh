#!/usr/bin/env bash
# Pull immutable acquisition artifacts back from hp-ts, then verify the manifest.
set -euo pipefail
VERSION="${1:?usage: $0 DATASET_VERSION [REMOTE_ROOT]}"
REMOTE_ROOT="${2:-~/brickbreak/data/intraday_acquisition/$VERSION}"
LOCAL_ROOT="data/intraday_acquisition/$VERSION"
mkdir -p "$LOCAL_ROOT"
rsync -az --stats "hp-ts:$REMOTE_ROOT/" "$LOCAL_ROOT/"
.venv/bin/python - "$LOCAL_ROOT" <<'PY'
import sys
from pathlib import Path
from src.research_data.pipelines import intraday

root = Path(sys.argv[1])
requests = intraday.load_request_manifest(root)
report = intraday.verify_acquisition(root, require_complete=True)
print(f"verified manifest={intraday.manifest_fingerprint(requests)}")
print(" ".join(f"{key}={value:,}" for key, value in report.items()))
PY
