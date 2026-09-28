"""Async SQLAlchemy engine/session factory (style_guide.md §A.1: async all
the way — no blocking I/O inside `async def`).

Usage in a service's `main.py` / dependency wiring:

    engine = create_engine(settings.db)
    session_factory = create_session_factory(engine)
    async with session_scope(session_factory) as session:
        ...
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from vms_common.config import DatabaseSettings


def create_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Build the async engine. One per process; share it across requests."""
    return create_async_engine(
        settings.dsn,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        echo=settings.echo,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """One transaction per use: commit on success, roll back on error."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
