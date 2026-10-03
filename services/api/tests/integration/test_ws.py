"""`WS /api/v1/ws` against the real app, Postgres and Redis (P3-J3): authentication, role
filtering, token expiry, slow clients, and delivery across two api replicas. Run via
`make test-int`."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from api.main import create_app
from api.realtime.messages import WsMessage
from api.settings import ApiSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from vms_db.models import Alert

pytestmark = pytest.mark.integration

Headers = Callable[[str], dict[str, str]]
SeedAlert = Callable[..., Awaitable[Alert]]
URL = "/api/v1/ws"


def token(
    api_settings: ApiSettings,
    *,
    user_id: str,
    role: str = "operator",
    expires_in_s: float = 600,
    token_type: str = "access",  # noqa: S107 - a JWT claim, not a credential
    secret: str | None = None,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in_s),
    }
    return jwt.encode(
        payload, secret or api_settings.jwt.secret, algorithm=api_settings.jwt.algorithm
    )


def publish(client: TestClient, type_: str, **data: Any) -> None:
    """Publish through the app's own relay — from the thread the app runs in."""
    client.portal.call(client.app.state.relay.publish, WsMessage(type=type_, data=data or {"n": 1}))


def closes_with(client: TestClient, url: str) -> tuple[int, str]:
    """Connect and return the (code, reason) the server closes with."""
    with client.websocket_connect(url) as ws, pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_text()
    return closed.value.code, closed.value.reason


@pytest.fixture
def operator(make_user: Callable[[str], dict[str, str]]) -> dict[str, str]:
    return make_user("operator")


@pytest.fixture
def viewer(make_user: Callable[[str], dict[str, str]]) -> dict[str, str]:
    return make_user("viewer")


def connect(client: TestClient, tok: str):
    return client.websocket_connect(f"{URL}?token={tok}")


def settle(client: TestClient, connections: int = 1, wait_s: float = 5.0) -> None:
    """Wait until the relay is subscribed and `connections` sockets are registered with the hub
    (a socket is registered only after its token has been checked against the database)."""
    state = client.app.state
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if state.relay.ready.is_set() and state.hub.connection_count >= connections:
            return
        time.sleep(0.02)
    pytest.fail(
        f"not ready: relay={state.relay.ready.is_set()} sockets={state.hub.connection_count}"
    )


# --- authentication ------------------------------------------------------------------------------


def test_a_connection_without_a_token_is_closed_4401(client: TestClient) -> None:
    assert closes_with(client, URL) == (4401, "missing token")
    assert closes_with(client, f"{URL}?token=") == (4401, "missing token")


@pytest.mark.parametrize("junk", ["not-a-jwt", "a.b.c", "Bearer abc"])
def test_a_malformed_token_is_closed_4401(client: TestClient, junk: str) -> None:
    code, reason = closes_with(client, f"{URL}?token={junk}")
    assert (code, reason) == (4401, "invalid or expired token")


def test_a_token_signed_with_another_secret_is_refused(
    client: TestClient, operator: dict, api_settings: ApiSettings
) -> None:
    forged = token(
        api_settings, user_id=operator["id"], secret="another-secret-at-least-32-bytes-long"
    )
    assert closes_with(client, f"{URL}?token={forged}")[0] == 4401


def test_an_expired_token_is_refused(
    client: TestClient, operator: dict, api_settings: ApiSettings
) -> None:
    stale = token(api_settings, user_id=operator["id"], expires_in_s=-5)
    assert closes_with(client, f"{URL}?token={stale}")[0] == 4401


def test_a_refresh_token_is_not_an_access_token(
    client: TestClient, operator: dict, api_settings: ApiSettings
) -> None:
    refresh = token(api_settings, user_id=operator["id"], token_type="refresh")  # noqa: S106
    assert closes_with(client, f"{URL}?token={refresh}")[0] == 4401


def test_a_token_for_a_user_who_does_not_exist_is_refused(
    client: TestClient, api_settings: ApiSettings
) -> None:
    ghost = token(api_settings, user_id=str(uuid.uuid4()))
    assert closes_with(client, f"{URL}?token={ghost}") == (4401, "unknown or inactive user")


def test_a_token_whose_subject_is_not_a_uuid_is_refused(
    client: TestClient, api_settings: ApiSettings
) -> None:
    assert closes_with(client, f"{URL}?token={token(api_settings, user_id='alice')}")[0] == 4401


def test_a_deactivated_user_is_refused_even_with_a_valid_token(
    client: TestClient, operator: dict, admin_access_token: str, auth_headers: Headers
) -> None:
    patched = client.patch(
        f"/api/v1/users/{operator['id']}",
        json={"is_active": False},
        headers=auth_headers(admin_access_token),
    )
    assert patched.status_code == 200, patched.text
    assert closes_with(client, f"{URL}?token={operator['token']}") == (
        4401,
        "unknown or inactive user",
    )


