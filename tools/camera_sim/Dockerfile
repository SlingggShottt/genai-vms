# camera_sim image — replays dataset videos as live RTSP streams (FR-ING-06).
#
# Build context is the REPO ROOT (see deploy/compose/docker-compose.yml:
# `build.context: ../..`), not this directory — uv needs the whole workspace
# visible to resolve the vms-common workspace dependency. This copies the
# full repo rather than a narrow file list for correctness; narrow it for
# faster rebuilds once that matters (.dockerignore already keeps datasets
# and other large/irrelevant paths out of the context).

FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app
COPY . /app

RUN uv sync --package vms-camera-sim --no-dev

ENTRYPOINT ["uv", "run", "--package", "vms-camera-sim", "camera-sim"]
CMD ["--manifest", "config/camera_sim.yaml"]
