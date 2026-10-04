# api image — auth/RBAC, CRUD, recordings, alerts, search/assistant proxy, incidents, reports.
#
# Build context is the REPO ROOT (`build.context: ../..` in deploy/compose/docker-compose.yml):
# uv needs the whole workspace to resolve vms-common / vms-db. Same shape as the other services.

FROM python:3.11-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY . /app

RUN uv sync --package vms-api --no-dev

EXPOSE 8000
ENTRYPOINT ["uv", "run", "--package", "vms-api", "python", "-m", "api.main"]
