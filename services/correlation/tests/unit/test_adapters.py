"""Config loader, topology source, publisher and settings — no database, no Kafka."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from correlation.adapters.config_loader import load_correlation_config
from correlation.adapters.publisher import KafkaCorrelationPublisher
from correlation.adapters.topology_source import (
    fetch_topology_from_api,
    load_topology_from_yaml,
    resolve_topology,
)
from correlation.settings import CorrelationSettings
from pydantic import ValidationError
from vms_common.contracts.correlation import CorrelationV1

REPO = Path(__file__).resolve().parents[4]
FIXTURE = json.loads(
    (REPO / "libs/vms_common/src/vms_common/fixtures/topology_internal.json").read_text()
)


# --- config loader ---------------------------------------------------------------------------


def test_the_shipped_config_file_loads() -> None:
    config = load_correlation_config(REPO / "config" / "correlation.yaml")
    assert config.link_threshold == 0.5 and "intrusion" in config.compatibility


def test_a_missing_config_file_is_an_oserror(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        load_correlation_config(tmp_path / "nope.yaml")


@pytest.mark.parametrize("content", ["- a\n- b\n", "just a string", ""])
def test_a_config_that_is_not_a_mapping_is_a_valueerror(tmp_path: Path, content: str) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(content)
    with pytest.raises(ValueError, match="mapping"):
        load_correlation_config(path)


def test_an_invalid_config_is_a_validation_error_naming_the_field(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text("link_threshold: 7\n")
    with pytest.raises(ValidationError, match="link_threshold"):
        load_correlation_config(path)
    path.write_text("link_thresold: 0.5\n")  # a typo
    with pytest.raises(ValidationError, match="link_thresold"):
        load_correlation_config(path)


# --- topology source -------------------------------------------------------------------------


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_the_api_is_asked_with_the_service_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=FIXTURE)

    edges = await fetch_topology_from_api(
        "http://api:8000/api/v1/", service_token="s3cret", client=_client(handler)
    )
    assert [e.edge_type for e in edges] == ["overlap", "transit", "transit"]
    (request,) = seen
    assert str(request.url) == "http://api:8000/api/v1/internal/v1/topology"
    assert request.headers["authorization"] == "Bearer s3cret"


async def test_no_token_means_no_authorization_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"edges": []})

    await fetch_topology_from_api("http://api", client=_client(handler))
    assert "authorization" not in seen[0].headers


async def test_an_api_error_status_raises(tmp_path: Path) -> None:
    client = _client(lambda r: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await fetch_topology_from_api("http://api", client=client)


async def test_resolve_falls_back_to_the_yaml_when_the_api_is_down(tmp_path: Path) -> None:
    fallback = tmp_path / "topology.yaml"
    fallback.write_text(json.dumps(FIXTURE))  # JSON is YAML
    client = _client(lambda r: httpx.Response(500))
    edges = await resolve_topology(
        api_base_url="http://api", service_token="", yaml_fallback_path=fallback, client=client
    )
    assert len(edges) == 3


async def test_resolve_falls_back_on_a_connection_error(tmp_path: Path) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    fallback = tmp_path / "t.yaml"
    fallback.write_text("edges: []\n")
    edges = await resolve_topology(
        api_base_url="http://api",
        service_token="",
        yaml_fallback_path=fallback,
        client=_client(refuse),
    )
    assert edges == []


async def test_resolve_uses_the_api_when_it_answers(tmp_path: Path) -> None:
    edges = await resolve_topology(
        api_base_url="http://api",
        service_token="",
        yaml_fallback_path=tmp_path / "unused.yaml",
        client=_client(lambda r: httpx.Response(200, json=FIXTURE)),
    )
    assert len(edges) == 3


async def test_resolve_without_an_api_url_reads_the_yaml_only(tmp_path: Path) -> None:
    fallback = tmp_path / "t.yaml"
    fallback.write_text(json.dumps(FIXTURE))
    edges = await resolve_topology(api_base_url=None, service_token="", yaml_fallback_path=fallback)
    assert len(edges) == 3


async def test_an_api_payload_that_breaks_the_contract_is_not_silently_accepted(
    tmp_path: Path,
) -> None:
    bad = {
        "edges": [{"id": "x", "from_camera_id": "a", "to_camera_id": "a", "edge_type": "overlap"}]
    }
    with pytest.raises(ValidationError):
        await resolve_topology(
            api_base_url="http://api",
            service_token="",
            yaml_fallback_path=tmp_path / "t.yaml",
            client=_client(lambda r: httpx.Response(200, json=bad)),
        )


def test_a_missing_topology_yaml_is_an_empty_graph_not_a_crash(tmp_path: Path) -> None:
    assert load_topology_from_yaml(tmp_path / "absent.yaml") == []


def test_an_empty_topology_yaml_is_an_empty_graph(tmp_path: Path) -> None:
    path = tmp_path / "t.yaml"
    path.write_text("")
    assert load_topology_from_yaml(path) == []


def test_the_shipped_example_topology_is_valid() -> None:
    edges = load_topology_from_yaml(REPO / "config" / "topology.example.yaml")
    assert {e.edge_type for e in edges} == {"overlap", "transit"}


# --- publisher & settings ----------------------------------------------------------------------


async def test_messages_are_sent_to_the_topic_keyed_by_site() -> None:
    sent: list[tuple[str, str, object]] = []

    class FakeProducer:
        async def send(self, topic: str, *, key: str, message: object) -> None:
            sent.append((topic, key, message))

    message = CorrelationV1.model_validate(
        json.loads(
            (REPO / "libs/vms_common/src/vms_common/fixtures/correlation_v1.json").read_text()
        )
    )
    await KafkaCorrelationPublisher(FakeProducer(), topic="vms.correlations.v1").publish(message)  # type: ignore[arg-type]
    assert sent == [("vms.correlations.v1", "rvce-campus", message)]


def test_settings_defaults_match_the_designs_topics(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("VMS_CORRELATION_API_BASE_URL", "VMS_CORRELATION_CONFIG_PATH"):
        monkeypatch.delenv(name, raising=False)
    s = CorrelationSettings(_env_file=None)
    assert (s.events_topic, s.correlations_topic) == ("vms.events.v1", "vms.correlations.v1")
    assert s.consumer_group == "correlation" and s.api_base_url is None
    assert s.topology_refresh_seconds == 60 and s.sweep_interval_seconds == 1.0


def test_settings_read_the_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VMS_CORRELATION_API_BASE_URL", "http://api:8000/api/v1")
    monkeypatch.setenv("VMS_CORRELATION_SWEEP_INTERVAL_SECONDS", "0.25")
    s = CorrelationSettings(_env_file=None)
    assert s.api_base_url == "http://api:8000/api/v1" and s.sweep_interval_seconds == 0.25
    monkeypatch.setenv("VMS_CORRELATION_SWEEP_INTERVAL_SECONDS", "0")
    with pytest.raises(ValidationError):
        CorrelationSettings(_env_file=None)
