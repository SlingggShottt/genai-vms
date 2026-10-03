"""The zone and camera-link JSON the frontend's tests use is what the api really sends (P3-J5).

Same idea as `test_frontend_fixtures.py` (P3-J4): the files under
`frontend/src/features/{zones,topology}/fixtures/` are built here from the real response models
(`ZoneOut`, `ZonesPage`, `TopologyEdgeOut`, `TopologyEdgesPage`) and compared with the committed
copies, so a change to the api's shape fails *this* test until the fixtures are regenerated, and
the frontend's own tests (zod against the same files) then fail if the UI no longer fits.
Regenerate:

    UPDATE_FRONTEND_FIXTURES=1 uv run pytest \
        services/api/tests/unit/test_frontend_fixtures_config.py
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from api.schemas import TopologyEdgeOut, TopologyEdgesPage, ZoneOut, ZonesPage
from vms_db.models import EdgeType, TopologyEdge, Zone, ZoneType

FRONTEND = Path(__file__).resolve().parents[4] / "frontend/src/features"

CREATED = datetime(2026, 10, 5, 9, 0, 0, tzinfo=UTC)
CAM1 = uuid.UUID("01929e6c-0002-7000-8000-000000000001")
CAM2 = uuid.UUID("01929e6c-0002-7000-8000-000000000002")
CAM3 = uuid.UUID("01929e6c-0002-7000-8000-000000000003")


def _zone(n: int, **over: object) -> Zone:
    fields: dict[str, object] = {
        "id": uuid.UUID(f"01929e6c-0001-7000-8000-00000000000{n}"),
        "camera_id": CAM1,
        "name": "Loading bay",
        "zone_type": ZoneType.GENERIC,
        "polygon": [[0.12, 0.3], [0.55, 0.28], [0.6, 0.8], [0.1, 0.85]],
        "schedule": None,
        "created_at": CREATED,
    }
    fields.update(over)
    return Zone(**fields)


def _edge(n: int, **over: object) -> TopologyEdge:
    fields: dict[str, object] = {
        "id": uuid.UUID(f"01929e6c-0003-7000-8000-00000000000{n}"),
        "from_camera_id": CAM1,
        "to_camera_id": CAM2,
        "edge_type": EdgeType.OVERLAP,
        "min_s": None,
        "max_s": None,
        "tolerance_s": 5.0,
        "bidirectional": True,
        "created_at": CREATED,
    }
    fields.update(over)
    return TopologyEdge(**fields)


def build() -> dict[str, object]:
    plain = ZoneOut.from_model(_zone(1))
    scheduled = ZoneOut.from_model(
        _zone(
            2,
            name="Staff yard",
            zone_type=ZoneType.RESTRICTED,
            polygon=[[0.5, 0.1], [0.9, 0.1], [0.9, 0.5]],
            schedule={
                "start_time": "22:00",
                "end_time": "06:00",
                "days": ["mon", "tue", "wed", "thu", "fri"],
            },
        )
    )
    overlap = TopologyEdgeOut.from_model(_edge(1))
    transit_one_way = TopologyEdgeOut.from_model(
        _edge(
            2,
            from_camera_id=CAM2,
            to_camera_id=CAM3,
            edge_type=EdgeType.TRANSIT,
            min_s=10.0,
            max_s=45.0,
            tolerance_s=None,
            bidirectional=False,
        )
    )
    transit_two_way = TopologyEdgeOut.from_model(
        _edge(
            3,
            from_camera_id=CAM1,
            to_camera_id=CAM3,
            edge_type=EdgeType.TRANSIT,
            min_s=20.5,
            max_s=90.0,
            tolerance_s=None,
            bidirectional=True,
        )
    )
    return {
        "zones/fixtures/zone.json": plain.model_dump(mode="json"),
        "zones/fixtures/zone_scheduled.json": scheduled.model_dump(mode="json"),
        "zones/fixtures/zones_page.json": ZonesPage(items=[plain, scheduled]).model_dump(
            mode="json"
        ),
        "topology/fixtures/edge_overlap.json": overlap.model_dump(mode="json"),
        "topology/fixtures/edge_transit.json": transit_one_way.model_dump(mode="json"),
        "topology/fixtures/edges_page.json": TopologyEdgesPage(
            items=[overlap, transit_one_way, transit_two_way]
        ).model_dump(mode="json"),
    }


@pytest.mark.parametrize("name", sorted(build()))
def test_the_committed_fixture_is_what_the_api_sends(name: str) -> None:
    expected = build()[name]
    path = FRONTEND / name
    if os.environ.get("UPDATE_FRONTEND_FIXTURES"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
    assert path.exists(), f"{name} missing: run with UPDATE_FRONTEND_FIXTURES=1"
    # Compared as data, not text: Prettier lays the file out its own way.
    assert json.loads(path.read_text()) == expected, (
        f"{name} no longer matches the api's response model; regenerate with "
        "UPDATE_FRONTEND_FIXTURES=1 and update the frontend if its tests then fail"
    )


def test_the_pages_round_trip_through_the_response_models() -> None:
    """The fixtures are also valid *input* to the models: nothing in them is shaped by hand."""
    zones = FRONTEND / "zones/fixtures/zones_page.json"
    edges = FRONTEND / "topology/fixtures/edges_page.json"
    if not (zones.exists() and edges.exists()):
        pytest.skip("fixtures not generated yet")
    zones_page = json.loads(zones.read_text())
    edges_page = json.loads(edges.read_text())
    assert ZonesPage.model_validate(zones_page).model_dump(mode="json") == zones_page
    assert TopologyEdgesPage.model_validate(edges_page).model_dump(mode="json") == edges_page
