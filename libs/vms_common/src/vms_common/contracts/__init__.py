"""Pydantic contracts that cross a service boundary (Kafka messages, documents).

Each contract module declares a `schema_version` literal and ships with a
fixture in ../fixtures/ plus a round-trip test. Populated per-phase — see
docs/design_architecture.md §16 for the freeze schedule.
"""

from vms_common.contracts.base import MessageEnvelope
from vms_common.contracts.camera import CameraInternal, CamerasInternalResponse
from vms_common.contracts.correlation import CorrelationLink, CorrelationV1
from vms_common.contracts.embeddings import (
    InvalidEmbeddingsError,
    build_embeddings_npz,
    load_embeddings_npz,
)
from vms_common.contracts.event import EventV1, Verification
from vms_common.contracts.reasoning import (
    EvidenceBundleV1,
    IncidentReadyV1,
    IncidentReportV1,
    PhaseTimelineV1,
)
from vms_common.contracts.segment import SegmentV1
from vms_common.contracts.search import QueryPlan, SearchRequest, SearchResponse, SearchResult
from vms_common.contracts.topology import TopologyEdgeInternal, TopologyInternalResponse
from vms_common.contracts.twin import (
    Frame,
    FrameObject,
    FrameSize,
    ObjectAttributes,
    ObjectMotion,
    Scene,
    TrackSummary,
    TwinV1,
)
from vms_common.contracts.twinready import TwinReadyV1
from vms_common.contracts.zones import ZoneInternal, ZoneSchedule, ZonesInternalResponse

__all__ = [
    "CameraInternal",
    "CamerasInternalResponse",
    "CorrelationLink",
    "CorrelationV1",
    "EventV1",
    "EvidenceBundleV1",
    "IncidentReadyV1",
    "IncidentReportV1",
    "PhaseTimelineV1",
    "QueryPlan",
    "SearchRequest",
    "SearchResponse",
    "SearchResult",
    "Frame",
    "FrameObject",
    "FrameSize",
    "InvalidEmbeddingsError",
    "MessageEnvelope",
    "ObjectAttributes",
    "ObjectMotion",
    "Scene",
    "SegmentV1",
    "TopologyEdgeInternal",
    "TopologyInternalResponse",
    "TrackSummary",
    "TwinReadyV1",
    "TwinV1",
    "Verification",
    "ZoneInternal",
    "ZoneSchedule",
    "ZonesInternalResponse",
    "build_embeddings_npz",
    "load_embeddings_npz",
]
