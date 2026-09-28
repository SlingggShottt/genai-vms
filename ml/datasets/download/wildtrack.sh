#!/usr/bin/env bash
# Downloads WILDTRACK full (7 synchronized HD cameras, dense pedestrian
# detection) from EPFL CVLab. No registration required.
#
# Source verified 27 Sep 2026:
# https://www.epfl.ch/labs/cvlab/data/data-wildtrack/
# Direct zip (dataset page's link, not a guess):
# http://documents.epfl.ch/groups/c/cv/cvlab-unit/www/data/Wildtrack/Wildtrack_dataset_full.zip
#
# If this 404s later (academic dataset pages move), re-check the page
# above and update this URL + the date in this comment.
set -euo pipefail

OUT_DIR="${1:-ml/datasets/raw/wildtrack}"
URL="http://documents.epfl.ch/groups/c/cv/cvlab-unit/www/data/Wildtrack/Wildtrack_dataset_full.zip"

mkdir -p "$OUT_DIR"
echo "Downloading WILDTRACK to $OUT_DIR (large file — check disk space first)."
curl -L --fail --progress-bar -o "$OUT_DIR/Wildtrack_dataset_full.zip" "$URL"

echo "Extracting..."
unzip -q "$OUT_DIR/Wildtrack_dataset_full.zip" -d "$OUT_DIR"

echo "Done: $OUT_DIR"
echo "Read ml/datasets/README.md for licence terms before using this data."
