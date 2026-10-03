"""Notifier channels, their formatting and the dispatcher's isolation (P3-J3, FR-ALR-03).
No network: SMTP is a recording fake and Telegram goes through `httpx.MockTransport`."""

from __future__ import annotations

import asyncio
import smtplib
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from api.notifiers import (
    AlertNotice,
    NotificationDispatcher,
    NotifierError,
    build_dispatcher,
    build_notifiers,
)
from api.notifiers import email_notifier as email_module
from api.notifiers.base import MAX_CAPTION_CHARS, body_text, subject_line
from api.notifiers.dashboard import DashboardNotifier
from api.notifiers.email_notifier import EmailNotifier
from api.notifiers.telegram import TelegramNotifier
from api.realtime.messages import WsMessage
from api.settings import NotifySettings
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

ENV = (
    "VMS_NOTIFY_CHANNELS", "VMS_NOTIFY_SMTP_HOST", "VMS_NOTIFY_EMAIL_FROM", "VMS_NOTIFY_EMAIL_TO",
    "VMS_NOTIFY_TELEGRAM_BOT_TOKEN", "VMS_NOTIFY_TELEGRAM_CHAT_ID",
)  # fmt: skip
TOKEN = "123456:secret-bot-token"  # noqa: S105 - fixture value
SMTP_PASSWORD = "hunter2"  # noqa: S105 - fixture value


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def notice(**over: Any) -> AlertNotice:
    fields: dict[str, Any] = {
        "alert_id": "0198f2a0-0000-7000-8000-000000000001",
        "title": "Intrusion on cam02",
        "severity": "high",
        "event_type": "intrusion",
        "camera_code": "cam02",
        "caption": "A person climbs the north fence.",
        "start_ts": datetime(2026, 10, 3, 8, 35, 20, tzinfo=UTC),
    }
    fields.update(over)
    fields.setdefault("payload", {"id": fields["alert_id"], "title": fields["title"]})
    return AlertNotice(**fields)


def settings(**kw: Any) -> NotifySettings:
    return NotifySettings(_env_file=None, **kw)


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


# --- formatting ----------------------------------------------------------------------------------


def test_the_subject_names_severity_and_what_happened() -> None:
    assert subject_line(notice()) == "[HIGH] Intrusion on cam02"


def test_the_subject_is_always_one_line() -> None:
    assert subject_line(notice(title="Intrusion\r\nBcc: x@evil.test")) == (
        "[HIGH] Intrusion Bcc: x@evil.test"
    )


def test_the_body_shows_the_time_in_ist_not_utc() -> None:
    body = body_text(notice())  # 08:35:20 UTC
    assert "03 Oct 2026, 14:05:20 IST" in body
    assert "08:35" not in body


def test_the_body_carries_the_caption_and_the_alert_id() -> None:
    body = body_text(notice())
    assert "A person climbs the north fence." in body
    assert "Alert 0198f2a0-0000-7000-8000-000000000001" in body


def test_a_missing_caption_leaves_no_blank_section() -> None:
    body = body_text(notice(caption=None))
    assert "None" not in body
    assert "\n\n\n" not in body


def test_a_long_caption_is_cut_to_exactly_the_limit_with_an_ellipsis() -> None:
    body = body_text(notice(caption="x" * 800))  # no whitespace for rstrip to hide an off-by-one
    shown = next(line for line in body.splitlines() if line.startswith("x"))
    assert len(shown) == MAX_CAPTION_CHARS
    assert shown == "x" * (MAX_CAPTION_CHARS - 1) + "…"


def test_a_cut_caption_does_not_end_in_a_space_before_the_ellipsis() -> None:
    body = body_text(notice(caption=("word " * 400)))
    shown = next(line for line in body.splitlines() if line.startswith("word"))
    assert shown.endswith("d…") and len(shown) <= MAX_CAPTION_CHARS


def test_a_caption_exactly_at_the_limit_is_not_cut() -> None:
    caption = "x" * MAX_CAPTION_CHARS
    assert caption in body_text(notice(caption=caption))


def test_caption_whitespace_is_collapsed() -> None:
    assert "a b c" in body_text(notice(caption="a\n\n b\t c"))


# --- dashboard -----------------------------------------------------------------------------------


async def test_the_dashboard_channel_publishes_alert_created_with_the_payload() -> None:
    sent: list[WsMessage] = []

    async def publish(message: WsMessage) -> None:
        sent.append(message)

    await DashboardNotifier(publish).send(notice(payload={"id": "a1", "severity": "high"}))
    assert [(m.type, m.data) for m in sent] == [("alert.created", {"id": "a1", "severity": "high"})]


# --- email ---------------------------------------------------------------------------------------


