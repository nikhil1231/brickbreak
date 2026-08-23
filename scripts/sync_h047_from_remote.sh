#!/usr/bin/env bash
# Merge remote H047 shards/manifest back into the local named data product.
set -eu
REMOTE="${1:-hp-ts}"
REMOTE_ROOT="${2:-~/brickbreak-h047}"
cd "$(dirname "$0")/.."
mkdir -p data/normalized/bulk_1515 data/metadata
rsync -az --stats "$REMOTE:$REMOTE_ROOT/data/normalized/bulk_1515/" \
  data/normalized/bulk_1515/
rsync -az "$REMOTE:$REMOTE_ROOT/data/metadata/bulk_1515_manifest.parquet" \
  data/metadata/
rsync -az "$REMOTE:$REMOTE_ROOT/data/normalized/bulk_1515_nifty_daily.parquet" \
  data/normalized/ 2>/dev/null || true
rsync -az "$REMOTE:$REMOTE_ROOT/data/metadata/h047_pull_status.json" \
  data/metadata/ 2>/dev/null || true
echo "H047 remote data synchronized from $REMOTE"