# --- roles ---------------------------------------------------------------------------------------


def test_an_operator_receives_alerts_and_a_viewer_does_not(
    client: TestClient, operator: dict, viewer: dict
) -> None:
    with connect(client, operator["token"]) as op, connect(client, viewer["token"]) as vw:
        settle(client, 2)
        publish(client, "alert.created", id="a1")
        publish(client, "camera.status", camera="cam01", status="online")  # everyone's

        first_for_operator = op.receive_json()
        first_for_viewer = vw.receive_json()

    assert first_for_operator["type"] == "alert.created" and first_for_operator["data"] == {
        "id": "a1"
    }
    # Delivery is in order, so the viewer's *first* message being the status proves the alert was
    # never queued for them.
    assert first_for_viewer["type"] == "camera.status"


def test_what_each_role_may_see_follows_the_policy(
    client: TestClient, operator: dict, viewer: dict, admin_access_token: str
) -> None:
    sent = ["alert.created", "alert.updated", "camera.status", "job.progress", "incident.ready"]
    expect = {
        "admin": sent,
        "operator": sent,
        "viewer": ["camera.status", "incident.ready"],
    }
    tokens = {"admin": admin_access_token, "operator": operator["token"], "viewer": viewer["token"]}
    with (
        connect(client, tokens["admin"]) as admin_ws,
        connect(client, tokens["operator"]) as operator_ws,
        connect(client, tokens["viewer"]) as viewer_ws,
    ):
        settle(client, 3)
        for type_ in sent:
            publish(client, type_)
        publish(client, "camera.status", marker=True)  # end marker for everyone
        for role, ws in (("admin", admin_ws), ("operator", operator_ws), ("viewer", viewer_ws)):
            got = []
            while True:
                message = ws.receive_json()
                if message["data"].get("marker"):
                    break
                got.append(message["type"])
            assert got == expect[role], role


def test_a_message_type_the_policy_does_not_know_reaches_nobody(
    client: TestClient, operator: dict
) -> None:
    with connect(client, operator["token"]) as ws:
        settle(client)
        publish(client, "debug.dump")
        publish(client, "camera.status", marker=True)
        assert ws.receive_json()["data"] == {"marker": True}


def test_the_role_is_the_users_current_role_not_the_one_in_the_token(
    client: TestClient, viewer: dict, api_settings: ApiSettings
) -> None:
    claims_admin = token(api_settings, user_id=viewer["id"], role="admin")  # a lying claim
    with connect(client, claims_admin) as ws:
        settle(client)
        publish(client, "alert.created", id="secret")
        publish(client, "camera.status", marker=True)
        assert ws.receive_json()["type"] == "camera.status"  # still just a viewer


def test_a_role_change_takes_effect_on_the_next_connection(
    client: TestClient, viewer: dict, admin_access_token: str, auth_headers: Headers
) -> None:
    patched = client.patch(
        f"/api/v1/users/{viewer['id']}",
        json={"role": "operator"},
        headers=auth_headers(admin_access_token),
    )
    assert patched.status_code == 200, patched.text
    with connect(client, viewer["token"]) as ws:  # the same token, now an operator
        settle(client)
        publish(client, "alert.created", id="now-visible")
        assert ws.receive_json()["data"] == {"id": "now-visible"}


# --- messages ------------------------------------------------------------------------------------


def test_messages_carry_type_data_and_a_utc_timestamp_and_arrive_in_order(
    client: TestClient, operator: dict
) -> None:
    with connect(client, operator["token"]) as ws:
        settle(client)
        for n in range(20):
            publish(client, "job.progress", n=n)
        received = [ws.receive_json() for _ in range(20)]
    assert [m["data"]["n"] for m in received] == list(range(20))
    assert set(received[0]) == {"type", "data", "ts"}
    assert datetime.fromisoformat(received[0]["ts"]).utcoffset() == timedelta(0)


def test_text_the_client_sends_is_ignored(client: TestClient, operator: dict) -> None:
    with connect(client, operator["token"]) as ws:
        settle(client)
        ws.send_text("ping")
        ws.send_text(json.dumps({"type": "alert.created", "data": {"forged": True}}))
        publish(client, "alert.created", id="real")
        assert ws.receive_json()["data"] == {"id": "real"}  # nothing the client said came back