class FakeSMTP:
    instances: list[FakeSMTP] = []
    fail_with: Exception | None = None

    def __init__(self, host: str, port: int, **kwargs: Any) -> None:
        self.kind = type(self).__name__
        self.host, self.port, self.kwargs = host, port, kwargs
        self.calls: list[tuple[str, Any]] = []
        type(self).instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        self.calls.append(("quit", None))

    def starttls(self, *, context: object) -> None:
        self.calls.append(("starttls", context is not None))

    def login(self, user: str, password: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append(("login", (user, password)))

    def send_message(self, message: Any, *, to_addrs: list[str]) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append(("send", (message, to_addrs)))


class FakeSMTPSSL(FakeSMTP):
    pass


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances = []
    FakeSMTP.fail_with = None
    monkeypatch.setattr(email_module.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_module.smtplib, "SMTP_SSL", FakeSMTPSSL)
    return FakeSMTP


def email_settings(**kw: Any) -> NotifySettings:
    base: dict[str, Any] = {
        "channels": "email",
        "smtp_host": "smtp.example.test",
        "email_from": "vms@example.test",
        "email_to": "ops@example.test, soc@example.test",
    }
    return settings(**(base | kw))


async def test_an_email_goes_to_every_recipient_with_the_subject_and_body(smtp) -> None:
    await EmailNotifier(email_settings()).send(notice())
    (server,) = smtp.instances
    assert (server.host, server.port) == ("smtp.example.test", 587)
    sent = next(arg for name, arg in server.calls if name == "send")
    message, recipients = sent
    assert recipients == ["ops@example.test", "soc@example.test"]
    assert message["Subject"] == "[HIGH] Intrusion on cam02"
    assert message["From"] == "vms@example.test"
    assert "14:05:20 IST" in message.get_content()


async def test_starttls_runs_before_login_and_before_anything_is_sent(smtp) -> None:
    await EmailNotifier(
        email_settings(smtp_username="vms", smtp_password=SMTP_PASSWORD)
    ).send(notice())  # fmt: skip
    steps = [name for name, _ in smtp.instances[0].calls]
    assert steps == ["starttls", "login", "send", "quit"]
    assert dict(smtp.instances[0].calls)["login"] == ("vms", SMTP_PASSWORD)


async def test_starttls_can_be_switched_off(smtp) -> None:
    await EmailNotifier(email_settings(smtp_starttls=False, smtp_port=25)).send(notice())
    assert "starttls" not in [name for name, _ in smtp.instances[0].calls]


async def test_no_username_means_no_login(smtp) -> None:
    await EmailNotifier(email_settings()).send(notice())
    assert "login" not in [name for name, _ in smtp.instances[0].calls]


async def test_port_465_uses_implicit_tls_and_never_starttls(smtp) -> None:
    await EmailNotifier(email_settings(smtp_port=465)).send(notice())
    (server,) = smtp.instances
    assert server.kind == "FakeSMTPSSL"
    assert "starttls" not in [name for name, _ in server.calls]


async def test_the_smtp_timeout_comes_from_settings(smtp) -> None:
    await EmailNotifier(email_settings(timeout_seconds=3.5)).send(notice())
    assert smtp.instances[0].kwargs["timeout"] == 3.5


async def test_an_smtp_failure_is_reported_without_the_servers_message(smtp) -> None:
    smtp.fail_with = smtplib.SMTPAuthenticationError(
        535, f"bad credentials {SMTP_PASSWORD}".encode()
    )
    with pytest.raises(NotifierError) as caught:
        await EmailNotifier(
            email_settings(smtp_username="vms", smtp_password=SMTP_PASSWORD)
        ).send(notice())  # fmt: skip
    assert SMTP_PASSWORD not in str(caught.value)
    assert "SMTPAuthenticationError" in str(caught.value)
    assert caught.value.__cause__ is None  # nothing in the chain carries the original text


async def test_a_connection_failure_is_a_notifier_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_a: Any, **_k: Any) -> None:
        raise ConnectionRefusedError("smtp.example.test:587")

    monkeypatch.setattr(email_module.smtplib, "SMTP", refuse)
    with pytest.raises(NotifierError, match="ConnectionRefusedError"):
        await EmailNotifier(email_settings()).send(notice())


# --- telegram ------------------------------------------------------------------------------------


def telegram(handler: Any, **kw: Any) -> TelegramNotifier:
    cfg = settings(channels="telegram", telegram_bot_token=TOKEN, telegram_chat_id="-1001", **kw)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TelegramNotifier(cfg, client=client, api_base="https://tg.example.test")


async def test_a_telegram_message_is_posted_to_the_bot_api_as_plain_text() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    await telegram(handler).send(notice())
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == f"https://tg.example.test/bot{TOKEN}/sendMessage"
    body = request.read().decode()
    assert '"chat_id":"-1001"' in body.replace(" ", "")
    assert "14:05:20 IST" in body
    assert "parse_mode" not in body  # a model-written caption must not be parsed as markup


@pytest.mark.parametrize("code", [400, 401, 429, 500])
async def test_a_telegram_error_status_raises_with_the_code_only(code: int) -> None:
    with pytest.raises(NotifierError) as caught:
        await telegram(lambda _r: httpx.Response(code)).send(notice())
    assert str(caught.value) == f"telegram answered {code}"
    assert TOKEN not in str(caught.value)


async def test_a_telegram_network_error_never_leaks_the_token() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    with pytest.raises(NotifierError) as caught:
        await telegram(boom).send(notice())
    assert TOKEN not in str(caught.value)
    assert "ConnectError" in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


