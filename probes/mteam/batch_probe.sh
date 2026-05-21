#!/usr/bin/env bash
# Batch run common M-Team API probes and save results to a timestamped directory.
#
# Usage:
#   bash probes/mteam/batch_probe.sh
#   bash probes/mteam/batch_probe.sh --keyword "沙丘" --torrent-id 1163290
#
# Requires: .venv with httpx and app config, valid MTEAM_* env vars or .env file.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="${ROOT_DIR}/probes/mteam/output_$(date +%Y%m%d_%H%M%S)"
PYTHON="${ROOT_DIR}/.venv/bin/python"
PROBE="${ROOT_DIR}/probes/mteam/api_probe.py"

KEYWORD="${1:-沙丘}"
TORRENT_ID="${2:-1163290}"
DOUBAN_CODE="${3:-1292052}"
IMDB_CODE="${4:-tt0111161}"

mkdir -p "$OUT_DIR"

echo "=== M-Team API batch probe ==="
echo "Output dir: $OUT_DIR"
echo "Keyword:   $KEYWORD"
echo "Torrent:   $TORRENT_ID"
echo "Douban:    $DOUBAN_CODE"
echo "IMDB:      $IMDB_CODE"
echo ""

run_probe() {
    local label="$1"
    shift
    local out_file="${OUT_DIR}/${label}.json"
    echo "[$(date +%H:%M:%S)] Running: $label"
    "$PYTHON" "$PROBE" --raw "$@" > "$out_file" 2>&1 || {
        echo "  -> FAILED (see ${out_file})"
        return 1
    }
    local size
    size=$(wc -c < "$out_file")
    echo "  -> OK (${size} bytes)"
}

run_probe "category-list"        category-list
run_probe "files"                files --id "$TORRENT_ID"
run_probe "media-info"           media-info --id "$TORRENT_ID"
run_probe "douban-elessar"       douban-elessar --code "$DOUBAN_CODE"
run_probe "douban-info"          douban-info --code "$DOUBAN_CODE"
run_probe "imdb-info"            imdb-info --code "$IMDB_CODE"
run_probe "search-basic"         search --keyword "$KEYWORD" --page-size 3
run_probe "search-sorted-size"   search --keyword "$KEYWORD" --page-size 3 --sort-field size --sort-direction desc
run_probe "search-sorted-seeders" search --keyword "$KEYWORD" --page-size 3 --sort-field seeders --sort-direction desc
run_probe "search-categories"    search --keyword "$KEYWORD" --page-size 3 --categories 419 421


echo ""
echo "All probe results saved to: $OUT_DIR"
echo ""
echo "Quick review:"
echo "  cat ${OUT_DIR}/category-list.json | python -m json.tool | head -60"
echo "  cat ${OUT_DIR}/search-basic.json | python -m json.tool | head -60"
