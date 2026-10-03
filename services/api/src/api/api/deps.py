"""Request-scoped FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from vms_db.session import session_scope


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped DB session; commits on success, rolls back on error."""
    async with session_scope(request.app.state.db_session_factory) as session:
        yield session


# What endpoints should depend on, instead of `Depends(get_session)`.
#
# `scope="function"` makes the exit code above (the commit) run when the endpoint returns, *before*
# the response is sent. FastAPI's default scope runs it *after*: the client would hear "201 Created"
# while the transaction was still uncommitted, so a UI that refetches the list at once could read
# the old one (seen as a stale list that never refreshed), and a commit that failed would follow a
# success response nobody could take back. Here a failed commit is an error response instead.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