# --- dispatcher ----------------------------------------------------------------------------------


class Recorder:
    def __init__(self, name: str) -> None:
        self.name = name
        self.sent: list[AlertNotice] = []

    async def send(self, n: AlertNotice) -> None:
        self.sent.append(n)


class Broken:
    def __init__(self, name: str, error: Exception) -> None:
        self.name, self._error = name, error

    async def send(self, n: AlertNotice) -> None:
        raise self._error


class Hanging:
    name = "hanging"

    async def send(self, n: AlertNotice) -> None:
        await asyncio.sleep(3600)


async def test_every_channel_receives_the_notice() -> None:
    a, b = Recorder("a"), Recorder("b")
    outcome = await NotificationDispatcher([a, b]).dispatch(notice())
    assert outcome == {"a": "ok", "b": "ok"}
    assert len(a.sent) == len(b.sent) == 1


async def test_no_channels_is_a_no_op() -> None:
    assert await NotificationDispatcher([]).dispatch(notice()) == {}


async def test_a_failing_channel_does_not_stop_the_others() -> None:
    good = Recorder("good")
    outcome = await NotificationDispatcher([Broken("bad", RuntimeError("down")), good]).dispatch(
        notice()
    )
    assert outcome == {"bad": "error", "good": "ok"}
    assert len(good.sent) == 1


async def test_a_hanging_channel_times_out_and_the_rest_still_finish() -> None:
    good = Recorder("good")
    started = asyncio.get_running_loop().time()
    outcome = await NotificationDispatcher([Hanging(), good], timeout_s=0.1).dispatch(notice())
    assert outcome == {"hanging": "timeout", "good": "ok"}
    assert asyncio.get_running_loop().time() - started < 2  # bounded by the timeout, not 3600 s


async def test_channels_run_concurrently_not_one_after_another() -> None:
    class Slow:
        def __init__(self, name: str) -> None:
            self.name = name

        async def send(self, n: AlertNotice) -> None:
            await asyncio.sleep(0.3)

    loop = asyncio.get_running_loop()
    started = loop.time()
    await NotificationDispatcher([Slow("a"), Slow("b"), Slow("c")]).dispatch(notice())
    assert loop.time() - started < 0.8  # ~0.3 s, not ~0.9 s


async def test_cancellation_is_not_swallowed() -> None:
    task = asyncio.create_task(NotificationDispatcher([Hanging()], timeout_s=60).dispatch(notice()))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_outcomes_are_counted_per_channel() -> None:
    before = {
        (c, r): sample("vms_api_notifications_total", channel=c, result=r)
        for c, r in (("ok-ch", "ok"), ("err-ch", "error"), ("slow-ch", "timeout"))
    }
    slow = Hanging()
    slow.name = "slow-ch"  # type: ignore[misc]
    await NotificationDispatcher(
        [Recorder("ok-ch"), Broken("err-ch", ValueError("x")), slow], timeout_s=0.05
    ).dispatch(notice())
    for (channel, result), was in before.items():
        assert sample("vms_api_notifications_total", channel=channel, result=result) == was + 1


async def test_a_failure_is_logged_without_the_exception_text() -> None:
    with capture_logs() as logs:
        await NotificationDispatcher(
            [Broken("leaky", RuntimeError(f"POST https://api.telegram.org/bot{TOKEN}/sendMessage"))]
        ).dispatch(notice())
    failed = [e for e in logs if e["event"] == "notification_failed"]
    assert len(failed) == 1
    assert failed[0]["channel"] == "leaky" and failed[0]["error"] == "RuntimeError"
    assert TOKEN not in repr(logs)


async def test_a_notifier_errors_own_sanitised_message_is_logged() -> None:
    with capture_logs() as logs:
        await NotificationDispatcher(
            [Broken("tg", NotifierError("telegram answered 401"))]
        ).dispatch(notice())
    failed = [e for e in logs if e["event"] == "notification_failed"]
    assert failed[0]["detail"] == "telegram answered 401"


# --- registry ------------------------------------------------------------------------------------


async def _noop(_m: WsMessage) -> None: ...


def test_the_default_is_the_dashboard_channel_only() -> None:
    assert [n.name for n in build_notifiers(settings(), publish=_noop)] == ["dashboard"]


def test_channels_are_built_in_the_order_named_each_once() -> None:
    cfg = email_settings(channels="email,dashboard,email")
    assert [n.name for n in build_notifiers(cfg, publish=_noop)] == ["email", "dashboard"]


def test_all_three_channels_can_be_enabled() -> None:
    cfg = email_settings(
        channels="dashboard,email,telegram", telegram_bot_token=TOKEN, telegram_chat_id="-1"
    )
    dispatcher = build_dispatcher(cfg, publish=_noop)
    assert dispatcher.channels == ["dashboard", "email", "telegram"]


def test_an_empty_channel_list_builds_a_dispatcher_that_sends_nothing() -> None:
    assert build_dispatcher(settings(channels=""), publish=_noop).channels == []
