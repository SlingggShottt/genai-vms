#!/usr/bin/env bash
# Label Studio for the organiser: serves the cut clips under $1/clips (default ~/vms-annotation) on :8090.
# Needs Label Studio installed (`uv venv ls-venv && uv pip install --python ls-venv/bin/python label-studio`
# in $1) and $1/ls-credentials with an email on line 1 and a password on line 2.
set -euo pipefail
here="${1:-$HOME/vms-annotation}"
export LABEL_STUDIO_BASE_DATA_DIR="$here/ls-data"
export LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true
export LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT="$here"
export LABEL_STUDIO_DISABLE_SIGNUP_WITHOUT_LINK=true
export LABEL_STUDIO_COLLECT_ANALYTICS=false
export LABEL_STUDIO_SENTRY_DSN=""
export LABEL_STUDIO_FRONTEND_SENTRY_DSN=""
export DJANGO_DB=sqlite
user="$(sed -n 1p "$here/ls-credentials")"
pass="$(sed -n 2p "$here/ls-credentials")"
exec "$here/ls-venv/bin/label-studio" start --port "${PORT:-8090}" --no-browser \
  --username "$user" --password "$pass"
