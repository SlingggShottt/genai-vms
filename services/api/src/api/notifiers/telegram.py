"""The Telegram channel (Bot API `sendMessage`). Off unless `VMS_NOTIFY_CHANNELS` names it.

The bot token is part of the request URL, so no exception or log line from here may carry the
URL: every failure is re-raised as a `NotifierError` that names only the status or error type.
"""

from __future__ import annotations

import httpx

from api.notifiers.base import AlertNotice, NotifierError, body_text
from api.settings import NotifySettings

API_BASE = "https://api.telegram.org"


class TelegramNotifier:
    name = "telegram"

    def __init__(
        self,
        settings: NotifySettings,
        *,
        client: httpx.AsyncClient | None = None,
        api_base: str = API_BASE,
    ) -> None:
        self._settings = settings
        self._client = client
        self._api_base = api_base.rstrip("/")

    async def send(self, notice: AlertNotice) -> None:
        s = self._settings
        url = f"{self._api_base}/bot{s.telegram_bot_token.get_secret_value()}/sendMessage"
        body = {
            "chat_id": s.telegram_chat_id,
            "text": body_text(notice),
            "disable_web_page_preview": True,
        }
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=s.timeout_seconds)
        try:
            response = await client.post(url, json=body)
        except httpx.HTTPError as exc:
            raise NotifierError(f"telegram request failed ({type(exc).__name__})") from None
        finally:
            if owns_client:
                await client.aclose()
        if response.status_code >= 300:
            raise NotifierError(f"telegram answered {response.status_code}")
