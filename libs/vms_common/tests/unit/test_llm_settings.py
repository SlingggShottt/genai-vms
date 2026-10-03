"""LLMSettings: provider keys, Ollama location, lease knobs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from vms_common.config import LLMSettings

ENV_NAMES = (
    "VMS_LLM_PROFILE", "VMS_LLM_OLLAMA_URL", "VMS_LLM_GENAI_HOST", "VMS_GENAI_HOST",
    "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "VMS_LLM_GEMINI_API_KEY",
)  # fmt: skip


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def settings(**kw) -> LLMSettings:
    return LLMSettings(_env_file=None, **kw)  # never read the developer's real .env


def test_defaults_are_local_and_keyless() -> None:
    s = settings()
    assert s.profile == "local"
    assert s.models_path == "config/models.yaml"
    assert s.effective_ollama_url == "http://localhost:11434"
    assert s.gemini_api_key.get_secret_value() == ""
    assert (s.lease_node, s.lease_ttl_seconds, s.lease_wait_seconds) == ("local", 30.0, 120.0)


def test_profile_is_still_restricted_to_the_three_known_ones(monkeypatch) -> None:
    monkeypatch.setenv("VMS_LLM_PROFILE", "cloud")
    assert settings().profile == "cloud"
    monkeypatch.setenv("VMS_LLM_PROFILE", "staging")
    with pytest.raises(ValidationError):
        settings()


def test_provider_keys_are_read_under_their_native_names(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("GROQ_API_KEY", "q-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o-key")
    s = settings()
    assert s.gemini_api_key.get_secret_value() == "g-key"
    assert s.groq_api_key.get_secret_value() == "q-key"
    assert s.openrouter_api_key.get_secret_value() == "o-key"


def test_provider_keys_also_accept_the_prefixed_name(monkeypatch) -> None:
    monkeypatch.setenv("VMS_LLM_GEMINI_API_KEY", "prefixed")
    assert settings().gemini_api_key.get_secret_value() == "prefixed"


def test_keys_never_appear_in_repr_or_dumps(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
    s = settings()
    assert "super-secret-value" not in repr(s)
    assert "super-secret-value" not in str(s)
    assert "super-secret-value" not in s.model_dump_json()


def test_ollama_location_comes_from_the_genai_host(monkeypatch) -> None:
    monkeypatch.setenv("VMS_GENAI_HOST", "192.168.1.20")
    assert settings().effective_ollama_url == "http://192.168.1.20:11434"
    monkeypatch.setenv("VMS_LLM_GENAI_HOST", "laptop-b")
    assert settings().effective_ollama_url == "http://laptop-b:11434"


def test_explicit_ollama_url_wins_over_the_host(monkeypatch) -> None:
    monkeypatch.setenv("VMS_GENAI_HOST", "192.168.1.20")
    monkeypatch.setenv("VMS_LLM_OLLAMA_URL", "http://gpu-box:9999")
    assert settings().effective_ollama_url == "http://gpu-box:9999"


@pytest.mark.parametrize("name", ["lease_ttl_seconds"])
def test_lease_ttl_must_be_positive(name: str) -> None:
    with pytest.raises(ValidationError):
        settings(**{name: 0})
