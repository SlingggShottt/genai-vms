"""P2-J2: point ids must be deterministic (same key -> same id, replay-safe)
and distinct across different keys, so Qdrant's upsert naturally dedupes.
"""

from __future__ import annotations

import uuid

from vms_common.qdrant.point_ids import frame_point_id, track_point_id


def test_frame_point_id_is_deterministic() -> None:
    a = frame_point_id("cam03_20261005T101500Z_000123", 1)
    b = frame_point_id("cam03_20261005T101500Z_000123", 1)
    assert a == b


def test_frame_point_id_is_a_valid_uuid() -> None:
    assert uuid.UUID(frame_point_id("seg1", 0))


def test_frame_point_id_differs_by_segment_and_by_index() -> None:
    base = frame_point_id("seg1", 0)
    assert frame_point_id("seg2", 0) != base
    assert frame_point_id("seg1", 1) != base


def test_track_point_id_is_deterministic() -> None:
    a = track_point_id("cam03-t412", "seg1")
    b = track_point_id("cam03-t412", "seg1")
    assert a == b


def test_track_point_id_differs_by_track_and_by_segment() -> None:
    base = track_point_id("cam03-t412", "seg1")
    assert track_point_id("cam03-t999", "seg1") != base
    assert track_point_id("cam03-t412", "seg2") != base


def test_frame_and_track_point_ids_never_collide() -> None:
    # Different namespace prefixes ("frame:"/"track:") even for the same raw key.
    assert frame_point_id("x", 0) != track_point_id("x", "0")
