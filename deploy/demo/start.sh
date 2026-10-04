#!/usr/bin/env bash
# Starts the host-side demo services: Ollama, retrieval (:8010), reasoning, api (:8000) and the
# Vite dev server (:5173). The Docker infrastructure and the core pipeline run separately:
#
#     make up PROFILE=infra,core,tools      # Kafka, Postgres, MinIO, ingestion, indexer, events, ...
#     deploy/demo/start.sh                   # this script
#
# Each service is started in its own session (so it outlives this shell), logs to
# .demo/logs/<name>.log and records its process group in .demo/pids/<name>. Re-running starts only
# what is not already up. Stop everything with deploy/demo/stop.sh.
#
# Environment:
#   VMS_RETRIEVAL_ARCHIVE_SINCE   ISO time; footage older than this is not searched (recordings
#                                 the retention policy has removed). Unset = search everything.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
RUN="$ROOT/.demo"
mkdir -p "$RUN/logs" "$RUN/pids"

up() { # port -> 0 if something listens on it
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

start() { # name port command...
  local name="$1" port="$2"
  shift 2
  if [ -n "$port" ] && up "$port"; then
    echo "  $name already up on :$port"
    return
  fi
  setsid nohup "$@" >"$RUN/logs/$name.log" 2>&1 </dev/null &
  echo $! >"$RUN/pids/$name"
  echo "  started $name (log: .demo/logs/$name.log)"
}

wait_for() { # name url seconds
  for _ in $(seq 1 "$3"); do
    curl -sf "$2" >/dev/null 2>&1 && { echo "  $1 is ready"; return; }
    sleep 1
  done
  echo "  $1 did not answer within $3 s - see .demo/logs/$1.log" >&2
}

echo "Starting host services from $ROOT"

OLLAMA_BIN="${OLLAMA_BIN:-$HOME/.local/ollama/bin/ollama}"
[ -x "$OLLAMA_BIN" ] || OLLAMA_BIN="$(command -v ollama || true)"
if [ -n "$OLLAMA_BIN" ]; then
  # 0.0.0.0 so the containers (events) can reach it; one model resident (4 GB GPU).
  OLLAMA_HOST=0.0.0.0:11434 OLLAMA_MAX_LOADED_MODELS=1 start ollama 11434 "$OLLAMA_BIN" serve
else
  echo "  ollama not found - the language-model steps will degrade (set OLLAMA_BIN)" >&2
fi

start retrieval 8010 uv run --package vms-retrieval python -m retrieval.main
start reasoning "" uv run --package vms-reasoning python -m reasoning.main
start api 8000 uv run --package vms-api python -m api.main
start vite 5173 bash -c "cd frontend && VMS_API_URL=http://localhost:8000 exec npx vite --port 5173 --host 127.0.0.1"

wait_for retrieval http://127.0.0.1:8010/ready 120
wait_for api http://127.0.0.1:8000/health 60
wait_for vite http://127.0.0.1:5173/ 30
echo "Open http://127.0.0.1:5173  (log in with the admin account from .env)"
