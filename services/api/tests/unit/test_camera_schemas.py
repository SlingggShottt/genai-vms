"""Unit tests for camera request schemas — RTSP URL validation (FR-CAM-01).
No I/O, no DB.
"""

from __future__ import annotations

import pytest
from api.schemas import CameraCreateRequest, CameraUpdateRequest
from pydantic import ValidationError

_VALID_CREATE_KWARGS = {
    "code": "cam01",
    "name": "North Gate",
    "rtsp_url": "rtsp://mediamtx:8554/cam01",
    "site_id": "rvce-campus",
}


def test_create_request_accepts_a_valid_rtsp_url() -> None:
    request = CameraCreateRequest(**_VALID_CREATE_KWARGS)
    assert request.rtsp_url == "rtsp://mediamtx:8554/cam01"


@pytest.mark.parametrize(
    "bad_url", ["http://mediamtx:8554/cam01", "not-a-url", "", "rtsp://", "rtsp:// has a space"]
)
def test_create_request_rejects_a_malformed_rtsp_url(bad_url: str) -> None:
    with pytest.raises(ValidationError):
        CameraCreateRequest(**{**_VALID_CREATE_KWARGS, "rtsp_url": bad_url})


def test_create_request_defaults_enabled_to_true() -> None:
    assert CameraCreateRequest(**_VALID_CREATE_KWARGS).enabled is True


def test_update_request_allows_omitting_rtsp_url() -> None:
    request = CameraUpdateRequest(name="Renamed")
    assert request.rtsp_url is None


def test_update_request_rejects_a_malformed_rtsp_url_when_given() -> None:
    with pytest.raises(ValidationError):
        CameraUpdateRequest(rtsp_url="not-a-url")


def test_update_request_allows_clearing_location_label_explicitly() -> None:
    request = CameraUpdateRequest(location_label=None)
    assert "location_label" in request.model_fields_set
    assert request.location_label is None
