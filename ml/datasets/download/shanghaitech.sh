#!/usr/bin/env bash
# ShanghaiTech Campus (13 scenes, single view per scene, anomaly detection
# — used here for rule/event precision-recall per design_architecture.md §13).
#
# Source verified 27 Sep 2026: https://svip-lab.github.io/dataset/campus_dataset.html
# Only a OneDrive link resolves from that page (the Google Drive link on
# it is unpopulated/broken as of the same date):
# https://1drv.ms/u/s!AjjUqiJZsj8whLt-1ABerTT-9eH9Ag?e=eJbY6Y
#
# OneDrive share links don't support a reliable scripted download (unlike
# a plain HTTPS file URL), so this script does the best automatable
# attempt and falls back to clear manual instructions rather than pretend
# it always works unattended.
set -euo pipefail

OUT_DIR="${1:-ml/datasets/raw/shanghaitech}"
SHARE_URL="https://1drv.ms/u/s!AjjUqiJZsj8whLt-1ABerTT-9eH9Ag?e=eJbY6Y"

mkdir -p "$OUT_DIR"

echo "Attempting automated OneDrive download (may fail — OneDrive share"
echo "links aren't a stable scripted-download target)."
if curl -L --fail --progress-bar -o "$OUT_DIR/shanghaitech.zip" \
    "${SHARE_URL}&download=1" 2>/dev/null; then
  echo "Downloaded. Extracting..."
  unzip -q "$OUT_DIR/shanghaitech.zip" -d "$OUT_DIR"
  echo "Done: $OUT_DIR"
else
  cat <<EOF
Automated download failed (expected — OneDrive usually needs a browser).
Manual steps:
  1. Open: $SHARE_URL
  2. Download the archive through the browser UI.
  3. Move/extract it into: $OUT_DIR
EOF
  exit 1
fi

echo "Read ml/datasets/README.md for licence terms before using this data."
