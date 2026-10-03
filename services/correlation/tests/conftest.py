"""Shared fixtures for the correlation tests: the shipped config, the contract fixtures as
engine inputs, and a tiny event/edge builder so each test states only what it is about."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from correlation.domain.config import CorrelationConfig
from correlation.domain.topology import Topology
from correlation.domain.types import EventRecord
from vms_common.contracts.event import EventV1
from vms_common.contracts.topology import TopologyEdgeInternal, TopologyInternalResponse

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "libs" / "vms_common" / "src" / "vms_common" / "fixtures"
T0 = datetime(2026, 10, 5, 10, 15, 0, tzinfo=UTC)

EventFactory = Callable[..., EventRecord]
EdgeFactory = Callable[..., TopologyEdgeInternal]


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def shipped_config() -> CorrelationConfig:
    """`config/correlation.yaml` as the service will load it."""
    return CorrelationConfig.model_validate(
        yaml.safe_load((REPO / "config" / "correlation.yaml").read_text())
    )


@pytest.fixture
def fixture_topology() -> Topology:
    raw = json.loads((FIXTURES / "topology_internal.json").read_text())
    return Topology(TopologyInternalResponse.model_validate(raw).edges)


@pytest.fixture
def fixture_events() -> dict[str, EventRecord]:
    """The three event.v1 fixtures keyed by event_type."""
    out = {}
    for name in ("intrusion", "running_skipped", "abandoned_object"):
        e = EventV1.model_validate(json.loads((FIXTURES / f"event_v1_{name}.json").read_text()))
        out[e.event_type] = EventRecord(
            event_id=e.event_id,
            site_id=e.site_id,
            camera_id=e.camera_id,
            event_type=e.event_type,
            severity=e.severity,
            start_ts=e.start_ts,
            end_ts=e.end_ts,
        )
    return out


@pytest.fixture
def ev() -> EventFactory:
    def make(
        camera: str,
        event_type: str = "intrusion",
        start: float = 0,
        end: float = 10,
        *,
        severity: str = "high",
        site: str = "site",
        event_id: str | None = None,
    ) -> EventRecord:
        return EventRecord(
            event_id=event_id or str(uuid.uuid4()),
            site_id=site,
            camera_id=camera,
            event_type=event_type,
            severity=severity,
            start_ts=at(start),
            end_ts=at(end),
        )

    return make


@pytest.fixture
def edge() -> EdgeFactory:
    counter = iter(range(1, 1000))

    def make(a: str, b: str, kind: str = "transit", **kw: object) -> TopologyEdgeInternal:
        params: dict[str, object] = {"min_s": 5.0, "max_s": 90.0, "bidirectional": False}
        if kind == "overlap":
            params = {"tolerance_s": 3.0, "bidirectional": True}
        return TopologyEdgeInternal.model_validate(
            {"id": f"e{next(counter)}", "from_camera_id": a, "to_camera_id": b, "edge_type": kind}
            | params
            | kw
        )

    return make
