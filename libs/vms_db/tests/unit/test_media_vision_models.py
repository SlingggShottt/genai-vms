"""Unit tests for the `media`/`vision` schema models — metadata shape only,
no DB (P2-J1). Catches accidental table/schema renames before they reach a
migration.
"""

from __future__ import annotations

from vms_db.base import Base
from vms_db.models.media import SCHEMA as MEDIA_SCHEMA
from vms_db.models.vision import SCHEMA as VISION_SCHEMA


def test_media_vision_tables_are_registered_on_base_metadata() -> None:
    table_names = {table.name for table in Base.metadata.tables.values()}
    assert {"segments", "tracks", "track_segments", "minute_counts"} <= table_names


def test_segments_lives_in_media_schema() -> None:
    table = Base.metadata.tables["media.segments"]
    assert table.schema == MEDIA_SCHEMA


def test_tracks_and_friends_live_in_vision_schema() -> None:
    for full_name in ("vision.tracks", "vision.track_segments", "vision.minute_counts"):
        assert Base.metadata.tables[full_name].schema == VISION_SCHEMA


def test_track_segments_primary_key_is_track_and_segment() -> None:
    table = Base.metadata.tables["vision.track_segments"]
    assert {c.name for c in table.primary_key.columns} == {"track_id", "segment_id"}


def test_minute_counts_primary_key_is_camera_category_minute() -> None:
    table = Base.metadata.tables["vision.minute_counts"]
    assert {c.name for c in table.primary_key.columns} == {"camera_id", "category", "minute_ts"}
