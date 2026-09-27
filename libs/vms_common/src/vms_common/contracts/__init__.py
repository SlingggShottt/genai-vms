"""Pydantic contracts that cross a service boundary (Kafka messages, documents).

Each contract module declares a `schema_version` literal and ships with a
fixture in ../fixtures/ plus a round-trip test. Populated per-phase — see
docs/design_architecture.md §16 for the freeze schedule.
"""

from vms_common.contracts.base import MessageEnvelope
from vms_common.contracts.camera import CameraInternal, CamerasInternalResponse
from vms_common.contracts.segment import SegmentV1

__all__ = [
    "CameraInternal",
    "CamerasInternalResponse",
    "MessageEnvelope",
    "SegmentV1",
]
