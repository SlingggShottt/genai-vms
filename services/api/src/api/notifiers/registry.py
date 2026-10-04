"""Build the enabled channels from settings (`VMS_NOTIFY_CHANNELS`)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from api.notifiers.base import Notifier
from api.notifiers.dashboard import DashboardNotifier
from api.notifiers.dispatcher import NotificationDispatcher
from api.notifiers.email_notifier import EmailNotifier
from api.notifiers.telegram import TelegramNotifier
from api.realtime.messages import WsMessage
from api.settings import NotifySettings


def build_notifiers(
    settings: NotifySettings, *, publish: Callable[[WsMessage], Awaitable[None]]
) -> list[Notifier]:
    """In the order named, each at most once. `NotifySettings` has already rejected unknown
    names and missing credentials."""
    notifiers: list[Notifier] = []
    for channel in dict.fromkeys(settings.enabled_channels):
        if channel == "dashboard":
            notifiers.append(DashboardNotifier(publish))
        elif channel == "email":
            notifiers.append(EmailNotifier(settings))
        elif channel == "telegram":
            notifiers.append(TelegramNotifier(settings))
    return notifiers


def build_dispatcher(
    settings: NotifySettings, *, publish: Callable[[WsMessage], Awaitable[None]]
) -> NotificationDispatcher:
    return NotificationDispatcher(
        build_notifiers(settings, publish=publish), timeout_s=settings.timeout_seconds
    )
