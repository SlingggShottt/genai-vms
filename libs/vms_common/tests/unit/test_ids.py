"""Tests for vms_common.ids.uuid7 (style_guide.md §A.1: unit tests for domain logic)."""

import uuid

from vms_common.ids import uuid7, uuid7_str


def test_uuid7_has_correct_version_and_variant() -> None:
    u = uuid7()
    assert u.version == 7
    assert u.variant == uuid.RFC_4122


def test_uuid7_is_monotonically_non_decreasing() -> None:
    ids = [uuid7() for _ in range(1000)]
    timestamps = [int.from_bytes(u.bytes[0:6], "big") for u in ids]
    assert timestamps == sorted(timestamps)


def test_uuid7_ids_are_unique() -> None:
    ids = {uuid7() for _ in range(10_000)}
    assert len(ids) == 10_000


def test_uuid7_str_is_a_valid_uuid7_string() -> None:
    s = uuid7_str()
    assert uuid.UUID(s).version == 7
