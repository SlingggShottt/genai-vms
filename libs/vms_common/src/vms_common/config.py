"""Typed configuration via pydantic-settings (style_guide.md §A.1).

Business code never reads `os.environ` directly — every service composes
its `Settings` from these blocks in its own `settings.py`. Env vars follow
`VMS_<AREA>_<NAME>` (style_guide.md §A.1 naming table); each block below
owns one `VMS_<AREA>_` prefix.

Composition pattern — nest these as fields with a `default_factory`, and
each nested settings object independently reads its own prefixed env vars:

    class Settings(VMSBaseSettings):
        kafka: KafkaSettings = Field(default_factory=KafkaSettings)
        storage: StorageSettings = Field(default_factory=StorageSettings)
"""

from __future__ import annotations

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class VMSBaseSettings(BaseSettings):
    """Common base every settings class should inherit."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


class KafkaSettings(VMSBaseSettings):
    """Kafka connection settings — `VMS_KAFKA_*` (design_architecture.md §5.1)."""

    model_config = SettingsConfigDict(env_prefix="VMS_KAFKA_", env_file=".env", extra="ignore")

    bootstrap_servers: str = Field(default="localhost:9092")
    consumer_group_prefix: str = Field(default="vms")
    dlq_topic: str = Field(default="vms.dlq.v1")


class StorageSettings(VMSBaseSettings):
    """S3-compatible object storage settings — `VMS_STORAGE_*`."""

    model_config = SettingsConfigDict(env_prefix="VMS_STORAGE_", env_file=".env", extra="ignore")

    endpoint_url: str = Field(default="http://localhost:9000")
    access_key: str = Field(default="")
    secret_key: str = Field(default="")
    region: str = Field(default="us-east-1")
    # NFR-SEC-02: presigned URLs must expire within 15 minutes. The upper
    # bound is enforced here so a bad env value fails fast at startup.
    presign_expiry_seconds: int = Field(default=900, gt=0, le=900)


class RedisSettings(VMSBaseSettings):
    """Redis settings — `VMS_REDIS_*` (GPU lease, LLM cache, WS pub/sub, tracker checkpoints)."""

    model_config = SettingsConfigDict(env_prefix="VMS_REDIS_", env_file=".env", extra="ignore")

    url: str = Field(default="redis://localhost:6379/0")


class QdrantSettings(VMSBaseSettings):
    """Qdrant vector store settings — `VMS_QDRANT_*` (design_architecture.md §6.2)."""

    model_config = SettingsConfigDict(env_prefix="VMS_QDRANT_", env_file=".env", extra="ignore")

    url: str = Field(default="http://localhost:6333")
    api_key: str = Field(default="")


class DatabaseSettings(VMSBaseSettings):
    """PostgreSQL connection settings — `VMS_DB_*` (design_architecture.md §6.1).

    `dsn` uses the `asyncpg` driver (style_guide.md §A.1: async all the way).
    """

    model_config = SettingsConfigDict(env_prefix="VMS_DB_", env_file=".env", extra="ignore")

    dsn: str = Field(default="postgresql+asyncpg://vms:vms@localhost:5432/vms")
    pool_size: int = Field(default=5, gt=0)
    max_overflow: int = Field(default=10, ge=0)
    echo: bool = Field(default=False)


class JWTSettings(VMSBaseSettings):
    """JWT signing settings — `VMS_JWT_*` (design_architecture.md §15: HS256
    dev, RS256 option later). `secret` has no safe default — callers that
    need a real one must set `VMS_JWT_SECRET`.
    """

    model_config = SettingsConfigDict(env_prefix="VMS_JWT_", env_file=".env", extra="ignore")

    secret: str = Field(default="")
    algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=15, gt=0)  # FR-AUTH-01
    refresh_token_expire_days: int = Field(default=7, gt=0)  # FR-AUTH-01


class LLMProfileSettings(VMSBaseSettings):
    """LLM profile switch — `VMS_LLM_PROFILE` (D-08, FR-CFG-02)."""

    model_config = SettingsConfigDict(env_prefix="VMS_LLM_", env_file=".env", extra="ignore")

    profile: str = Field(default="local", pattern="^(local|hybrid|cloud)$")


class LLMSettings(LLMProfileSettings):
    """Everything the LLM gateway reads from the environment — `VMS_LLM_*`.

    The provider keys keep the names LiteLLM and the provider docs use
    (`GEMINI_API_KEY`, ...) and are also accepted as `VMS_LLM_<NAME>`
    (FR-CFG-03: keys come from env/secrets only). They are `SecretStr` so a
    stray `repr(settings)` or log line never prints one.
    """

    # The aliased fields below are also settable by field name (`LLMSettings(genai_host=...)`),
    # which pydantic otherwise ignores silently for a field with a validation_alias.
    model_config = SettingsConfigDict(populate_by_name=True)

    models_path: str = Field(default="config/models.yaml", description="Model registry file")

    # Where Ollama listens. The two-laptop demo sets VMS_GENAI_HOST on the machine that
    # does not run Ollama itself (design_architecture.md §11.3); VMS_LLM_OLLAMA_URL wins.
    ollama_url: str | None = Field(default=None, description="e.g. http://laptop-b:11434")
    genai_host: str = Field(
        default="localhost",
        validation_alias=AliasChoices("VMS_LLM_GENAI_HOST", "VMS_GENAI_HOST"),
    )

    gemini_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("VMS_LLM_GEMINI_API_KEY", "GEMINI_API_KEY"),
    )
    groq_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("VMS_LLM_GROQ_API_KEY", "GROQ_API_KEY"),
    )
    openrouter_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("VMS_LLM_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"),
    )

    # GPU lease (design_architecture.md §11.3): one lease per GPU node.
    lease_node: str = Field(default="local", description="Names the GPU this process leases")
    lease_ttl_seconds: float = Field(
        default=30.0, gt=0, description="Holder expires unless renewed"
    )
    lease_wait_seconds: float = Field(
        default=120.0, ge=0, description="How long a call queues for the GPU before giving up"
    )

    @property
    def effective_ollama_url(self) -> str:
        return self.ollama_url or f"http://{self.genai_host}:11434"
