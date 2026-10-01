"""Deterministic candidate ids (design §15 idempotency key
`(camera_id, rule_id, track_id, start_ts)`) — pure."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

from events.domain.candidates import CANDIDATE_NAMESPACE, candidate_id

START = datetime(2026, 10, 1, 7, 0, 0, 500000, tzinfo=UTC)


def _id(**overrides) -> uuid.UUID:
    args = {
        "camera_id": "cam01",
        "rule_id": "loitering",
        "zone_name": "yard",
        "hit_key": "cam01-t1",
        "start_ts": START,
    }
    args.update(overrides)
    return candidate_id(**args)


def test_the_same_episode_always_gets_the_same_id() -> None:
    assert _id() == _id()


def test_the_namespace_is_pinned_so_ids_never_change_between_releases() -> None:
    # If this fails someone changed the namespace or the key layout: every id in
    # events.candidates would stop matching and replays would duplicate rows.
    assert str(CANDIDATE_NAMESPACE) == "5b0f1c52-6b1f-4c0e-9a4e-3f7a8d1e2c90"
    assert str(_id()) == str(
        uuid.uuid5(
            CANDIDATE_NAMESPACE, "cam01|loitering|yard|cam01-t1|2026-10-01T07:00:00.500000+00:00"
        )
    )


def test_each_part_of_the_key_changes_the_id() -> None:
    base = _id()

    assert _id(camera_id="cam02") != base
    assert _id(rule_id="crowding") != base
    assert _id(zone_name="lobby") != base
    assert _id(hit_key="cam01-t2") != base
    assert _id(start_ts=START + timedelta(microseconds=1)) != base


def test_the_id_does_not_depend_on_how_the_timestamp_is_expressed() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))

    assert _id(start_ts=START.astimezone(ist)) == _id()


def test_it_is_a_valid_uuid() -> None:
    assert isinstance(_id(), uuid.UUID)
    assert _id().version == 5
