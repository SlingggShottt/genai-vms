"""The email and Telegram channels over real sockets (P3-J3, FR-ALR-03): a tiny SMTP server and a
tiny HTTP server on 127.0.0.1 stand in for the providers, so `smtplib` and `httpx` really do their
I/O. Nothing leaves the machine."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from email import message_from_bytes
from email.policy import default
from typing import Any

import pytest
from api.notifiers import AlertNotice, NotifierError
from api.notifiers.email_notifier import EmailNotifier
from api.notifiers.telegram import TelegramNotifier
from api.settings import NotifySettings

TOKEN = "123456:secret-bot-token"  # noqa: S105 - fixture value


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "VMS_NOTIFY_CHANNELS", "VMS_NOTIFY_SMTP_HOST", "VMS_NOTIFY_EMAIL_FROM",
        "VMS_NOTIFY_EMAIL_TO", "VMS_NOTIFY_TELEGRAM_BOT_TOKEN", "VMS_NOTIFY_TELEGRAM_CHAT_ID",
    ):  # fmt: skip
        monkeypatch.delenv(name, raising=False)


def notice() -> AlertNotice:
    return AlertNotice(
        alert_id="0198f2a0-0000-7000-8000-000000000001",
        title="Intrusion on cam02",
        severity="high",
        event_type="intrusion",
        camera_code="cam02",
        caption="A person climbs the north fence.",
        start_ts=datetime(2026, 10, 3, 8, 35, 20, tzinfo=UTC),
        payload={},
    )


# --- a minimal SMTP server -----------------------------------------------------------------------


class SmtpSink:
    def __init__(self) -> None:
        self.sender: str | None = None
        self.recipients: list[str] = []
        self.raw: bytes = b""
        self.commands: list[str] = []
        self.reject_data = False

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async def say(line: str) -> None:
            writer.write(line.encode() + b"\r\n")
            await writer.drain()

        await say("220 sink ESMTP")
        while line := await reader.readline():
            command = line.decode().strip()
            verb = command.upper()
            self.commands.append(verb.split(" ")[0])
            if verb.startswith(("EHLO", "HELO")):
                await say("250 sink")  # no STARTTLS and no AUTH offered
            elif verb.startswith("MAIL FROM"):
                self.sender = command.split(":", 1)[1].strip().strip("<>")
                await say("250 ok")
            elif verb.startswith("RCPT TO"):
                self.recipients.append(command.split(":", 1)[1].strip().strip("<>"))
                await say("250 ok")
            elif verb == "DATA":
                if self.reject_data:
                    await say("554 transaction failed")
                    continue
                await say("354 go ahead")
                body = b""
                while not body.endswith(b"\r\n.\r\n"):
                    body += await reader.readline()
                self.raw = body[: -len(b"\r\n.\r\n")]
                await say("250 queued")
            elif verb == "QUIT":
                await say("221 bye")
                break
            else:
                await say("250 ok")
        writer.close()


@pytest.fixture
async def smtp() -> AsyncIterator[tuple[SmtpSink, int]]:
    sink = SmtpSink()
    server = await asyncio.start_server(sink.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield sink, port
    finally:
        server.close()
        await server.wait_closed()


def email_settings(port: int, **kw: Any) -> NotifySettings:
    base: dict[str, Any] = {
        "channels": "email",
        "smtp_host": "127.0.0.1",
        "smtp_port": port,
        "smtp_starttls": False,
        "email_from": "vms@example.test",
        "email_to": "ops@example.test, soc@example.test",
        "timeout_seconds": 5,
    }
    return NotifySettings(_env_file=None, **(base | kw))


async def test_an_email_is_really_delivered_over_smtp(smtp) -> None:
    sink, port = smtp

    await EmailNotifier(email_settings(port)).send(notice())

    assert sink.sender == "vms@example.test"
    assert sink.recipients == ["ops@example.test", "soc@example.test"]
    assert sink.commands[-1] == "QUIT"  # a clean session
    message = message_from_bytes(sink.raw, policy=default)
    assert message["Subject"] == "[HIGH] Intrusion on cam02"
    assert message["From"] == "vms@example.test"
    body = message.get_content()
    assert "03 Oct 2026, 14:05:20 IST" in body and "A person climbs the north fence." in body


async def test_an_smtp_server_that_refuses_the_message_is_a_notifier_error(smtp) -> None:
    sink, port = smtp
    sink.reject_data = True
    with pytest.raises(NotifierError, match="SMTPDataError"):
        await EmailNotifier(email_settings(port)).send(notice())


async def test_an_smtp_server_that_is_not_there_is_a_notifier_error() -> None:
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()  # the port is now closed
    with pytest.raises(NotifierError, match="ConnectionRefusedError"):
        await EmailNotifier(email_settings(port)).send(notice())


# --- a minimal HTTP server -----------------------------------------------------------------------


class HttpSink:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[tuple[str, dict[str, str], bytes]] = []

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request_line = (await reader.readline()).decode().strip()
        headers: dict[str, str] = {}
        while (line := (await reader.readline()).decode().strip()) != "":
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        body = await reader.readexactly(int(headers.get("content-length", "0")))
        self.requests.append((request_line, headers, body))
        payload = b'{"ok": true}'
        writer.write(
            f"HTTP/1.1 {self.status} X\r\ncontent-type: application/json\r\n"
            f"content-length: {len(payload)}\r\nconnection: close\r\n\r\n".encode()
            + payload
        )
        await writer.drain()
        writer.close()


@pytest.fixture
async def http() -> AsyncIterator[Callable[[int], Awaitable[tuple[HttpSink, str]]]]:
    servers: list[asyncio.Server] = []

    async def start(status: int = 200) -> tuple[HttpSink, str]:
        sink = HttpSink(status)
        server = await asyncio.start_server(sink.handle, "127.0.0.1", 0)
        servers.append(server)
        return sink, f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"

    try:
        yield start
    finally:
        for server in servers:
            server.close()
            await server.wait_closed()


def telegram_settings() -> NotifySettings:
    return NotifySettings(
        _env_file=None,
        channels="telegram",
        telegram_bot_token=TOKEN,
        telegram_chat_id="-1001",
        timeout_seconds=5,
    )


async def test_a_telegram_message_is_really_posted(http) -> None:
    sink, base = await http(200)

    await TelegramNotifier(telegram_settings(), api_base=base).send(notice())

    ((request_line, headers, body),) = sink.requests
    assert request_line.startswith(f"POST /bot{TOKEN}/sendMessage ")
    assert headers["content-type"].startswith("application/json")
    sent = json.loads(body)
    assert sent["chat_id"] == "-1001" and "14:05:20 IST" in sent["text"]
    assert "parse_mode" not in sent


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_a_telegram_error_status_is_a_notifier_error_without_the_token(
    http, status: int
) -> None:
    _sink, base = await http(status)
    with pytest.raises(NotifierError) as caught:
        await TelegramNotifier(telegram_settings(), api_base=base).send(notice())
    assert str(caught.value) == f"telegram answered {status}"
    assert TOKEN not in str(caught.value)


async def test_telegram_being_unreachable_is_a_notifier_error_without_the_token() -> None:
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    with pytest.raises(NotifierError) as caught:
        await TelegramNotifier(telegram_settings(), api_base=f"http://127.0.0.1:{port}").send(
            notice()
        )
    assert "ConnectError" in str(caught.value) and TOKEN not in str(caught.value)
    assert caught.value.__cause__ is None
