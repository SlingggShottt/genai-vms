"""Make sure a cancelled long-running loop actually stops.

`task.cancel()` is a request, and a library the task is awaiting can lose it two ways:

- *swallow* it: a call returns normally although the task has a cancellation pending (seen with
  redis-py 8.1 on Python 3.11: a cancel that lands while `pubsub.subscribe()` is still
  connecting vanishes, and the loop then listens for ever);
- *replace* it: the library raises a different exception while unwinding — redis-py's
  `pubsub.__aexit__` raises `ConnectionError` closing a connection being torn down — and a retry
  loop that catches that error takes it for a lost connection, reconnects, and never ends.

Either way `Task.cancelling()` still counts the request. So a loop that waits or retries calls
`raise_if_cancelling()` once per turn, where a swallowed cancel would otherwise let it go round
again (the relay: inside its listen loop and first thing in its reconnect `except`; the
supervisor: after each consumer run, before it backs off and restarts).
"""

from __future__ import annotations

import asyncio


def raise_if_cancelling(cause: BaseException | None = None) -> None:
    """Raise `CancelledError` (chained to `cause`) if this task has a cancellation pending."""
    task = asyncio.current_task()
    if task is not None and task.cancelling() > 0:
        raise asyncio.CancelledError from cause
