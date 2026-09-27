# perception image — YOLO11 + ByteTrack + SigLIP2 + PyAV/OpenCV, GPU required.
#
# Build context is the REPO ROOT (see deploy/compose/docker-compose.yml:
# `build.context: ../..`) — uv needs the whole workspace visible to resolve
# the vms-common dependency. See tools/camera_sim/Dockerfile for the same
# pattern.
#
# Base image matches the exact torch build pinned in pyproject.toml
# (torch==2.6.0+cu124) — verified locally against a real RTX 3050, see
# adapters/*.py docstrings. Not yet built/run inside Docker itself (no
# Docker daemon in the environment this was written in) — verify the
# image actually builds and the container sees the GPU
# (`docker run --gpus all ... nvidia-smi`) before relying on it.

FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3.11 python3.11-venv python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app
COPY . /app

RUN uv sync --package vms-perception --no-dev

ENTRYPOINT ["uv", "run", "--package", "vms-perception", "python", "-m", "perception.main"]
