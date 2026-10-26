"""The search proxy's mapping of what the retrieval service answers (P4-J1)."""

from __future__ import annotations

import types

import httpx
import pytest
from api.api import search as search_module
from api.api.errors import APIError


def request_to(handler) -> types.SimpleNamespace:  # noqa: ANN001
    settings = types.SimpleNamespace(retrieval_url="http://retrieval", search_timeout_seconds=5.0)
    real = httpx.AsyncClient

    class Client(real):
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)

    search_module.httpx.AsyncClient = Client  # type: ignore[misc]
    return types.SimpleNamespace(
        app=types.SimpleNamespace(state=types.SimpleNamespace(settings=settings, s3=None))
    )


@pytest.fixture(autouse=True)
def restore_httpx():  # noqa: ANN201
    real = search_module.httpx.AsyncClient
    yield
    search_module.httpx.AsyncClient = real


async def test_a_frame_that_is_gone_is_a_404_with_the_reason_not_a_503() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"detail": "that result is no longer available; search again"}
        )

    user = types.SimpleNamespace(id="u1")
    with pytest.raises(APIError) as caught:
        await search_module._forward(request_to(handler), user, "/search/crop", json={})
    assert caught.value.status_code == 404
    assert caught.value.code == "NOT_FOUND" and "no longer available" in caught.value.message


async def test_a_retrieval_service_that_is_down_is_still_a_503() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    with pytest.raises(APIError) as caught:
        await search_module._forward(
            request_to(handler), types.SimpleNamespace(id="u"), "/search", json={}
        )
    assert caught.value.status_code == 503
