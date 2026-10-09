#!/usr/bin/env bash
# List every .mp4 under a folder that ffprobe cannot read (a killed ffmpeg leaves one with no index).
set -uo pipefail
find "${1:?usage: check_clips.sh clips-dir}" -name '*.mp4' | while read -r f; do
  d="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null)"
  [ -n "$d" ] || echo "BAD $f"
done
