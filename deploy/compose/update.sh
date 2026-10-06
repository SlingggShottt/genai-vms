#!/usr/bin/env bash
# Deploys an image tag on the cloud VM, or reports whether it is up. Run from the repo checkout
# on the VM (the deploy workflow does: `cd /opt/genai-vms && ./deploy/compose/update.sh <tag>`).
#
#   deploy/compose/update.sh 1.2.3        pull that tag, migrate, create topics, start
#   deploy/compose/update.sh --rollback   deploy the tag that was running before the last update
#   deploy/compose/update.sh --status     exit 0 only if every service is up (and healthy where it
#                                         has a health check) and the api answers
#
# Rolling back does NOT undo database migrations: a migration that dropped or changed a column
# stays done. Take a backup first (README.md, "Backups") when an update carries one.
#
# Environment: ENV_FILE (default <repo>/.env.prod), DEPLOY_STATE_DIR (default <repo>/.deploy).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
ENV_FILE="${ENV_FILE:-$ROOT/.env.prod}"
STATE="${DEPLOY_STATE_DIR:-$ROOT/.deploy}"

die() { echo "update.sh: $*" >&2; exit 1; }

compose() {
  docker compose --env-file "$ENV_FILE" \
    -f deploy/compose/docker-compose.yml -f deploy/compose/docker-compose.prod.yml "$@"
}

valid_tag() { [[ "$1" =~ ^[A-Za-z0-9._-]+$ ]]; }

# A service is fine when it is running and not unhealthy / still starting.
status() {
  [ -f "$STATE/tag" ] && export VMS_TAG="$(cat "$STATE/tag")"
  local rows bad
  rows="$(compose ps --all --format '{{.Service}} {{.State}} {{.Health}}')"
  [ -n "$rows" ] || die "no services found (is anything deployed?)"
  echo "$rows"
  bad="$(echo "$rows" | awk '$2 != "running" || ($3 != "" && $3 != "healthy") {print $1}')"
  [ -z "$bad" ] || die "not up: $(echo $bad)"
  compose exec -T api python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" \
    || die "the api does not answer on /health"
  echo "ok: ${VMS_TAG:-unknown tag} is up"
}

deploy() {
  local tag="$1"
  valid_tag "$tag" || die "tag may only contain letters, digits, . _ -"
  [ -f "$ENV_FILE" ] || die "$ENV_FILE not found - copy deploy/compose/.env.prod.example"
  export VMS_TAG="$tag"
  mkdir -p "$STATE"

  echo "== checking the configuration"
  compose config --quiet # stops here, naming the variable, if a required one is missing

  echo "== pulling $tag"
  compose pull --quiet

  echo "== starting the infrastructure"
  compose up -d --wait --wait-timeout 300 postgres kafka redis qdrant minio

  echo "== migrating the database"
  compose run --rm --no-deps --entrypoint uv api \
    run --package vms-db alembic -c libs/vms_db/alembic.ini upgrade head

  echo "== creating Kafka topics"
  ENV_FILE="$ENV_FILE" bash deploy/compose/scripts/create_topics.sh >/dev/null

  echo "== starting everything"
  compose up -d --remove-orphans --wait --wait-timeout 600

  # Only now is $tag "what is running": a failed update leaves the record of the last good one.
  if [ -f "$STATE/tag" ] && [ "$(cat "$STATE/tag")" != "$tag" ]; then
    cp "$STATE/tag" "$STATE/previous"
  fi
  echo "$tag" >"$STATE/tag"
  echo "== deployed $tag"
}

case "${1:-}" in
  --status) status ;;
  --rollback)
    [ -f "$STATE/previous" ] || die "no previous tag recorded"
    deploy "$(cat "$STATE/previous")"
    ;;
  "" | -h | --help) sed -n '2,13p' "${BASH_SOURCE[0]}"; exit 2 ;;
  -*) die "unknown option $1" ;;
  *) deploy "$1" ;;
esac