async def test_acknowledging_over_rest_reaches_the_dashboards_as_alert_updated(
    client: TestClient,
    operator: dict,
    viewer: dict,
    auth_headers: Headers,
    seed_alert: SeedAlert,
    unique_camera: str,
) -> None:
    alert = await seed_alert(camera=unique_camera)
    with connect(client, operator["token"]) as op, connect(client, viewer["token"]) as vw:
        settle(client, 2)
        done = client.post(
            f"/api/v1/alerts/{alert.id}/ack",
            json={"note": "checking"},
            headers=auth_headers(operator["token"]),
        )
        assert done.status_code == 200, done.text
        pushed = op.receive_json()
        publish(client, "camera.status", marker=True)
        assert vw.receive_json()["type"] == "camera.status"  # the viewer saw no alert traffic

    assert pushed["type"] == "alert.updated"
    assert pushed["data"]["id"] == str(alert.id) and pushed["data"]["status"] == "acknowledged"
    assert (
        pushed["data"]["ack_note"] == "checking"
        and pushed["data"]["acknowledged_by"] == operator["id"]
    )
    assert pushed["data"]["keyframe_urls"] == [] and pushed["data"]["keyframe_count"] == 2


# --- lifetime ------------------------------------------------------------------------------------


def test_the_connection_closes_when_the_token_expires(
    client: TestClient, operator: dict, api_settings: ApiSettings
) -> None:
    short = token(api_settings, user_id=operator["id"], expires_in_s=2)
    started = time.monotonic()
    code, reason = closes_with(client, f"{URL}?token={short}")
    elapsed = time.monotonic() - started
    assert (code, reason) == (4401, "token expired")
    assert 1.0 < elapsed < 5.0  # when the token ran out, not before, not much after


def test_a_client_that_falls_too_far_behind_is_dropped_with_1013(
    client: TestClient, operator: dict
) -> None:
    hub = client.app.state.hub
    with connect(client, operator["token"]) as ws:
        settle(client)
        assert hub.connection_count == 1

        def overflow() -> None:  # what `ConnectionHub.broadcast` does to a full queue
            for subscriber in hub._subscribers.values():
                subscriber.overflowed.set()

        client.portal.call(lambda: overflow())
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 1013


def test_a_closed_connection_is_forgotten_by_the_hub(client: TestClient, operator: dict) -> None:
    hub = client.app.state.hub
    with client.websocket_connect(f"{URL}?token={operator['token']}") as ws:
        settle(client)
        assert hub.connection_count == 1
        ws.close(1000)
        deadline = time.monotonic() + 3
        while hub.connection_count and time.monotonic() < deadline:
            time.sleep(0.02)
        assert hub.connection_count == 0  # gone because it left, not because the test ended


def test_many_clients_connect_and_all_hear_one_message(client: TestClient, operator: dict) -> None:
    with ExitStack() as stack:
        sockets = [stack.enter_context(connect(client, operator["token"])) for _ in range(5)]
        settle(client, 5)
        assert client.app.state.hub.connection_count == 5
        publish(client, "alert.created", id="all")
        assert [ws.receive_json()["data"] for ws in sockets] == [{"id": "all"}] * 5


# --- two api replicas ----------------------------------------------------------------------------


@pytest.fixture
def replica_b(api_settings: ApiSettings) -> Iterator[TestClient]:
    """A second api process: its own hub, its own relay, the same Redis and database."""
    app: FastAPI = create_app(api_settings)
    with TestClient(app) as second:
        yield second


def test_a_message_published_by_one_replica_reaches_clients_of_both(
    client: TestClient, replica_b: TestClient, operator: dict
) -> None:
    with connect(client, operator["token"]) as on_a, connect(replica_b, operator["token"]) as on_b:
        settle(client)
        settle(replica_b)
        publish(client, "alert.created", id="from-a")
        publish(replica_b, "alert.created", id="from-b")
        for ws in (on_a, on_b):
            heard = {ws.receive_json()["data"]["id"] for _ in range(2)}
            assert heard == {"from-a", "from-b"}  # each client heard both, wherever it is


async def test_an_acknowledgement_on_one_replica_updates_a_dashboard_on_the_other(
    client: TestClient,
    replica_b: TestClient,
    operator: dict,
    auth_headers: Headers,
    seed_alert: SeedAlert,
    unique_camera: str,
) -> None:
    alert = await seed_alert(camera=unique_camera)
    with connect(client, operator["token"]) as watcher_on_a:
        settle(client)
        acked = replica_b.post(  # the operator's request happens to land on replica B
            f"/api/v1/alerts/{alert.id}/ack", headers=auth_headers(operator["token"])
        )
        assert acked.status_code == 200, acked.text
        pushed = watcher_on_a.receive_json()
    assert pushed["type"] == "alert.updated" and pushed["data"]["status"] == "acknowledged"


def test_each_replica_delivers_a_message_exactly_once_not_per_publisher(
    client: TestClient, replica_b: TestClient, operator: dict
) -> None:
    with connect(client, operator["token"]) as on_a:
        settle(client)
        publish(replica_b, "alert.created", id="once")
        publish(client, "camera.status", marker=True)
        types = [on_a.receive_json()["type"], on_a.receive_json()["type"]]
    assert types == ["alert.created", "camera.status"]  # a duplicate would show up in between
