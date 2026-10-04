"""Integration tests: topology edge CRUD (FR-CAM-04) and `GET /internal/v1/topology`
against real, migrated Postgres. Run via `make test-int`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import pytest
from fastapi.testclient import TestClient
from vms_common.contracts.topology import TopologyInternalResponse

pytestmark = pytest.mark.integration

Headers = Callable[[str], dict[str, str]]


def _create_camera(
    client: TestClient, headers: dict[str, str], *, site_id: str = "rvce-campus"
) -> dict[str, str]:
    code = f"cam-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/v1/cameras",
        json={
            "code": code,
            "name": f"Camera {code}",
            "rtsp_url": f"rtsp://mediamtx:8554/{code}",
            "site_id": site_id,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _cameras(client: TestClient, headers: dict[str, str], n: int = 2) -> list[dict[str, str]]:
    """`n` cameras on one fresh site (so tests never see each other's edges)."""
    site = f"site-{uuid.uuid4().hex[:8]}"
    return [_create_camera(client, headers, site_id=site) for _ in range(n)]


def _edge(a: dict, b: dict, **fields: object) -> dict[str, object]:
    body: dict[str, object] = {
        "from_camera_id": a["id"],
        "to_camera_id": b["id"],
        "edge_type": "transit",
        "min_s": 5,
        "max_s": 90,
    }
    return body | fields


def _post(client: TestClient, headers: dict, body: dict) -> object:
    return client.post("/api/v1/topology/edges", json=body, headers=headers)


def _error_code(response: object) -> str:
    return response.json()["error"]["code"]  # type: ignore[attr-defined]


@pytest.fixture
def admin(admin_access_token: str, auth_headers: Headers) -> dict[str, str]:
    return auth_headers(admin_access_token)


# --- the happy path ----------------------------------------------------------------------


def test_admin_can_create_list_update_and_delete_edges(client: TestClient, admin: dict) -> None:
    a, b, c = _cameras(client, admin, 3)

    overlap = _post(
        client, admin, {"from_camera_id": a["id"], "to_camera_id": b["id"], "edge_type": "overlap"}
    )
    assert overlap.status_code == 201, overlap.text
    o = overlap.json()
    assert (o["edge_type"], o["tolerance_s"], o["bidirectional"]) == ("overlap", 5.0, True)
    assert o["min_s"] is None and o["max_s"] is None
    assert (o["from_camera_id"], o["to_camera_id"]) == (a["id"], b["id"])  # UUIDs, not codes
    assert o["created_at"]

    transit = _post(client, admin, _edge(b, c, bidirectional=True))
    assert transit.status_code == 201, transit.text
    t = transit.json()
    assert (t["min_s"], t["max_s"], t["tolerance_s"], t["bidirectional"]) == (5.0, 90.0, None, True)

    everything = client.get("/api/v1/topology/edges", headers=admin).json()["items"]
    ours = [e for e in everything if e["id"] in {o["id"], t["id"]}]
    assert {e["id"] for e in ours} == {o["id"], t["id"]}

    touching_a = client.get(f"/api/v1/topology/edges?camera_id={a['id']}", headers=admin)
    assert [e["id"] for e in touching_a.json()["items"]] == [o["id"]]
    touching_b = client.get(f"/api/v1/topology/edges?camera_id={b['id']}", headers=admin)
    assert {e["id"] for e in touching_b.json()["items"]} == {o["id"], t["id"]}  # either end

    patched = client.patch(
        f"/api/v1/topology/edges/{t['id']}", json={"min_s": 10, "max_s": 45}, headers=admin
    )
    assert patched.status_code == 200, patched.text
    assert (patched.json()["min_s"], patched.json()["max_s"]) == (10.0, 45.0)
    assert patched.json()["bidirectional"] is True  # untouched fields keep their value

    retuned = client.patch(
        f"/api/v1/topology/edges/{o['id']}", json={"tolerance_s": 1.5}, headers=admin
    )
    assert retuned.json()["tolerance_s"] == 1.5

    assert (
        client.patch(f"/api/v1/topology/edges/{t['id']}", json={}, headers=admin).status_code == 200
    )

    assert client.delete(f"/api/v1/topology/edges/{t['id']}", headers=admin).status_code == 204
    after = client.get(f"/api/v1/topology/edges?camera_id={c['id']}", headers=admin)
    assert after.json()["items"] == []


def test_any_authenticated_role_can_read_but_only_admin_can_write(
    client: TestClient, admin: dict, auth_headers: Headers
) -> None:
    a, b = _cameras(client, admin)
    created = _post(client, admin, _edge(a, b)).json()
    for role in ("operator", "viewer"):
        email = f"{role}-{uuid.uuid4().hex[:8]}@example.com"
        client.post(
            "/api/v1/users",
            json={
                "email": email,
                "full_name": role,
                "password": "correct-horse-battery-1",
                "role": role,
            },
            headers=admin,
        )
        token = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery-1"}
        ).json()["access_token"]
        headers = auth_headers(token)
        assert client.get("/api/v1/topology/edges", headers=headers).status_code == 200
        assert _post(client, headers, _edge(a, b)).status_code == 403
        assert (
            client.patch(
                f"/api/v1/topology/edges/{created['id']}", json={"max_s": 80}, headers=headers
            ).status_code
            == 403
        )
        assert (
            client.delete(f"/api/v1/topology/edges/{created['id']}", headers=headers).status_code
            == 403
        )


