"""Unit tests for the `core.zones` model — metadata shape only, no DB (P2-J4)."""

from __future__ import annotations

from vms_db.base import Base
from vms_db.models.core import SCHEMA, ZoneType


def test_zones_is_registered_in_the_core_schema() -> None:
    table = Base.metadata.tables["core.zones"]
    assert table.schema == SCHEMA


def test_zones_camera_id_is_a_foreign_key_to_cameras() -> None:
    table = Base.metadata.tables["core.zones"]
    fk_targets = {fk.target_fullname for fk in table.c.camera_id.foreign_keys}
    assert fk_targets == {"core.cameras.id"}


def test_zone_type_has_four_values() -> None:
    assert {t.value for t in ZoneType} == {"generic", "restricted", "entrance", "exit"}
