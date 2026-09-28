# correlation service image — placeholder.
#
# Completed when this service's backlog story lands (see docs/backlog.md
# and docs/design_architecture.md §4). Build pattern: uv-based Python 3.11
# image, non-root user, multi-stage (builder installs deps, runtime copies
# the synced venv + src/). See docs/techstack.md §9 for base image policy.

FROM python:3.11-slim AS base
WORKDIR /app

# TODO: install uv, copy pyproject.toml + uv.lock, `uv sync --frozen --no-dev`,
# copy src/, set non-root USER, set CMD/ENTRYPOINT.
