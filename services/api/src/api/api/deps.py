"""Request-scoped FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.session import session_scope


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped DB session; commits on success, rolls back on error."""
    async with session_scope(request.app.state.db_session_factory) as session:
        yield session
