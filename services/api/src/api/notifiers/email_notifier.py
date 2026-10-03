"""The email channel (SMTP). Off unless `VMS_NOTIFY_CHANNELS` names it.

`smtplib` is blocking, so the exchange runs in a worker thread; the socket timeout is what
ends it if the server hangs (cancelling the awaiting task cannot stop a thread).
Port 465 means implicit TLS; otherwise STARTTLS is used when `smtp_starttls` is on.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage

from api.notifiers.base import AlertNotice, NotifierError, body_text, subject_line
from api.settings import NotifySettings

IMPLICIT_TLS_PORT = 465


class EmailNotifier:
    name = "email"

    def __init__(self, settings: NotifySettings) -> None:
        self._settings = settings

    def build_message(self, notice: AlertNotice) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = subject_line(notice)
        message["From"] = self._settings.email_from
        message["To"] = ", ".join(self._settings.email_recipients)
        message.set_content(body_text(notice))
        return message

    async def send(self, notice: AlertNotice) -> None:
        message = self.build_message(notice)
        try:
            await asyncio.to_thread(self._deliver, message)
        except (smtplib.SMTPException, OSError) as exc:
            # The exception text can name the server or the login; the type is enough to act on.
            raise NotifierError(f"smtp delivery failed ({type(exc).__name__})") from None

    def _deliver(self, message: EmailMessage) -> None:
        s = self._settings
        context = ssl.create_default_context()
        if s.smtp_port == IMPLICIT_TLS_PORT:
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                s.smtp_host, s.smtp_port, timeout=s.timeout_seconds, context=context
            )
        else:
            server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.timeout_seconds)
        with server:
            if s.smtp_port != IMPLICIT_TLS_PORT and s.smtp_starttls:
                server.starttls(context=context)
            if s.smtp_username:
                server.login(s.smtp_username, s.smtp_password.get_secret_value())
            server.send_message(message, to_addrs=s.email_recipients)
