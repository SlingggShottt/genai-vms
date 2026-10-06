#!/usr/bin/env bash
# Re-records the demo footage on real MEVA clips and lets the rules + the VLM gate judge it, so
# search, events, alerts and playback have footage again. MinIO keeps segments and keyframes for
# one day (lifecycle rules), so run this the day of the demo, not days before.
#
#   deploy/demo/refresh.sh                 # about 45 min: 10 min replay, then the gate
#   DRY_RUN=1 deploy/demo/refresh.sh       # checks the preconditions and prints the plan, changes nothing
#   WITH_CAM01=1 deploy/demo/refresh.sh    # also replays the cam01 demo clip (not tried with four cameras)
#   make demo-refresh
#
# Environment:
#   REPLAY_SECONDS   how long the simulator plays (default 620: the clips are 10 min)
#   GATE_TIMEOUT     give up waiting for the gate after this many seconds (default 3600)
#   VMS_RETRIEVAL_ARCHIVE_SINCE   floor for search once the stack restarts (default: today 00:00 UTC)
#
# What it does, in the order the 4 GB GPU and 14 GB of RAM require:
#   1. stops retrieval and reasoning, unloads the language models;
#   2. enables the bus-station cameras (config/cameras.yaml and the API) and swaps in the MEVA
#      simulator manifest (ml/datasets/raw/meva/camera_sim.meva.yaml, gitignored);
#   3. starts perception FIRST, then the camera simulator, and waits for the clip to play;
#   4. stops the simulator, waits for perception and the indexer to drain, stops perception;
#   5. starts the events service so the gate has the whole GPU, and waits until every candidate
#      from this run has a decision (restarts Ollama if it dies, which it did under memory pressure);
#   6. stops the gate, restores the simulator manifest, disables the bus cameras again and brings
#      the demo stack back with deploy/demo/start.sh.
# Needs: `make up PROFILE=infra,core`, the host services from start.sh, the re-encoded clips in
# ml/datasets/raw/meva/sim/ (see ml/evaluation/results/meva-detection-run.md for how they are made).
# Results of the last run: that same file. MEVA video is research-only; do not publish it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
RUN="$ROOT/.demo"
mkdir -p "$RUN/logs" "$RUN/pids"

DRY_RUN="${DRY_RUN:-0}"
WITH_CAM01="${WITH_CAM01:-0}"
REPLAY_SECONDS="${REPLAY_SECONDS:-620}"
GATE_TIMEOUT="${GATE_TIMEOUT:-3600}"
MEVA_MANIFEST="ml/datasets/raw/meva/camera_sim.meva.yaml"
SIM_MANIFEST="config/camera_sim.yaml"
SIM_BACKUP="$RUN/camera_sim.yaml.before-refresh"
COMPOSE_CMD="docker compose --env-file .env -f deploy/compose/docker-compose.yml"
KAFKA_GROUPS="/opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group"
PY="$ROOT/.venv/bin/python"
OLLAMA_BIN="${OLLAMA_BIN:-$HOME/.local/ollama/bin/ollama}"

say() { printf '\n== %s\n' "$*"; }
die() { printf 'refresh: %s\n' "$*" >&2; exit 1; }

# Docker without a re-login: the docker group may not be active in a long-lived shell.
dksh() {
  if docker info >/dev/null 2>&1; then bash -c "$1"; else sg docker -c "$1"; fi
}
port_up() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
sql() { printf '%s\n' "$1" | dksh "docker exec -i vms-postgres psql -U vms -d vms -At"; }
lag() { dksh "docker exec vms-kafka $KAFKA_GROUPS $1 2>/dev/null" | awk 'NR>2 && $6 ~ /^[0-9]+$/ {s+=$6} END{print s+0}'; }

stop_group() { # name -> kill the process group a start.sh-style pid file points at
  local f="$RUN/pids/$1" pid pg me
  [ -f "$f" ] || return 0
  pid="$(cat "$f")"
  pg="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
  me="$(ps -o pgid= -p $$ | tr -d ' ')"
  if [ -n "$pg" ] && [ "$pg" != "$me" ]; then kill -- "-$pg" 2>/dev/null || true; fi
  rm -f "$f"
}

unload_models() {
  port_up 11434 || return 0
  for m in qwen2.5vl:3b qwen2.5:3b; do
    curl -s -m 20 -XPOST localhost:11434/api/generate -d "{\"model\":\"$m\",\"keep_alive\":0}" >/dev/null || true
  done
}

