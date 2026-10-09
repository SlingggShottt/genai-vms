#!/usr/bin/env bash
# Run the cuts that `annotation-kit cut --script` wrote, N at a time (default 5). Each line skips
# itself when its clip exists. Failures are appended to cuts.failed next to the script.
# Needs `ffmpeg` on PATH (a wrapper that runs the one in a container does).
set -euo pipefail
script="${1:?usage: cut_parallel.sh cut_clips.sh [parallel]}"
jobs="${2:-5}"
dir="$(dirname "$script")"
grep '^mkdir' "$script" | sort -u | bash
grep '^\[ -s' "$script" | xargs -P "$jobs" -d '\n' -I{} bash -c '{} || echo "FAILED: {}" >> "'"$dir"'/cuts.failed"'
[ -e "$dir/cuts.failed" ] && { echo "some cuts failed: see $dir/cuts.failed"; exit 1; }
echo "all cuts done"
