#!/usr/bin/env bash
# Pull the corporate-event archives down from the server. Safe to re-run:
# rsync only transfers what changed, so run it again after a pull completes.
#
# Only the RAW caches and the XBRL manifest come down. The normalized event
# tables are rebuilt locally with `python -m src.cli build-events`, because
# the availability timestamps depend on the local trading calendar and a
# table built against a staler tape would silently disagree with the panel.
set -eu
SERVER="${1:-user@server}"
cd "$(dirname "$0")/.."
mkdir -p data/raw/deals data/raw/announcements data/raw/filings data/raw/xbrl data/metadata

for d in deals announcements filings; do
  rsync -az --stats "$SERVER:~/brickbreak/data/raw/$d/" "data/raw/$d/" \
    | grep -E "Number of files transferred|Total file size" | sed "s/^/  $d: /"
done

# The XBRL archive is the large one — hundreds of thousands of small files.
# --info=progress2 keeps a multi-hour transfer legible.
rsync -az --info=progress2 "$SERVER:~/brickbreak/data/raw/xbrl/" data/raw/xbrl/
rsync -az "$SERVER:~/brickbreak/data/metadata/xbrl_manifest.parquet" data/metadata/ 2>/dev/null || true
rsync -az "$SERVER:~/brickbreak/data/metadata/events_pull_status.json" data/metadata/ 2>/dev/null || true

echo "local: $(find data/raw/xbrl -name '*.xml' | wc -l | tr -d ' ') filings archived, $(du -sh data/raw/xbrl | cut -f1)"
echo "next:  .venv/bin/python -m src.cli build-events"
