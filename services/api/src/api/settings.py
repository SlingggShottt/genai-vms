"""pydantic-settings configuration for api.

Config is read only through vms_common.config settings classes — never
os.environ directly (docs/style_guide.md §A.1).
"""

from __future__ import annotations

from typing import Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import SettingsConfigDict
from vms_common.config import (
    DatabaseSettings,
    JWTSettings,
    KafkaSettings,
    RedisSettings,
    StorageSettings,
    VMSBaseSettings,
)

NOTIFY_CHANNELS = ("dashboard", "email", "telegram")


class AdminSeedSettings(VMSBaseSettings):
    """Seed admin account — `VMS_ADMIN_*` (P1-J2, FR-AUTH-04). Created on
    first start if no user with this email exists yet; see
    `api.adapters.users.seed_admin_user`.
    """

    model_config = SettingsConfigDict(env_prefix="VMS_ADMIN_", env_file=".env", extra="ignore")

    email: str = Field(default="admin@genai-vms.dev")
    password: str = Field(default="")

    @field_validator("password")
    @classmethod
    def _password_meets_the_same_floor_as_every_other_account(cls, value: str) -> str:
        # Empty means "don't seed" (seed_admin_user's own no-op check) — the
        # one value this field allows despite the floor. Anything else must
        # meet the same bar UserCreateRequest enforces for every other
        # account; the admin is the highest-privilege one, not an exception.
        if value and len(value) < 8:
            raise ValueError(
                "VMS_ADMIN_PASSWORD must be empty (skip seeding) or at least 8 characters."
            )
        return value

    @model_validator(mode="after")
    def _seeded_admin_email_must_be_able_to_log_in(self) -> AdminSeedSettings:
        # POST /auth/login validates the email with `EmailStr`, which rejects
        # reserved/special-use domains (.local, .test, .invalid, ...). Seeding
        # such an address would create an admin nobody can ever log in as —
        # and the 400 at login gives no hint why — so fail at startup instead.
        # Only checked when seeding is enabled (a non-empty password).
        if self.password:
            try:
                validate_email(self.email, check_deliverability=False)
            except EmailNotValidError as exc:
                raise ValueError(
                    f"VMS_ADMIN_EMAIL {self.email!r} cannot be used to log in ({exc}). "
                    "Use a normal domain, e.g. admin@genai-vms.dev."
                ) from exc
        return self


class AlertSettings(VMSBaseSettings):
    """`VMS_ALERTS_*` — which events become alerts and how they reach the api (P3-J3)."""

    model_config = SettingsConfigDict(env_prefix="VMS_ALERTS_", env_file=".env", extra="ignore")

    # FR-ALR-01: "verified events at or above a configured severity". Lower-severity events
    # are still stored and searchable; they just do not interrupt anyone.
    min_severity: Literal["low", "medium", "high", "critical"] = Field(default="medium")
    # An event that ended longer ago than this still becomes an alert (the history is real) but
    # is not announced: a fresh consumer group replays the whole topic, and that must not email
    # or pop up a month of old incidents.
    notify_max_age_seconds: float = Field(default=900.0, gt=0)
    # The api consumes event.v1 / correlation.v1 itself; switch off for an api replica that
    # should only serve HTTP/WS, or for tests that have no Kafka.
    consumers_enabled: bool = Field(default=True)
    events_topic: str = Field(default="vms.events.v1")
    correlations_topic: str = Field(default="vms.correlations.v1")
    events_group: str = Field(default="api-alerts")
    correlations_group: str = Field(default="api-alerts-correlations")
    # Messages a WebSocket client may have waiting; a client further behind than this is
    # disconnected (it reconnects and refetches) rather than buffered without bound.
    ws_queue_size: int = Field(default=100, gt=0)


class NotifySettings(VMSBaseSettings):
    """`VMS_NOTIFY_*` — notification channels (FR-ALR-03). `dashboard` (the WebSocket push) is
    on by default; `email` and `telegram` are implemented but off until named in `channels`.

    Choosing a channel without its credentials is a startup error, not a notification that
    silently never goes out.
    """

    model_config = SettingsConfigDict(env_prefix="VMS_NOTIFY_", env_file=".env", extra="ignore")

    channels: str = Field(default="dashboard", description="comma list of dashboard,email,telegram")
    timeout_seconds: float = Field(default=10.0, gt=0)

    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587, gt=0)
    smtp_username: str = Field(default="")
    smtp_password: SecretStr = Field(default=SecretStr(""))
    smtp_starttls: bool = Field(default=True)
    email_from: str = Field(default="")
    email_to: str = Field(default="", description="comma list of recipients")

    telegram_bot_token: SecretStr = Field(default=SecretStr(""))
    telegram_chat_id: str = Field(default="")

    @property
    def enabled_channels(self) -> list[str]:
        return [c.strip().lower() for c in self.channels.split(",") if c.strip()]

    @property
    def email_recipients(self) -> list[str]:
        return [a.strip() for a in self.email_to.split(",") if a.strip()]

    @model_validator(mode="after")
    def _channels_are_known_and_configured(self) -> NotifySettings:
        channels = self.enabled_channels
        unknown = sorted(set(channels) - set(NOTIFY_CHANNELS))
        if unknown:
            raise ValueError(
                f"VMS_NOTIFY_CHANNELS names unknown channel(s) {unknown}; "
                f"known: {list(NOTIFY_CHANNELS)}"
            )
        if "email" in channels:
            missing = [
                name
                for name, value in (
                    ("VMS_NOTIFY_SMTP_HOST", self.smtp_host),
                    ("VMS_NOTIFY_EMAIL_FROM", self.email_from),
                    ("VMS_NOTIFY_EMAIL_TO", self.email_recipients),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"the email channel needs {', '.join(missing)}")
        if "telegram" in channels:
            missing = [
                name
                for name, value in (
                    ("VMS_NOTIFY_TELEGRAM_BOT_TOKEN", self.telegram_bot_token.get_secret_value()),
                    ("VMS_NOTIFY_TELEGRAM_CHAT_ID", self.telegram_chat_id),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"the telegram channel needs {', '.join(missing)}")
        return self


class ApiSettings(VMSBaseSettings):
    """`VMS_API_*` env vars, plus the shared database/JWT blocks."""

    model_config = SettingsConfigDict(env_prefix="VMS_API_", env_file=".env", extra="ignore")

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    # Shared secret internal services present as `Authorization: Bearer
    # <token>` on /internal/* (design_architecture.md §15) — distinct from
    # user JWTs, not itself a JWT. Empty means "reject everything" (see
    # api.api.security.require_service_token), not "accept anything".
    service_token: str = Field(default="")

    # Where the retrieval service listens (`/search*` is proxied there) and how long a search may
    # take: `reason` mode runs a language model over the candidates, which on a 4 GB GPU is slow.
    retrieval_url: str = Field(default="http://localhost:8010")
    search_timeout_seconds: float = Field(default=150.0, gt=0)

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    jwt: JWTSettings = Field(default_factory=JWTSettings)
    admin: AdminSeedSettings = Field(default_factory=AdminSeedSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    alerts: AlertSettings = Field(default_factory=AlertSettings)
    notify: NotifySettings = Field(default_factory=NotifySettings)
