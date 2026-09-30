# indexer image — idempotent Postgres writes from twinready.v1 (P2-J1).
#
# Build context is the REPO ROOT (see deploy/compose/docker-compose.yml:
# `build.context: ../..`) — uv needs the whole workspace visible to resolve
# the vms-common/vms-db dependencies. See services/ingestion/Dockerfile for
# the same pattern (indexer is a plain consumer, same shape, no GPU/ffmpeg).

FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY . /app

RUN uv sync --package vms-indexer --no-dev

ENTRYPOINT ["uv", "run", "--package", "vms-indexer", "indexer"]
