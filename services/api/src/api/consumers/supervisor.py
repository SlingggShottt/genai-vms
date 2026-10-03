"""Keep a Kafka consumer alive for the life of the api.

`BaseConsumer.run()` ends with an exception when Kafka is unreachable, the broker goes away or
the dead-letter send itself fails; the api must not lose alerts for the rest of its life because
of one such blip, nor refuse to start because Kafka is not up yet. So each consumer runs under
`supervise`, which restarts it with backoff until cancelled.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable

from vms_common.kafka.consumer import BaseConsumer
from vms_common.logging import get_logger

from api.cancellation import raise_if_cancelling

log = get_logger(__name__)

RESTART_BACKOFF_S: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0)
HEALTHY_AFTER_S = 30.0  # a consumer that ran this long was fine; the next failure starts at 1 s


async def supervise(
    name: str,
    make_consumer: Callable[[], BaseConsumer],
    *,
    backoff: tuple[float, ...] = RESTART_BACKOFF_S,
) -> None:
    """Run `make_consumer()` until cancelled, restarting it after any failure."""
    attempt = 0
    while True:
        consumer = make_consumer()
        started = time.monotonic()
        try:
            await consumer.start()
            log.info("consumer_started", consumer=name)
            await consumer.run()
            log.warning("consumer_stopped_unexpectedly", consumer=name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - restart is the whole job; the type is logged
            log.error("consumer_failed", consumer=name, error=type(exc).__name__)
        finally:
            with contextlib.suppress(Exception):
                await consumer.stop()
        # `run()` may have returned (cancel swallowed) or raised another error (cancel replaced):
        # either way a pending cancellation means stop, not restart.
        raise_if_cancelling()
        if time.monotonic() - started >= HEALTHY_AFTER_S:
            attempt = 0
        delay = backoff[min(attempt, len(backoff) - 1)]
        attempt += 1
        log.info("consumer_restarting", consumer=name, in_s=delay)
        await asyncio.sleep(delay)
