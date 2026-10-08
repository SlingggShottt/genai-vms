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
# Where systemd is available each one also gets its own systemd scope with OOMPolicy=continue.
# Without that, a process started from a VS Code terminal belongs to VS Code's scope, and when the
# kernel's out-of-memory killer takes one of them (Ollama's model runner is the usual one: 6 GB or
# more on the CPU), systemd stops the whole scope - VS Code and everything in it - with "Failed with
# result 'oom-kill'". In its own scope only the process that was killed is lost.
#
# Environment:
#   VMS_RETRIEVAL_ARCHIVE_SINCE   ISO time; footage older than this is not searched (recordings
#                                 the retention policy has removed). Unset = search everything.
#   VMS_OLLAMA_MEMORY_MAX         memory cap for Ollama's scope (default 8G; 0 = no cap). Its runner uses
#                                 6-7 GB on the CPU: a 6G cap killed it three times in 16 minutes
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
RUN="$ROOT/.demo"
mkdir -p "$RUN/logs" "$RUN/pids"

up() { # port -> 0 if something listens on it
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

ISOLATE=()
if command -v systemd-run >/dev/null 2>&1 && systemd-run --user --scope --quiet true 2>/dev/null; then
  ISOLATE=(systemd-run --user --scope --quiet -p OOMPolicy=continue)
fi

start() { # name port command...   (MEMORY_MAX=6G start ... caps the scope)
  local name="$1" port="$2" cap=()
  shift 2
  [ -n "${MEMORY_MAX:-}" ] && [ "${MEMORY_MAX}" != 0 ] && [ "${#ISOLATE[@]}" -gt 0 ] \
    && cap=(-p "MemoryMax=${MEMORY_MAX}")
  if [ -n "$port" ] && up "$port"; then
    echo "  $name already up on :$port"
    return
  fi
  # A service with no port (the reasoning worker) is "up" if its recorded process group lives.
  if [ -z "$port" ] && [ -f "$RUN/pids/$name" ] && kill -0 "$(cat "$RUN/pids/$name")" 2>/dev/null; then
    echo "  $name already running (pid $(cat "$RUN/pids/$name"))"
    return
  fi
  setsid nohup ${ISOLATE[@]+"${ISOLATE[@]}"} ${cap[@]+"${cap[@]}"} "$@" \
    >"$RUN/logs/$name.log" 2>&1 </dev/null &
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
  # The runner it spawns is the first thing the kernel should give up under memory pressure, so
  # raise its OOM score (allowed without privileges) and cap the scope.
  OLLAMA_HOST=0.0.0.0:11434 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NUM_PARALLEL=1 \
    MEMORY_MAX="${VMS_OLLAMA_MEMORY_MAX:-8G}" start ollama 11434 \
    bash -c 'echo 500 >/proc/self/oom_score_adj; exec "$@"' _ "$OLLAMA_BIN" serve
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
