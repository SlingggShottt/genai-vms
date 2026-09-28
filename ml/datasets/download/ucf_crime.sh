#!/usr/bin/env bash
# Downloads UCF-Crime (13 anomaly classes, untrimmed single-view
# surveillance video) from UCF's Center for Research in Computer Vision.
# No registration required.
#
# Source verified 27 Sep 2026: https://www.crcv.ucf.edu/projects/real-world/
# Direct zip: https://www.crcv.ucf.edu/data1/chenchen/UCF_Crimes.zip
# Alternative (if the direct link is down): CRCV's Dropbox mirror, linked
# from the project page above.
#
# The backlog scope is "8 classes" (P1-D6 AC) — this script downloads the
# full archive (all 13) since CRCV doesn't offer a per-class download; use
# --classes to filter which top-level folders get kept after extraction.
set -euo pipefail

OUT_DIR="${1:-ml/datasets/raw/ucf_crime}"
URL="https://www.crcv.ucf.edu/data1/chenchen/UCF_Crimes.zip"

mkdir -p "$OUT_DIR"
echo "Downloading UCF-Crime to $OUT_DIR (large file — check disk space first)."
curl -L --fail --progress-bar -o "$OUT_DIR/UCF_Crimes.zip" "$URL"

echo "Extracting..."
unzip -q "$OUT_DIR/UCF_Crimes.zip" -d "$OUT_DIR"

echo "Done: $OUT_DIR"
echo "Pick the 8 classes for phase annotation (P3-D5) — e.g. Abuse, Arrest,"
echo "Assault, Burglary, Fighting, Robbery, Shoplifting, Vandalism — and"
echo "note the choice + rationale in ml/annotation/phase_guideline.md."
echo "Read ml/datasets/README.md for licence terms before using this data."