def test_the_topology_api_requires_a_login(client: TestClient) -> None:
    assert client.get("/api/v1/topology/edges").status_code == 401
    assert client.post("/api/v1/topology/edges", json={}).status_code == 401


# --- validation --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"edge_type": "transit", "min_s": None, "max_s": None},  # no window
        {"edge_type": "transit", "min_s": 90, "max_s": 5},  # inverted
        {"edge_type": "transit", "tolerance_s": 3},  # tolerance on transit
        {"edge_type": "overlap", "min_s": 5, "max_s": 90},  # window on overlap
        {"edge_type": "overlap", "min_s": None, "max_s": None, "bidirectional": False},
        {"edge_type": "overlap", "min_s": None, "max_s": None, "tolerance_s": 99999},
        {"edge_type": "transit", "max_s": 999999},
        {"edge_type": "wormhole"},
    ],
)
def test_invalid_edges_are_400_with_the_error_envelope(
    client: TestClient, admin: dict, fields: dict
) -> None:
    a, b = _cameras(client, admin)
    response = _post(client, admin, _edge(a, b, **fields))
    assert response.status_code == 400, response.text
    assert _error_code(response) == "VALIDATION_ERROR"


def test_a_camera_cannot_link_to_itself_and_ids_must_be_uuids(
    client: TestClient, admin: dict
) -> None:
    (a,) = _cameras(client, admin, 1)
    assert _post(client, admin, _edge(a, a)).status_code == 400
    assert _post(client, admin, _edge(a, a) | {"to_camera_id": "cam01"}).status_code == 400
    bad_filter = client.get("/api/v1/topology/edges?camera_id=cam01", headers=admin)
    assert bad_filter.status_code == 400


def test_cameras_on_different_sites_cannot_be_linked(client: TestClient, admin: dict) -> None:
    a = _create_camera(client, admin, site_id=f"north-{uuid.uuid4().hex[:6]}")
    b = _create_camera(client, admin, site_id=f"south-{uuid.uuid4().hex[:6]}")
    response = _post(client, admin, _edge(a, b))
    assert response.status_code == 400
    assert "same site" in response.json()["error"]["message"]


