#!/bin/sh
# Creates the buckets in docs/design_architecture.md §6.3. Idempotent
# (mc mb --ignore-existing) — run every `docker compose up`, no-ops once
# buckets exist. Runs inside the minio/mc image (compose service: minio-init).
set -eu

mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"

for bucket in vms-segments vms-keyframes vms-twins vms-crops vms-masks vms-evidence vms-reports vms-models; do
  mc mb --ignore-existing "local/$bucket"
  echo "bucket ready: $bucket"
done
