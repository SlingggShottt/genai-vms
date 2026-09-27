#!/usr/bin/env bash
# MEVA (Multiview Extended Video with Activities) — multi-camera synchronized
# activity dataset, used for correlation and multi-view phase reasoning.
# Free, no registration, via the AWS Public Dataset Program.
#
# Source verified 27 Sep 2026: https://registry.opendata.aws/mevadata/,
# https://mevadata.org. Bucket: mevadata-public-01 (~470-516 GB total across
# ~4000+ clips — do NOT sync the whole bucket). context.md open question #5
# and techstack.md §6 both flag this dataset needs a scoped subset; backlog.md
# P1-D6 caps it at <= 60 GB with >= 4 synchronized cameras.
#
# This script does NOT hardcode which "drop" (subdirectory) to sync — sizes
# and contents change as NIST/Kitware add data, and guessing wrong risks
# blowing the 60 GB budget or an incomplete subset. Instead:
#   1. `list`  — shows available top-level prefixes so you can pick.
#   2. `size <prefix>` — reports a prefix's total size before you commit to it.
#   3. `sync <prefix> [<prefix> ...]` — syncs the chosen prefix(es).
#
# Requires the AWS CLI (`aws`) — install: https://aws.amazon.com/cli/
set -euo pipefail

BUCKET="s3://mevadata-public-01"
OUT_DIR="ml/datasets/raw/meva"

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not found. Install it first: https://aws.amazon.com/cli/" >&2
  exit 1
fi

cmd="${1:-}"
shift || true

case "$cmd" in
  list)
    aws s3 ls "$BUCKET/" --no-sign-request
    ;;
  size)
    prefix="${1:?usage: meva.sh size <prefix>}"
    aws s3 ls "$BUCKET/$prefix" --no-sign-request --recursive --summarize \
      | tail -3
    ;;
  sync)
    if [ "$#" -eq 0 ]; then
      echo "usage: meva.sh sync <prefix> [<prefix> ...]" >&2
      echo "run 'meva.sh list' first to see available prefixes" >&2
      exit 1
    fi
    mkdir -p "$OUT_DIR"
    for prefix in "$@"; do
      echo "syncing $BUCKET/$prefix -> $OUT_DIR/$prefix"
      aws s3 sync "$BUCKET/$prefix" "$OUT_DIR/$prefix" --no-sign-request
    done
    echo "Done. Verify total size stayed <= 60 GB: du -sh $OUT_DIR"
    echo "Confirm the synced prefixes cover >= 4 synchronized cameras (same"
    echo "site/time window, different camera ids) before using for correlation."
    ;;
  *)
    echo "usage: meva.sh {list|size <prefix>|sync <prefix> [<prefix> ...]}" >&2
    echo "Read ml/datasets/README.md for licence terms before using this data." >&2
    exit 1
    ;;
esac
