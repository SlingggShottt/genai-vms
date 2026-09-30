"""Integration tests: recordings segments/playlist/density and twin frame
overlays (P2-J3) against real, migrated Postgres + MinIO. Run via
`make test-int`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from vms_common.contracts.twin import Frame, FrameObject, FrameSize, TwinV1
from vms_common.storage.s3 import S3Client
from vms_db.models import MinuteCount, Segment

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC)


def _unique_code() -> str:
    return f"cam-{uuid.uuid4().hex[:8]}"


async def _create_camera(client: TestClient, headers: dict[str, str]) -> str:
    code = _unique_code()
    resp = client.post(
        "/api/v1/cameras",
        json={
            "code": code,
            "name": "Test Camera",
            "rtsp_url": "rtsp://mediamtx:8554/" + code,
            "site_id": "rvce-campus",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return code


async def _seed_segments(
    session_factory: async_sessionmaker, *, camera_id: str, segments: list[Segment]
) -> None:
    async with session_factory() as session:
        for seg in segments:
            session.add(seg)
        await session.commit()


def _segment(
    camera_id: str, offset_s: int, duration_s: int = 10, twin_uri: str | None = None
) -> Segment:
    start = T0 + timedelta(seconds=offset_s)
    segment_id = f"{camera_id}_{offset_s}"
    return Segment(
        segment_id=segment_id,
        camera_id=camera_id,
        site_id="rvce-campus",
        start_ts=start,
        end_ts=start + timedelta(seconds=duration_s),
        uri=f"s3://vms-segments/{camera_id}/{segment_id}.ts",
        twin_uri=twin_uri or f"s3://vms-twins/{camera_id}/{segment_id}.json",
        perception_version="test@0.0.0",
    )


@pytest.fixture
async def camera_code(
    client: TestClient,
    auth_headers: Callable[[str], dict[str, str]],
    admin_access_token: str,
) -> str:
    return await _create_camera(client, auth_headers(admin_access_token))


async def test_segments_endpoint_reports_a_gap_between_two_segments(
    client: TestClient,
    auth_headers: Callable[[str], dict[str, str]],
    admin_access_token: str,
    db_session_factory: async_sessionmaker,
    camera_code: str,
) -> None:
    headers = auth_headers(admin_access_token)
    seg_a = _segment(camera_code, 0)
    seg_b = _segment(camera_code, 30)  # 20s gap after seg_a ends at offset 10
    await _seed_segments(db_session_factory, camera_id=camera_code, segments=[seg_a, seg_b])

    start = T0.isoformat()
    # seg_a covers [0,10), seg_b covers [30,40) -> interior gap [10,30) and,
    # with the range extended to 50s, a trailing gap [40,50) too.
    end = (T0 + timedelta(seconds=50)).isoformat()
    resp = client.get(
        f"/api/v1/recordings/{camera_code}/segments",
        params={"start": start, "end": end},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]

    assert [i["type"] for i in items] == ["segment", "gap", "segment", "gap"]
    assert items[0]["segment_id"] == seg_a.segment_id
    assert items[0]["uri"].startswith("http")  # presigned
    assert items[2]["segment_id"] == seg_b.segment_id


async def test_segments_endpoint_404s_for_an_unknown_camera(
    client: TestClient, auth_headers: Callable[[str], dict[str, str]], admin_access_token: str
) -> None:
    headers = auth_headers(admin_access_token)
    resp = client.get(
        "/api/v1/recordings/does-not-exist/segments",
        params={"start": T0.isoformat(), "end": (T0 + timedelta(seconds=10)).isoformat()},
        headers=headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


async def test_segments_endpoint_rejects_end_before_start(
    client: TestClient,
    auth_headers: Callable[[str], dict[str, str]],
    admin_access_token: str,
    camera_code: str,
) -> None:
    headers = auth_headers(admin_access_token)
    resp = client.get(
        f"/api/v1/recordings/{camera_code}/segments",
        params={"start": T0.isoformat(), "end": (T0 - timedelta(seconds=1)).isoformat()},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_playlist_endpoint_returns_valid_hls_with_a_discontinuity(
    client: TestClient,
    auth_headers: Callable[[str], dict[str, str]],
    admin_access_token: str,
    db_session_factory: async_sessionmaker,
    camera_code: str,
) -> None:
    headers = auth_headers(admin_access_token)
    seg_a = _segment(camera_code, 0)
    seg_b = _segment(camera_code, 30)
    await _seed_segments(db_session_factory, camera_id=camera_code, segments=[seg_a, seg_b])

    resp = client.get(
        f"/api/v1/recordings/{camera_code}/playlist.m3u8",
        params={"start": T0.isoformat(), "end": (T0 + timedelta(seconds=40)).isoformat()},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    body = resp.text
    assert body.startswith("#EXTM3U")
    assert body.count("#EXT-X-DISCONTINUITY") == 1
    assert body.count("#EXT-X-PROGRAM-DATE-TIME:") == 2
    assert body.strip().endswith("#EXT-X-ENDLIST")


async def test_density_endpoint_buckets_minute_counts(
    client: TestClient,
    auth_headers: Callable[[str], dict[str, str]],
    admin_access_token: str,
    db_session_factory: async_sessionmaker,
    camera_code: str,
) -> None:
    headers = auth_headers(admin_access_token)
    async with db_session_factory() as session:
        session.add_all(
            [
                MinuteCount(
                    camera_id=camera_code,
                    category="person",
                    minute_ts=T0,
                    site_id="rvce-campus",
                    count=3,
                ),
                MinuteCount(
                    camera_id=camera_code,
                    category="car",
                    minute_ts=T0,
                    site_id="rvce-campus",
                    count=1,
                ),
                MinuteCount(
                    camera_id=camera_code,
                    category="person",
                    minute_ts=T0 + timedelta(minutes=1),
                    site_id="rvce-campus",
                    count=2,
                ),
            ]
        )
        await session.commit()

    resp = client.get(
        f"/api/v1/recordings/{camera_code}/density",
        params={
            "start": T0.isoformat(),
            "end": (T0 + timedelta(minutes=2)).isoformat(),
            "bucket": 60,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [b["count"] for b in body["buckets"]] == [4, 2]


async def test_twin_frames_endpoint_returns_overlay_ready_bboxes(
    client: TestClient,
    auth_headers: Callable[[str], dict[str, str]],
    admin_access_token: str,
    db_session_factory: async_sessionmaker,
    s3_client: S3Client,
    camera_code: str,
) -> None:
    headers = auth_headers(admin_access_token)
    seg = _segment(camera_code, 0)
    await _seed_segments(db_session_factory, camera_id=camera_code, segments=[seg])

    twin = TwinV1(
        segment_id=seg.segment_id,
        camera_id=camera_code,
        site_id="rvce-campus",
        start_ts=seg.start_ts,
        end_ts=seg.end_ts,
        sample_fps=2.0,
        frame_size=FrameSize(w=1920, h=1080),
        frames=[
            Frame(
                ts=T0 + timedelta(seconds=1),
                idx=0,
                keyframe_uri="s3://vms-keyframes/f.jpg",
                objects=[
                    FrameObject(
                        track_id=f"{camera_code}-t1",
                        category="person",
                        conf=0.9,
                        bbox=(0.1, 0.1, 0.2, 0.2),
                    )
                ],
            )
        ],
    )
    await s3_client.put_bytes(
        seg.twin_uri, twin.model_dump_json().encode(), content_type="application/json"
    )

    resp = client.get(
        f"/api/v1/twin/{camera_code}/frames",
        params={"start": T0.isoformat(), "end": (T0 + timedelta(seconds=10)).isoformat()},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["frames"]) == 1
    assert body["frames"][0]["objects"][0]["track_id"] == f"{camera_code}-t1"
    assert body["frames"][0]["objects"][0]["bbox"] == [0.1, 0.1, 0.2, 0.2]


async def test_twin_frames_endpoint_rejects_a_window_over_60_seconds(
    client: TestClient,
    auth_headers: Callable[[str], dict[str, str]],
    admin_access_token: str,
    camera_code: str,
) -> None:
    headers = auth_headers(admin_access_token)
    resp = client.get(
        f"/api/v1/twin/{camera_code}/frames",
        params={"start": T0.isoformat(), "end": (T0 + timedelta(seconds=61)).isoformat()},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
