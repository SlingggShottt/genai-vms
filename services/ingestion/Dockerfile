# ingestion image — RTSP pull + segment + keyframes + segment.v1 (FR-ING-01…05).
#
# Build context is the REPO ROOT (see deploy/compose/docker-compose.yml:
# `build.context: ../..`) — uv needs the whole workspace visible to resolve
# the vms-common dependency. See tools/camera_sim/Dockerfile for the same
# pattern and its rationale.

FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app
COPY . /app

RUN uv sync --package vms-ingestion --no-dev

ENTRYPOINT ["uv", "run", "--package", "vms-ingestion", "ingestion"]