ensure_ollama() { # it exited once under memory pressure; the gate would publish held candidates as skipped
  port_up 11434 && return 0
  echo "  Ollama is down - restarting it"
  (cd "$(dirname "$OLLAMA_BIN")/.." && OLLAMA_HOST=0.0.0.0:11434 OLLAMA_MAX_LOADED_MODELS=1 \
    setsid nohup "$OLLAMA_BIN" serve >"$RUN/logs/ollama.log" 2>&1 </dev/null &)
  for _ in $(seq 1 20); do port_up 11434 && return 0; sleep 1; done
  echo "  Ollama did not come back" >&2
}

set_cameras() { # true|false -> bus-* cameras in config/cameras.yaml and in the API
  "$PY" - "$1" <<'EOF'
import re, sys
import httpx
from dotenv import dotenv_values

value = sys.argv[1]
path = "config/cameras.yaml"
out, current = [], None
for line in open(path).read().splitlines():
    m = re.match(r"\s*-\s*id:\s*(\S+)", line)
    if m:
        current = m.group(1)
    if current and current.startswith("bus-") and re.match(r"\s*enabled:", line):
        line = re.sub(r"enabled:.*", f"enabled: {value}", line)
    out.append(line)
open(path, "w").write("\n".join(out) + "\n")

env = dotenv_values(".env")
c = httpx.Client(base_url="http://localhost:8000/api/v1", timeout=20)
r = c.post("/auth/login", json={"email": env["VMS_ADMIN_EMAIL"], "password": env["VMS_ADMIN_PASSWORD"]})
r.raise_for_status()
c.headers["Authorization"] = "Bearer " + r.json()["access_token"]
for cam in c.get("/cameras", params={"limit": 100}).json()["items"]:
    if cam["code"].startswith("bus-"):
        c.patch(f"/cameras/{cam['id']}", json={"enabled": value == "true"}).raise_for_status()
        print(f"  {cam['code']}: enabled={value}")
EOF
}

# ---- preconditions (read-only) ---------------------------------------------------------------
say "Checking preconditions"
[ -f "$MEVA_MANIFEST" ] || die "$MEVA_MANIFEST is missing (the MEVA replay manifest; see ml/evaluation/results/meva-detection-run.md)"
while read -r f; do
  [ -f "$f" ] || die "replay clip $f is missing - re-create it as the results file describes"
done < <(sed -n 's/^ *file: *//p' "$MEVA_MANIFEST")
[ -f ml/datasets/demo/cam01_lite.mp4 ] || [ "$WITH_CAM01" != 1 ] || die "WITH_CAM01=1 but ml/datasets/demo/cam01_lite.mp4 is missing"
[ -x "$PY" ] || die "no .venv (run make setup)"
dksh "docker info >/dev/null" || die "docker is not usable"
for c in vms-kafka vms-postgres vms-minio vms-ingestion vms-indexer vms-mediamtx; do
  dksh "docker ps --format '{{.Names}}' | grep -qx $c" || die "container $c is not running (make up PROFILE=infra,core)"
done
port_up 8000 || die "the API is not up on :8000 (deploy/demo/start.sh)"
[ -x "$OLLAMA_BIN" ] || die "Ollama not found at $OLLAMA_BIN (set OLLAMA_BIN)"
free_gb="$(df -BG --output=avail / | tail -1 | tr -dc 0-9)"
[ "$free_gb" -ge 8 ] || die "only ${free_gb} GB free on / (need 8)"
backlog="$(sql "select count(*) from events.candidates c where c.end_ts > now() - interval '6 hours' and not exists (select 1 from events.events e where e.id = c.id)")"
echo "  ok: clips present, containers up, API up, ${free_gb} GB free"
echo "  undecided candidates from the last 6 h: $backlog (the gate judges high severity first, then oldest)"
[ "$backlog" -eq 0 ] || echo "  WARNING: they would be judged before this run's candidates; let the gate finish them or" \
  "set VMS_EVENTS_VERIFY_MAX_AGE_SECONDS lower for the events container"

if [ "$DRY_RUN" = 1 ]; then
  say "Dry run: nothing changed. The real run would do:"
  cat <<EOF
  1. stop retrieval and reasoning; unload the language models
  2. enable the bus-* cameras (cameras.yaml + API); use $MEVA_MANIFEST as $SIM_MANIFEST$( [ "$WITH_CAM01" = 1 ] && echo ' plus cam01')
  3. start perception, wait 70 s for ingestion to see the cameras, start vms-camera-sim, play ${REPLAY_SECONDS} s
  4. stop the simulator; wait for the perception and indexer consumer lag to reach 0 (now: perception=$(lag perception), indexer=$(lag indexer)); stop perception
  5. start vms-events (rules file: config/\${EVENTS_RULES_FILE:-rules.yaml}); wait until every candidate of the run is decided (timeout ${GATE_TIMEOUT} s)
  6. stop vms-events; restore $SIM_MANIFEST; disable the bus-* cameras; run deploy/demo/start.sh
EOF
  exit 0
fi

