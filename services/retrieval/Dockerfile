# retrieval image — text/image search, the assistant. SigLIP 2 runs on CPU here, so no GPU is
# needed; the image is large because the workspace pins the same torch build as perception
# (cu124 wheels). The Hugging Face cache is a volume (see Compose), so the model downloads once.
#
# Build context is the REPO ROOT (see deploy/compose/docker-compose.yml).

FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY . /app

# The torch wheel is ~2.5 GB: uv's default 30 s per request is too short on a slow link.
ENV UV_HTTP_TIMEOUT=900 UV_HTTP_RETRIES=8
RUN uv sync --package vms-retrieval --no-dev

EXPOSE 8010
ENTRYPOINT ["uv", "run", "--package", "vms-retrieval", "retrieval"]
