"""Tests for vms_common.config settings classes."""

import pytest
from pydantic import ValidationError
from vms_common.config import KafkaSettings, LLMProfileSettings, StorageSettings


def test_kafka_settings_reads_its_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VMS_KAFKA_BOOTSTRAP_SERVERS", "broker1:9092,broker2:9092")
    settings = KafkaSettings()
    assert settings.bootstrap_servers == "broker1:9092,broker2:9092"


def test_kafka_settings_has_sane_defaults() -> None:
    settings = KafkaSettings()
    assert settings.bootstrap_servers == "localhost:9092"
    assert settings.dlq_topic == "vms.dlq.v1"


def test_storage_settings_rejects_presign_expiry_over_15_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VMS_STORAGE_PRESIGN_EXPIRY_SECONDS", "3600")
    with pytest.raises(ValidationError):
        StorageSettings()


def test_llm_profile_settings_accepts_only_known_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VMS_LLM_PROFILE", "hybrid")
    assert LLMProfileSettings().profile == "hybrid"

    monkeypatch.setenv("VMS_LLM_PROFILE", "not-a-real-profile")
    with pytest.raises(ValidationError):
        LLMProfileSettings()


def test_llm_profile_defaults_to_local() -> None:
    assert LLMProfileSettings().profile == "local"
