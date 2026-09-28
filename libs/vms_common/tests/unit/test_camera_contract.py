"""Round-trip test for the cameras_internal fixture (style_guide.md §A.4)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from vms_common.contracts.camera import CamerasInternalResponse

FIXTURE = Path(__file__).parents[2] / "src" / "vms_common" / "fixtures" / "cameras_internal.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_cameras_internal_fixture_round_trips() -> None:
    raw = _load_fixture()

    response = CamerasInternalResponse.model_validate(raw)

    assert len(response.cameras) == 3
    assert response.cameras[0].code == "cam01"
    assert response.cameras[0].rtsp_url.startswith("rtsp://")
    assert response.cameras[2].enabled is False

    dumped = json.loads(response.model_dump_json())
    assert dumped["cameras"][0]["code"] == raw["cameras"][0]["code"]


def test_camera_internal_optional_fields_default_to_none() -> None:
    raw = _load_fixture()
    minimal = {
        "cameras": [
            {
                "id": "x",
                "code": "cam99",
                "name": "Minimal",
                "rtsp_url": "rtsp://mediamtx:8554/cam99",
                "site_id": raw["cameras"][0]["site_id"],
            }
        ]
    }

    response = CamerasInternalResponse.model_validate(minimal)

    assert response.cameras[0].enabled is True
    assert response.cameras[0].location_label is None


def test_cameras_internal_rejects_unknown_fields() -> None:
    raw = _load_fixture()
    raw["cameras"][0]["unexpected_field"] = "nope"

    with pytest.raises(ValidationError):
        CamerasInternalResponse.model_validate(raw)
