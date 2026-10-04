"""Rate limiting (NFR-SEC, P7-J5): a fixed one-minute window per client and endpoint group, kept
in Redis so every api replica shares it.

Applied as a dependency (`Depends(limit("search"))`) on the endpoints where a burst is costly:
login (password guessing), search and the assistant (each can occupy the GPU for a minute), and
the ones that queue analyses and reports. The client is the first address in `X-Forwarded-For`
(the api sits behind the frontend's nginx) or the socket's peer; a user behind a shared address
shares its allowance. If Redis cannot be reached the request is let through and logged: a limiter
must not be the reason the api is down."""

from __future__ import annotations

import time
from collections.abc import Callable, Coroutine
from typing import Any, Literal

from fastapi import Request, status
from vms_common.logging import get_logger

from api.api.errors import APIError

log = get_logger(__name__)

Group = Literal["login", "search", "assistant", "heavy"]
WINDOW_S = 60


def client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def allowance(request: Request, group: Group) -> int:
    cfg = request.app.state.settings.ratelimit
    return {
        "login": cfg.login_per_minute,
        "search": cfg.search_per_minute,
        "assistant": cfg.assistant_per_minute,
        "heavy": cfg.heavy_per_minute,
    }[group]


def limit(group: Group) -> Callable[[Request], Coroutine[Any, Any, None]]:
    async def dependency(request: Request) -> None:
        if not request.app.state.settings.ratelimit.enabled:
            return
        redis = getattr(request.app.state, "redis_client", None)
        if redis is None:
            return
        now = time.time()
        window = int(now // WINDOW_S)
        key = f"vms:rl:{group}:{client_key(request)}:{window}"
        try:
            used = await redis.incr(key)
            if used == 1:
                await redis.expire(key, WINDOW_S + 5)
        except Exception as exc:  # fail open
            log.warning("ratelimit_unavailable", error=str(exc))
            return
        if used > allowance(request, group):
            retry = max(1, int((window + 1) * WINDOW_S - now))
            raise APIError(
                "RATE_LIMITED",
                f"Too many requests. Try again in {retry} seconds.",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                details={"retry_after_s": retry},
                headers={"Retry-After": str(retry)},
            )

    return dependency
