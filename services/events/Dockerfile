# events image — rule engine over twinready.v1 -> events.candidates (P3-D1), and the VLM
# verification gate: candidates -> events.events + event.v1 (P3-D4).
#
# Build context is the REPO ROOT (see deploy/compose/docker-compose.yml:
# `build.context: ../..`) — uv needs the whole workspace visible to resolve
# the vms-common/vms-db dependencies. Same shape as services/indexer/Dockerfile
# (a plain consumer: no GPU, no ffmpeg). `config/` is mounted read-only by
# Compose, so rules.yaml / zones.yaml edits don't need an image rebuild.

FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY . /app

RUN uv sync --package vms-events --no-dev

ENTRYPOINT ["uv", "run", "--package", "vms-events", "events"]