# ---- the run -----------------------------------------------------------------------------------
restore() {
  say "Restoring the configuration"
  dksh "docker stop vms-camera-sim >/dev/null 2>&1 || true"
  stop_group perception
  dksh "docker stop vms-events >/dev/null 2>&1 || true"
  if [ -f "$SIM_BACKUP" ]; then cp "$SIM_BACKUP" "$SIM_MANIFEST" && rm -f "$SIM_BACKUP"; fi
  set_cameras false || echo "  could not disable the bus cameras (API down?) - do it in the UI"
}
trap restore EXIT

say "1/6 Making room on the GPU and in RAM"
stop_group retrieval
stop_group reasoning
unload_models

say "2/6 Cameras and simulator manifest"
set_cameras true
[ -f "$SIM_BACKUP" ] || cp "$SIM_MANIFEST" "$SIM_BACKUP"
cp "$MEVA_MANIFEST" "$SIM_MANIFEST"
if [ "$WITH_CAM01" = 1 ]; then
  printf '  - id: cam01\n    file: ml/datasets/demo/cam01_lite.mp4\n    start_offset_s: 0.0\n' >>"$SIM_MANIFEST"
fi
T0="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "  run started $T0"

say "3/6 Perception first, then the simulator"
setsid nohup uv run --package vms-perception python -m perception.main >"$RUN/logs/perception.log" 2>&1 </dev/null &
echo $! >"$RUN/pids/perception"
for _ in $(seq 1 120); do
  grep -q "Setting newly assigned partitions" "$RUN/logs/perception.log" 2>/dev/null && break
  sleep 1
done
grep -q "Setting newly assigned partitions" "$RUN/logs/perception.log" || die "perception did not start (see $RUN/logs/perception.log)"
echo "  perception is consuming; waiting 70 s so ingestion picks up the cameras"
sleep 70
dksh "docker start vms-camera-sim >/dev/null" || dksh "COMPOSE_PROFILES=infra,tools $COMPOSE_CMD up -d --no-deps camera-sim"
echo "  simulator started; playing for ${REPLAY_SECONDS} s"
for s in $(seq 60 60 "$REPLAY_SECONDS"); do sleep 60; echo "  ${s}s: perception lag $(lag perception)"; done
sleep $((REPLAY_SECONDS % 60))

say "4/6 Draining"
dksh "docker stop vms-camera-sim >/dev/null"
zero=0
for _ in $(seq 1 60); do
  p="$(lag perception)"; i="$(lag indexer)"
  echo "  lag: perception=$p indexer=$i"
  if [ "$p" -eq 0 ] && [ "$i" -eq 0 ]; then zero=$((zero + 1)); else zero=0; fi
  [ "$zero" -ge 2 ] && break
  sleep 10
done
stop_group perception
sleep 5
echo "  perception stopped"

say "5/6 The gate (the whole GPU is free now)"
dksh "COMPOSE_PROFILES=infra,core $COMPOSE_CMD up -d --no-deps events" 2>&1 | tail -2
ensure_ollama
quiet=0
started=$SECONDS
while [ $((SECONDS - started)) -lt "$GATE_TIMEOUT" ]; do
  total="$(sql "select count(*) from events.candidates where created_at >= '$T0'")"
  left="$(sql "select count(*) from events.candidates c where c.created_at >= '$T0' and not exists (select 1 from events.events e where e.id = c.id)")"
  echo "  $((total - left))/$total candidates decided"
  if [ "$total" -gt 0 ] && [ "$left" -eq 0 ]; then quiet=$((quiet + 1)); else quiet=0; fi
  [ "$quiet" -ge 3 ] && break
  ensure_ollama
  sleep 20
done
[ "$quiet" -ge 3 ] || echo "  WARNING: stopped waiting after ${GATE_TIMEOUT} s with candidates still undecided"

say "Result"
sql "select c.camera_id, c.rule_id, count(*) as candidates, count(*) filter (where e.status = 'verified') as verified, count(*) filter (where e.status = 'rejected') as rejected, count(*) filter (where e.status = 'skipped') as skipped from events.candidates c left join events.events e on e.id = c.id where c.created_at >= '$T0' group by 1, 2 order by 1, 2" | column -s'|' -t || true
echo "  alerts raised: $(sql "select count(*) from core.alerts where created_at >= '$T0'")"
echo "  loitering alerts are usually noise in the waiting room; resolve them in the UI (Alerts) if they crowd the tray"

say "6/6 Back to the demo stack"
unload_models
trap - EXIT
restore
VMS_RETRIEVAL_ARCHIVE_SINCE="${VMS_RETRIEVAL_ARCHIVE_SINCE:-$(date -u +%F)T00:00:00Z}" "$ROOT/deploy/demo/start.sh"
