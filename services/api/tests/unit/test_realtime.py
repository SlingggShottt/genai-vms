"""The WebSocket hub and message envelope (P3-J3) — in-memory, no database. The Redis relay is
tested against a real Redis in tests/integration/test_realtime_relay.py."""

from __future__ import annotations

import json

import pytest
from api.realtime.hub import ConnectionHub
from api.realtime.messages import WsMessage
from prometheus_client import REGISTRY
from pydantic import ValidationError


def msg(type_: str = "alert.created", **data: object) -> WsMessage:
    return WsMessage(type=type_, data=data or {"n": 1})


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


# --- the envelope --------------------------------------------------------------------------------


def test_the_envelope_has_type_data_and_a_utc_timestamp() -> None:
    wire = json.loads(msg("alert.updated", id="a1").to_json())
    assert set(wire) == {"type", "data", "ts"}
    assert wire["type"] == "alert.updated" and wire["data"] == {"id": "a1"}
    assert wire["ts"].endswith("Z") or "+00:00" in wire["ts"]


def test_the_envelope_round_trips_and_rejects_junk() -> None:
    original = msg("camera.status", camera="cam01", status="online")
    assert WsMessage.model_validate_json(original.to_json()) == original
    for bad in (
        '{"type": "", "data": {}}',
        '{"type": "x"}',
        '{"type": "x", "data": [], "ts": "2026-10-01T00:00:00Z"}',
        '{"type": "x", "data": {}, "ts": "2026-10-01T00:00:00"}',
        '{"type": "x", "data": {}, "extra": 1}',
        "not json",
    ):
        with pytest.raises(ValidationError):
            WsMessage.model_validate_json(bad)


# --- the hub -------------------------------------------------------------------------------------


async def test_a_broadcast_reaches_every_connection_whose_role_may_see_it() -> None:
    hub = ConnectionHub()
    admin, operator, viewer = hub.connect("admin"), hub.connect("operator"), hub.connect("viewer")
    assert hub.broadcast(msg("alert.created")) == 2  # a viewer sees no alert traffic
    assert admin.queue.qsize() == operator.queue.qsize() == 1 and viewer.queue.qsize() == 0
    assert hub.broadcast(msg("camera.status", camera="cam01")) == 3  # but everyone gets status
    assert viewer.queue.qsize() == 1
    assert json.loads(viewer.queue.get_nowait())["type"] == "camera.status"


async def test_a_message_of_an_unknown_type_reaches_nobody() -> None:
    hub = ConnectionHub()
    subscribers = [hub.connect(r) for r in ("admin", "operator", "viewer")]
    assert hub.broadcast(msg("something.new")) == 0
    assert all(s.queue.empty() for s in subscribers)


async def test_connections_are_counted_and_forgotten() -> None:
    hub = ConnectionHub()
    a, b = hub.connect("admin"), hub.connect("operator")
    assert hub.connection_count == 2
    assert sample("vms_api_ws_connections_count") == 2
    hub.disconnect(a)
    hub.disconnect(a)  # disconnecting twice is harmless
    assert hub.connection_count == 1 and hub.broadcast(msg("alert.created")) == 1
    hub.disconnect(b)
    assert hub.connection_count == 0 and hub.broadcast(msg("alert.created")) == 0


async def test_messages_arrive_in_order() -> None:
    hub = ConnectionHub()
    sub = hub.connect("operator")
    for i in range(5):
        hub.broadcast(msg("alert.updated", i=i))
    assert [json.loads(sub.queue.get_nowait())["data"]["i"] for i in range(5)] == [0, 1, 2, 3, 4]


async def test_a_client_that_falls_too_far_behind_is_dropped_not_buffered_forever() -> None:
    hub = ConnectionHub(queue_size=3)
    slow, fast = hub.connect("operator"), hub.connect("operator")
    dropped_before = sample("vms_api_ws_dropped_total")
    for i in range(3):
        hub.broadcast(msg("alert.updated", i=i))
        fast.queue.get_nowait()  # the fast client keeps up
    assert not slow.overflowed.is_set() and slow.queue.full()
    assert hub.broadcast(msg("alert.updated", i=3)) == 1  # slow's queue is full: only fast got it
    assert slow.overflowed.is_set()
    assert sample("vms_api_ws_dropped_total") == dropped_before + 1
    # once flagged it is skipped entirely, so one laggard never slows the others
    assert hub.broadcast(msg("alert.updated", i=4)) == 1
    assert fast.queue.qsize() == 2 and not fast.overflowed.is_set()


async def test_the_delivery_metric_counts_per_type() -> None:
    hub = ConnectionHub()
    hub.connect("operator")
    before = sample("vms_api_ws_messages_total", type="job.progress")
    hub.broadcast(msg("job.progress"))
    assert sample("vms_api_ws_messages_total", type="job.progress") == before + 1
