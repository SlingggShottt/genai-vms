"""Distinct identifier types so a camera's human-readable `code` (e.g.
`"cam03"`) and its `core.cameras.id` UUID can't be silently swapped for
each other at a type-checked call site.

Both are plain `str` at runtime (`NewType` only adds a static-typing
boundary — zero runtime cost, confirmed with Pydantic v2: a `CameraCode`
field validates and serializes exactly like `str`). Which one is used
where is a real, load-bearing convention, not an accident:

- `CameraCode` — every Kafka message contract (`segment.v1`, `twin.v1`,
  `twinready.v1`), every internal HTTP contract's camera reference
  (`CameraInternal.code`, `ZoneInternal.camera_id`), and every table
  populated from those (`media.segments.camera_id`, `vision.*.camera_id`).
  Ingestion/perception/events/indexer only ever see this — camera codes
  are stable, human-readable, and don't require a DB round-trip to use as
  a Kafka key or object-storage path segment.
- `CameraId` — `core.cameras.id`, the UUID the public REST API
  (`services/api`) keys `/cameras/{id}`, `/zones/{id}` etc. on, matching
  every other resource id in that API.

See `docs/design_architecture.md §5.1` for the full write-up.
"""

from __future__ import annotations

from typing import NewType

CameraCode = NewType("CameraCode", str)
CameraId = NewType("CameraId", str)
