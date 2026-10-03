"""A write is committed before its response is sent.

Found while driving the zone and camera-link editors (P3-J5) in a real browser: after saving a
link the UI refetched the list and sometimes got the old one back, which then stayed on screen
because nothing refetches twice. The api had answered "201 Created" while its transaction was
still uncommitted: `get_session` commits in the exit code of a `yield` dependency, and since
FastAPI 0.118 that code runs *after* the response is sent unless the dependency has
`scope="function"`. Test clients that call the app in-process wait for the whole call, so no
earlier test could see it; these drive the ASGI app directly and watch the order.

`SessionDep` (api.api.deps) is the fix. This file checks that it commits first, that a failing
commit is an error response rather than something after a success, and that no endpoint goes
round it.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Annotated

import api.api
import pytest
from api.api.deps import SessionDep, get_session
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession


class _Session:
    def __init__(self, log: list[str], commit_fails: bool) -> None:
        self._log = log
        self._commit_fails = commit_fails

    async def commit(self) -> None:
        await asyncio.sleep(0)  # a real commit awaits the database
        if self._commit_fails:
            raise RuntimeError("commit failed")
        self._log.append("commit")

    async def rollback(self) -> None:
        self._log.append("rollback")


class _Factory:
    """What `session_scope` calls: `factory()` is an async context manager yielding a session."""

    def __init__(self, log: list[str], commit_fails: bool = False) -> None:
        self._log = log
        self._commit_fails = commit_fails

    def __call__(self) -> _Factory:
        return self

    async def __aenter__(self) -> _Session:
        return _Session(self._log, self._commit_fails)

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _app(log: list[str], *, commit_fails: bool = False) -> FastAPI:
    app = FastAPI()
    app.state.db_session_factory = _Factory(log, commit_fails)

    @app.post("/with-session-dep")
    async def with_session_dep(session: SessionDep) -> dict[str, bool]:
        return {"ok": True}

    # What every endpoint used to do. Kept as a control: it proves the harness below can see a
    # commit that comes after the response, so a pass for `SessionDep` is not vacuous.
    @app.post("/with-bare-get-session")
    async def with_bare_get_session(
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict[str, bool]:
        return {"ok": True}

    return app


async def _post(app: FastAPI, path: str, log: list[str]) -> None:
    """POST `path` into the ASGI app; `log` gets "response:<status>" as the status line goes out."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "root_path": "",
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.start":
            log.append(f"response:{message['status']}")

    await app(scope, receive, send)


async def test_the_transaction_is_committed_before_the_response_is_sent() -> None:
    log: list[str] = []
    await _post(_app(log), "/with-session-dep", log)
    assert log == ["commit", "response:200"], (
        "the client must not be told a write succeeded before it is committed: a client that "
        "re-reads at once (a UI refetch) would see the old data"
    )


async def test_a_bare_get_session_dependency_commits_after_the_response() -> None:
    """The control. If this ever fails, FastAPI's default scope changed and `SessionDep` may be
    redundant — not a bug in the api, but worth knowing.
    """
    log: list[str] = []
    await _post(_app(log), "/with-bare-get-session", log)
    assert log == ["response:200", "commit"]


async def test_a_commit_that_fails_is_an_error_response_not_an_error_after_a_success() -> None:
    log: list[str] = []
    with pytest.raises(RuntimeError, match="commit failed"):
        await _post(_app(log, commit_fails=True), "/with-session-dep", log)
    # Rolled back, then a 500: the client never heard a 200 for a write that was not kept.
    assert log == ["rollback", "response:500"]


def test_no_endpoint_depends_on_get_session_directly() -> None:
    """Every endpoint uses `SessionDep`; a bare `Depends(get_session)` brings the race back."""
    api_dir = Path(api.api.__file__).parent
    offenders = sorted(
        path.name
        for path in api_dir.glob("*.py")
        if path.name != "deps.py" and re.search(r"Depends\(\s*get_session", path.read_text())
    )
    assert offenders == [], (
        f"{offenders} depend on get_session directly: it commits after the response is sent. "
        "Use `SessionDep` from api.api.deps."
    )
    assert any(
        "SessionDep" in path.read_text() for path in api_dir.glob("*.py") if path.name != "deps.py"
    ), "the guard above would pass vacuously: nothing uses SessionDep"
