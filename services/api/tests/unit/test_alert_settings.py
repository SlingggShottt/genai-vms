"""AlertSettings / NotifySettings: defaults and startup validation (P3-J3, FR-ALR-03)."""

from __future__ import annotations

import pytest
from api.settings import AlertSettings, ApiSettings, NotifySettings
from pydantic import ValidationError

ENV = (
    "VMS_ALERTS_MIN_SEVERITY", "VMS_ALERTS_CONSUMERS_ENABLED", "VMS_ALERTS_WS_QUEUE_SIZE",
    "VMS_ALERTS_NOTIFY_MAX_AGE_SECONDS",
    "VMS_NOTIFY_CHANNELS", "VMS_NOTIFY_SMTP_HOST", "VMS_NOTIFY_EMAIL_FROM", "VMS_NOTIFY_EMAIL_TO",
    "VMS_NOTIFY_TELEGRAM_BOT_TOKEN", "VMS_NOTIFY_TELEGRAM_CHAT_ID", "VMS_NOTIFY_SMTP_PASSWORD",
)  # fmt: skip


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def notify(**kw) -> NotifySettings:
    return NotifySettings(_env_file=None, **kw)


def test_alert_defaults() -> None:
    s = AlertSettings(_env_file=None)
    assert (s.min_severity, s.consumers_enabled, s.ws_queue_size) == ("medium", True, 100)
    assert (s.events_topic, s.correlations_topic) == ("vms.events.v1", "vms.correlations.v1")
    assert s.events_group != s.correlations_group  # two consumers, two offsets


def test_the_announcement_window_defaults_to_fifteen_minutes_and_must_be_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert AlertSettings(_env_file=None).notify_max_age_seconds == 900
    for bad in ("0", "-5"):
        monkeypatch.setenv("VMS_ALERTS_NOTIFY_MAX_AGE_SECONDS", bad)
        with pytest.raises(ValidationError):
            AlertSettings(_env_file=None)


def test_alert_settings_read_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VMS_ALERTS_MIN_SEVERITY", "high")
    monkeypatch.setenv("VMS_ALERTS_CONSUMERS_ENABLED", "false")
    s = AlertSettings(_env_file=None)
    assert s.min_severity == "high" and s.consumers_enabled is False


def test_an_unknown_minimum_severity_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VMS_ALERTS_MIN_SEVERITY", "catastrophic")
    with pytest.raises(ValidationError):
        AlertSettings(_env_file=None)


def test_only_the_dashboard_channel_is_on_by_default() -> None:
    s = notify()
    assert s.enabled_channels == ["dashboard"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("dashboard", ["dashboard"]),
        (" Dashboard , EMAIL ", ["dashboard", "email"]),
        ("", []),  # nothing on: legal, if unusual
        ("dashboard,,", ["dashboard"]),
    ],
)
def test_channels_are_a_tolerant_comma_list(raw, expected) -> None:
    kw = {"smtp_host": "h", "email_from": "a@b.co", "email_to": "c@d.co"}
    assert notify(channels=raw, **kw).enabled_channels == expected


def test_an_unknown_channel_is_a_startup_error() -> None:
    with pytest.raises(ValidationError, match=r"unknown channel.*sms"):
        notify(channels="dashboard,sms")


def test_the_email_channel_needs_its_settings() -> None:
    with pytest.raises(
        ValidationError, match="VMS_NOTIFY_SMTP_HOST.*VMS_NOTIFY_EMAIL_FROM.*VMS_NOTIFY_EMAIL_TO"
    ):
        notify(channels="email")
    ok = notify(
        channels="email",
        smtp_host="smtp.example.com",
        email_from="vms@example.com",
        email_to="a@x.org, b@x.org",
    )
    assert ok.email_recipients == ["a@x.org", "b@x.org"]


def test_the_telegram_channel_needs_its_settings() -> None:
    with pytest.raises(
        ValidationError, match="VMS_NOTIFY_TELEGRAM_BOT_TOKEN.*VMS_NOTIFY_TELEGRAM_CHAT_ID"
    ):
        notify(channels="telegram")
    with pytest.raises(ValidationError, match="VMS_NOTIFY_TELEGRAM_CHAT_ID"):
        notify(channels="telegram", telegram_bot_token="123:abc")
    assert notify(channels="telegram", telegram_bot_token="123:abc", telegram_chat_id="-100")


def test_unused_channels_need_no_settings() -> None:
    assert notify(channels="dashboard").enabled_channels == ["dashboard"]  # no smtp, no token


def test_secrets_never_appear_in_repr_or_dumps() -> None:
    s = notify(
        channels="telegram",
        telegram_bot_token="123:very-secret",
        telegram_chat_id="-1",
        smtp_password="pw-secret",
    )
    text = repr(s) + str(s) + s.model_dump_json()
    assert "very-secret" not in text and "pw-secret" not in text


def test_the_api_settings_carry_the_new_blocks() -> None:
    s = ApiSettings(_env_file=None)
    assert s.alerts.min_severity == "medium" and s.notify.enabled_channels == ["dashboard"]
    assert s.kafka.bootstrap_servers
