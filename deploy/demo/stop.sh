#!/usr/bin/env bash
# Stops what deploy/demo/start.sh started (by process group, so `uv run` wrappers go too).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
for f in "$ROOT"/.demo/pids/*; do
  [ -e "$f" ] || continue
  name="$(basename "$f")"
  pid="$(cat "$f")"
  if kill -0 "$pid" 2>/dev/null; then
    kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null
    echo "stopped $name"
  fi
  rm -f "$f"
done
