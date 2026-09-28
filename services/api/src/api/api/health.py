"""Liveness/readiness/metrics — every service exposes these three
(docs/design_architecture.md §15; CLAUDE.md commands).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from vms_common.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["ops"])


@router.get("/health")
async def health() -> dict:
    """Liveness: the process is up. No dependency checks."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict:
    """Readiness: dependencies (currently just Postgres) are reachable."""
    try:
        engine = request.app.state.db_engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        log.error("readiness_check_failed", error=str(exc))
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "checks": {"database": "down"}}
    return {"status": "ready", "checks": {"database": "up"}}


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
