#!/usr/bin/env bash
# Creates the Kafka topics in docs/design_architecture.md §5.2 against the
# `infra` profile's broker. Idempotent (--if-not-exists). Invoked via
# `make topics` — requires `docker compose -f deploy/compose/docker-compose.yml
# --profile infra up -d kafka` (or the full infra profile) to be running first.
set -euo pipefail

COMPOSE_FILE="$(dirname "$0")/../docker-compose.yml"
# Compose reads `.env` from the compose file's directory, not the repo root, and
# even `exec` must interpolate the file's required variables — so pass the repo
# root `.env` (what .env.example tells you to create) explicitly.
ENV_FILE="${ENV_FILE:-$(dirname "$0")/../../../.env}"
ENV_ARGS=()
if [ -f "$ENV_FILE" ]; then ENV_ARGS=(--env-file "$ENV_FILE"); fi
EXEC=(docker compose ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} -f "$COMPOSE_FILE" exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092)

create_topic() {
  local name="$1" partitions="$2" retention_ms="$3"
  echo "creating topic: $name (partitions=$partitions, retention.ms=$retention_ms)"
  "${EXEC[@]}" --create --if-not-exists \
    --topic "$name" \
    --partitions "$partitions" \
    --replication-factor 1 \
    --config "retention.ms=$retention_ms"
}

# name                    partitions  retention
create_topic vms.segments.v1      6   86400000    # 24h
create_topic vms.twin.v1          6   259200000   # 72h
create_topic vms.events.v1        6   604800000   # 7d
create_topic vms.correlations.v1  3   604800000   # 7d
create_topic vms.incidents.v1     3   604800000   # 7d
create_topic vms.dlq.v1           1   1209600000  # 14d

echo "done. current topics:"
"${EXEC[@]}" --list
