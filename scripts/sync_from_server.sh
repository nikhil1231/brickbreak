#!/usr/bin/env bash
# Pull opening-tick data + manifest down from the server. Safe to re-run:
# rsync only transfers what changed, so run it again after a pull completes.
set -eu
SERVER="${1:-hp-ts}"
cd "$(dirname "$0")/.."
mkdir -p data/normalized/opening_1s data/metadata
rsync -az --stats "$SERVER:~/brickbreak/data/normalized/opening_1s/" data/normalized/opening_1s/ \
  | grep -E "Number of files transferred|Total file size"
rsync -az "$SERVER:~/brickbreak/data/metadata/opening_manifest.parquet" data/metadata/
rsync -az "$SERVER:~/brickbreak/data/metadata/pull_status.json" data/metadata/ 2>/dev/null || true
echo "local: $(ls data/normalized/opening_1s | wc -l | tr -d ' ') date files, $(du -sh data/normalized/opening_1s | cut -f1)"
