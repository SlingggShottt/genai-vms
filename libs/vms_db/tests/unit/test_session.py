"""Unit tests for `session_scope`'s commit/rollback contract — a fake
session double, no real database (P1-J1; also exercises the path
`api.api.deps.get_session` now delegates to).
"""

from __future__ import annotations

import pytest
from vms_db.session import session_scope


class _FakeSession:
    """Stands in for `AsyncSession`: `session_scope` uses it as
    `async with session_factory() as session: ...`.
    """

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def _factory_for(session: _FakeSession):
    return lambda: session


@pytest.mark.asyncio
async def test_session_scope_commits_on_success() -> None:
    session = _FakeSession()
    async with session_scope(_factory_for(session)) as yielded:
        assert yielded is session

    assert session.committed is True
    assert session.rolled_back is False


@pytest.mark.asyncio
async def test_session_scope_rolls_back_and_reraises_on_error() -> None:
    session = _FakeSession()

    with pytest.raises(ValueError, match="boom"):
        async with session_scope(_factory_for(session)):
            raise ValueError("boom")

    assert session.committed is False
    assert session.rolled_back is True
