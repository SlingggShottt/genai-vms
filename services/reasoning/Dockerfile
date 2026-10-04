# reasoning image — job worker (phase timeline, evidence, incident reports), daily reports, and
# the consumer that queues jobs for closed correlation groups. No GPU: every model call goes
# through the LLM gateway to Ollama (VMS_LLM_OLLAMA_URL).
#
# Build context is the REPO ROOT (see deploy/compose/docker-compose.yml). `config/` is mounted
# read-only by Compose (models.yaml, vqa_bank.yaml).

FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY . /app

RUN uv sync --package vms-reasoning --no-dev

ENTRYPOINT ["uv", "run", "--package", "vms-reasoning", "reasoning"]