def test_unknown_cameras_and_edges_are_404(client: TestClient, admin: dict) -> None:
    (a,) = _cameras(client, admin, 1)
    ghost = {"id": str(uuid.uuid4())}
    missing_to = _post(client, admin, _edge(a, ghost))
    assert missing_to.status_code == 404
    assert missing_to.json()["error"]["details"] == {"field": "to_camera_id"}
    missing_from = _post(client, admin, _edge(ghost, a))
    assert missing_from.status_code == 404
    assert missing_from.json()["error"]["details"] == {"field": "from_camera_id"}

    nowhere = str(uuid.uuid4())
    assert (
        client.patch(
            f"/api/v1/topology/edges/{nowhere}", json={"max_s": 5}, headers=admin
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v1/topology/edges/{nowhere}", headers=admin).status_code == 404
    assert client.delete("/api/v1/topology/edges/not-a-uuid", headers=admin).status_code == 400
    assert (
        client.patch("/api/v1/topology/edges/not-a-uuid", json={}, headers=admin).status_code == 400
    )


def test_a_patch_must_leave_a_valid_edge_of_its_type(client: TestClient, admin: dict) -> None:
    a, b = _cameras(client, admin)
    transit = _post(client, admin, _edge(a, b)).json()
    overlap = _post(
        client, admin, {"from_camera_id": b["id"], "to_camera_id": a["id"], "edge_type": "overlap"}
    ).json()

    def patch(edge: dict, body: dict) -> object:
        return client.patch(f"/api/v1/topology/edges/{edge['id']}", json=body, headers=admin)

    for edge, body in [
        (transit, {"min_s": 200}),  # past max_s
        (transit, {"max_s": 1}),  # below min_s
        (transit, {"min_s": None}),  # explicit null clears a required bound
        (transit, {"tolerance_s": 2}),
        (transit, {"bidirectional": None}),
        (overlap, {"min_s": 1, "max_s": 2}),
        (overlap, {"tolerance_s": None}),
        (overlap, {"bidirectional": False}),
        (transit, {"edge_type": "overlap"}),  # identity cannot change
        (transit, {"to_camera_id": a["id"]}),
    ]:
        response = patch(edge, body)
        assert response.status_code == 400, f"{body}: {response.text}"

    unchanged = client.get(f"/api/v1/topology/edges?camera_id={a['id']}", headers=admin).json()[
        "items"
    ]
    by_id = {e["id"]: e for e in unchanged}
    assert (by_id[transit["id"]]["min_s"], by_id[transit["id"]]["max_s"]) == (5.0, 90.0)
    assert by_id[overlap["id"]]["tolerance_s"] == 5.0


# --- conflicts ---------------------------------------------------------------------------


def test_duplicate_edges_are_409(client: TestClient, admin: dict) -> None:
    a, b = _cameras(client, admin)
    assert _post(client, admin, _edge(a, b)).status_code == 201
    again = _post(client, admin, _edge(a, b, min_s=1, max_s=2))
    assert again.status_code == 409
    assert _error_code(again) == "CONFLICT"

    o = {"from_camera_id": a["id"], "to_camera_id": b["id"], "edge_type": "overlap"}
    assert _post(client, admin, o).status_code == 201  # same pair, different type: fine
    assert _post(client, admin, o).status_code == 409


def test_overlap_is_symmetric_so_the_reverse_is_409(client: TestClient, admin: dict) -> None:
    a, b = _cameras(client, admin)
    assert (
        _post(
            client,
            admin,
            {"from_camera_id": a["id"], "to_camera_id": b["id"], "edge_type": "overlap"},
        ).status_code
        == 201
    )
    reverse = _post(
        client, admin, {"from_camera_id": b["id"], "to_camera_id": a["id"], "edge_type": "overlap"}
    )
    assert reverse.status_code == 409
    assert "symmetric" in reverse.json()["error"]["message"]


def test_transit_in_both_directions_needs_two_one_way_edges_not_a_duplicate(
    client: TestClient, admin: dict
) -> None:
    a, b = _cameras(client, admin)
    assert _post(client, admin, _edge(a, b)).status_code == 201
    assert _post(client, admin, _edge(b, a)).status_code == 201  # the opposite one-way edge
    c, d = _cameras(client, admin)
    assert _post(client, admin, _edge(c, d, bidirectional=True)).status_code == 201
    assert _post(client, admin, _edge(d, c)).status_code == 409  # already covered
    e, f = _cameras(client, admin)
    assert _post(client, admin, _edge(e, f)).status_code == 201
    assert (
        _post(client, admin, _edge(f, e, bidirectional=True)).status_code == 409
    )  # would duplicate


def test_making_an_edge_bidirectional_cannot_create_a_duplicate(
    client: TestClient, admin: dict
) -> None:
    a, b = _cameras(client, admin)
    forward = _post(client, admin, _edge(a, b)).json()
    assert _post(client, admin, _edge(b, a)).status_code == 201
    response = client.patch(
        f"/api/v1/topology/edges/{forward['id']}", json={"bidirectional": True}, headers=admin
    )
    assert response.status_code == 409, response.text


def _race(client: TestClient, admin: dict, bodies: list[dict]) -> list[int]:
    """POST all `bodies` at once from separate threads; the sorted status codes."""
    with ThreadPoolExecutor(max_workers=len(bodies)) as pool:
        return sorted(r.status_code for r in pool.map(partial(_post, client, admin), bodies))


def test_concurrent_creates_of_one_edge_yield_exactly_one_201_never_a_500(
    client: TestClient, admin: dict
) -> None:
    a, b = _cameras(client, admin)
    transit = _edge(a, b)
    assert _race(client, admin, [transit] * 8) == [201] + [409] * 7

    c, d = _cameras(client, admin)
    overlap = {"from_camera_id": c["id"], "to_camera_id": d["id"], "edge_type": "overlap"}
    assert _race(client, admin, [overlap] * 8) == [201] + [409] * 7


def test_concurrent_reverse_overlap_creates_cannot_both_win(
    client: TestClient, admin: dict
) -> None:
    a, b = _cameras(client, admin)
    forward = {"from_camera_id": a["id"], "to_camera_id": b["id"], "edge_type": "overlap"}
    reverse = {"from_camera_id": b["id"], "to_camera_id": a["id"], "edge_type": "overlap"}
    # the partial unique index on the unordered pair is what stops the loser
    assert _race(client, admin, [forward, reverse] * 4) == [201] + [409] * 7


# --- cascade -----------------------------------------------------------------------------


def test_deleting_a_camera_removes_its_edges(client: TestClient, admin: dict) -> None:
    a, b, c = _cameras(client, admin, 3)
    ab = _post(client, admin, _edge(a, b)).json()
    bc = _post(client, admin, _edge(b, c)).json()
    assert client.delete(f"/api/v1/cameras/{a['id']}", headers=admin).status_code == 204
    remaining = {
        e["id"] for e in client.get("/api/v1/topology/edges", headers=admin).json()["items"]
    }
    assert ab["id"] not in remaining
    assert bc["id"] in remaining


# --- GET /internal/v1/topology -----------------------------------------------------------


def test_the_internal_topology_needs_the_service_token(
    client: TestClient, admin_access_token: str, auth_headers: Headers
) -> None:
    assert client.get("/api/v1/internal/v1/topology").status_code == 401
    wrong = client.get("/api/v1/internal/v1/topology", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    as_user = client.get("/api/v1/internal/v1/topology", headers=auth_headers(admin_access_token))
    assert as_user.status_code == 401  # a user's JWT is not a service token


def test_the_internal_topology_reports_camera_codes_and_matches_the_contract(
    client: TestClient, admin: dict, service_token: str
) -> None:
    a, b, c = _cameras(client, admin, 3)
    ab = _post(
        client,
        admin,
        {
            "from_camera_id": a["id"],
            "to_camera_id": b["id"],
            "edge_type": "overlap",
            "tolerance_s": 2,
        },
    ).json()
    bc = _post(client, admin, _edge(b, c, min_s=7, max_s=70, bidirectional=True)).json()

    response = client.get(
        "/api/v1/internal/v1/topology", headers={"Authorization": f"Bearer {service_token}"}
    )
    assert response.status_code == 200, response.text
    graph = TopologyInternalResponse.model_validate(response.json())  # every edge is contract-valid
    by_id = {e.id: e for e in graph.edges}

    overlap = by_id[ab["id"]]
    assert (overlap.from_camera_id, overlap.to_camera_id) == (
        a["code"],
        b["code"],
    )  # codes, not UUIDs
    assert (overlap.edge_type, overlap.tolerance_s, overlap.bidirectional) == ("overlap", 2.0, True)
    transit = by_id[bc["id"]]
    assert (transit.from_camera_id, transit.to_camera_id) == (b["code"], c["code"])
    assert (transit.min_s, transit.max_s, transit.bidirectional) == (7.0, 70.0, True)
