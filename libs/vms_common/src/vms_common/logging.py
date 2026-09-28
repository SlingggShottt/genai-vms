"""Structured JSON logging via structlog (style_guide.md §A.1).

Call `configure_logging()` once from each service's `main.py`, then get a
logger per module and log snake_case events with key-value context:

    log = get_logger(__name__)
    log.info("segment_indexed", segment_id=sid, tracks=n)

Use `bind_context(...)` to attach correlation ids (segment_id, event_id,
group_id, request_id — NFR-OBS-01) to every log call for the rest of the
current async task. Never log secrets, tokens, or full prompts containing
user data at INFO.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO", *, json: bool = True) -> None:
    """Configure structlog (+ stdlib logging) once per process."""
    level_no = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level_no)

    renderer = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a logger bound to `name` (conventionally `__name__`)."""
    return structlog.get_logger(name)


def bind_context(**kwargs: object) -> None:
    """Bind key-value context to every subsequent log call on this task."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear context bound by `bind_context` (call at the end of a request/message)."""
    structlog.contextvars.clear_contextvars()
