#!/usr/bin/env bash
# Check the cut clips under a folder (one sub-folder per clip, one .mp4 per camera):
#   BAD  <file>          ffprobe cannot read it (a killed ffmpeg leaves a file with no index)
#   SHORT <folder> ...   the views of a clip differ in length by more than one frame, so a source
#                        video ended before the window did and the views no longer show the same span
# Prints nothing when everything is fine. Needs ffprobe on PATH.
set -uo pipefail
root="${1:?usage: check_clips.sh clips-dir}"
for dir in "$root"/*/; do
  summary=""
  min=""; max=""
  for f in "$dir"*.mp4; do
    # < /dev/null: a wrapper that runs ffprobe in a container would read our stdin
    n="$(ffprobe -v error -select_streams v:0 -count_packets -show_entries stream=nb_read_packets \
         -of csv=p=0 "$f" 2>/dev/null < /dev/null)"
    if [ -z "$n" ]; then echo "BAD $f"; continue; fi
    summary="$summary $(basename "$f" .mp4)=$n"
    if [ -z "$min" ] || [ "$n" -lt "$min" ]; then min="$n"; fi
    if [ -z "$max" ] || [ "$n" -gt "$max" ]; then max="$n"; fi
  done
  if [ -n "$min" ] && [ $((max - min)) -gt 1 ]; then echo "SHORT $(basename "$dir")$summary"; fi
done
