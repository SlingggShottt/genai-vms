# correlation image — event.v1 -> correlation groups -> correlation.v1 (P3-J2).
#
# Build context is the REPO ROOT (see deploy/compose/docker-compose.yml:
# `build.context: ../..`) — uv needs the whole workspace visible to resolve the
# vms-common/vms-db dependencies. Same shape as services/events/Dockerfile (a plain
# consumer: no GPU, no ffmpeg). `config/` is mounted read-only by Compose, so
# correlation.yaml / topology.yaml edits don't need an image rebuild.

FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY . /app

RUN uv sync --package vms-correlation --no-dev

ENTRYPOINT ["uv", "run", "--package", "vms-correlation", "correlation"]
