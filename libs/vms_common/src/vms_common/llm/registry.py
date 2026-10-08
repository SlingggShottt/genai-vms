"""Model registry: `config/models.yaml` → per-task model choice for the active profile.

Shape of the file (design_architecture.md §11.2, plus a `tasks:` block):

    tasks:                    # provider-independent behaviour of each task
      event_verify: {modality: vision, max_tokens: 400, max_images: 4, cache_ttl_s: 86400}
    profiles:                 # which model serves each task
      local:  {event_verify: {provider: ollama, model: "qwen2.5vl:3b"}, ...}
      hybrid: {extends: local, rerank: {provider: gemini, model: ..., fallback: [groq/...]}}
    evaluation:
      judge: {provider: groq, model: ...}

A profile entry replaces its parent's entry for that task as a whole (no field-wise
merge, so a provider-specific field such as `keep_alive` can never leak onto a cloud
model). Every profile must cover every task and nothing else: that is checked for all
three profiles at load time, so a typo stops the service at startup rather than the
first request that happens to use it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vms_common.llm.errors import LLMRequestError, ModelRegistryError

Provider = Literal["ollama", "gemini", "groq", "openrouter", "hf_local"]
PROVIDERS: tuple[str, ...] = ("ollama", "gemini", "groq", "openrouter", "hf_local")
GPU_PROVIDERS = frozenset({"ollama", "hf_local"})  # run on the leased GPU
PROFILES: tuple[str, ...] = ("local", "hybrid", "cloud")

# The evaluation judge is reachable through the gateway like any other task.
JUDGE_TASK = "eval_judge"

# Per-provider call timeout when a task does not set one: a local 3B model may have to
# load from disk first; a hosted API that has not answered in 30 s is not going to.
DEFAULT_TIMEOUT_S: dict[str, float] = {
    "ollama": 120.0,
    "hf_local": 180.0,
    "gemini": 30.0,
    "groq": 30.0,
    "openrouter": 45.0,
}


class ModelRef(BaseModel):
    """One concrete model on one provider."""

    model_config = ConfigDict(frozen=True)

    provider: Provider
    model: str  # for hf_local: the base model id
    adapter: str | None = None  # hf_local only: LoRA adapter URI
    keep_alive: str | None = None  # ollama only: how long to keep the model loaded
    num_ctx: int | None = None  # ollama only: context window (prompt + images + reply), tokens

    @property
    def needs_gpu(self) -> bool:
        return self.provider in GPU_PROVIDERS

    @property
    def family(self) -> str:
        """What the GPU lease arbitrates between. hf_local adapters share their base's
        family: swapping a LoRA adapter does not reload the base model."""
        return f"{self.provider}:{self.model}"

    @property
    def litellm_model(self) -> str:
        """The `model=` string LiteLLM wants. `ollama_chat/` (not `ollama/`) is the route
        that supports chat messages, images, tools and JSON-schema output."""
        if self.provider == "ollama":
            return f"ollama_chat/{self.model}"
        return f"{self.provider}/{self.model}"

    def label(self) -> str:
        return f"{self.provider}/{self.model}"


class TaskConfig(BaseModel):
    """A task as the gateway runs it: models in order of preference + behaviour."""

    task: str
    modality: Literal["text", "vision"] = "text"
    primary: ModelRef
    fallbacks: list[ModelRef] = Field(default_factory=list)
    timeout_s: float | None = None  # None → DEFAULT_TIMEOUT_S[provider] of each candidate
    temperature: float = Field(default=0.0, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)
    max_images: int = Field(default=4, gt=0)  # CLAUDE.md: cap frames for VLM calls
    max_image_edge: int = Field(default=448, gt=0)  # px, long edge — ditto pixels
    cache_ttl_s: int = Field(default=0, ge=0)  # 0 = never cache this task
    validation_retries: int = Field(default=2, ge=0)  # extra tries after invalid output

    @property
    def candidates(self) -> list[ModelRef]:
        return [self.primary, *self.fallbacks]

    def timeout_for(self, ref: ModelRef) -> float:
        return self.timeout_s if self.timeout_s is not None else DEFAULT_TIMEOUT_S[ref.provider]


# --- raw YAML shapes (validated strictly so unknown keys are typos, not silent no-ops) ---


class _Behaviour(BaseModel):
    """Fields allowed both in `tasks:` and, as overrides, in a profile entry."""

    model_config = ConfigDict(extra="forbid")

    timeout_s: float | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)
    max_images: int | None = Field(default=None, gt=0)
    max_image_edge: int | None = Field(default=None, gt=0)
    cache_ttl_s: int | None = Field(default=None, ge=0)
    validation_retries: int | None = Field(default=None, ge=0)


class _TaskDefaults(_Behaviour):
    modality: Literal["text", "vision"] = "text"


class _FallbackDict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Provider
    model: str
    keep_alive: str | None = None
    num_ctx: int | None = Field(default=None, gt=0)


class _Entry(_Behaviour):
    """One `profiles.<name>.<task>` entry."""

    provider: Provider
    model: str | None = None
    base: str | None = None  # hf_local spelling of `model`
    adapter: str | None = None
    keep_alive: str | None = None
    num_ctx: int | None = Field(default=None, gt=0)
    fallback: list[str | _FallbackDict] = Field(default_factory=list)

    @model_validator(mode="after")
    def _provider_fields_agree(self) -> _Entry:
        if self.provider == "hf_local":
            if self.model is not None:
                raise ValueError("hf_local names its model with `base:`, not `model:`")
            if not self.base:
                raise ValueError("hf_local needs `base:` (the base model id)")
            if self.keep_alive is not None or self.num_ctx is not None:
                raise ValueError("`keep_alive` and `num_ctx` only apply to ollama")
        else:
            if not self.model:
                raise ValueError(f"{self.provider} needs `model:`")
            if self.base is not None or self.adapter is not None:
                raise ValueError("`base`/`adapter` only apply to hf_local")
            if self.provider != "ollama" and (
                self.keep_alive is not None or self.num_ctx is not None
            ):
                raise ValueError("`keep_alive` and `num_ctx` only apply to ollama")
        return self


def _only_ollama_options(item: _FallbackDict) -> None:
    if item.provider != "ollama" and (item.keep_alive is not None or item.num_ctx is not None):
        raise ValueError("`keep_alive` and `num_ctx` only apply to ollama")


def _parse_fallback(item: str | _FallbackDict) -> ModelRef:
    if isinstance(item, _FallbackDict):
        _only_ollama_options(item)
        return ModelRef(
            provider=item.provider,
            model=item.model,
            keep_alive=item.keep_alive,
            num_ctx=item.num_ctx,
        )
    provider, sep, model = item.partition("/")  # model ids may contain "/" (openrouter)
    if not sep or not model or provider not in PROVIDERS or provider == "hf_local":
        raise ValueError(
            f"fallback {item!r} must look like '<provider>/<model>' with provider one of "
            f"{[p for p in PROVIDERS if p != 'hf_local']}"
        )
    return ModelRef(provider=provider, model=model)  # type: ignore[arg-type]


def _entry_to_task(task: str, defaults: _TaskDefaults, entry: _Entry) -> TaskConfig:
    # An entry's own value wins; an unset (None) one falls back to the task's default, and
    # a field neither sets keeps TaskConfig's built-in default.
    behaviour: dict[str, Any] = {}
    for key in _Behaviour.model_fields:
        value = getattr(entry, key)
        if value is None:
            value = getattr(defaults, key)
        if value is not None:
            behaviour[key] = value
    if entry.provider == "hf_local":
        primary = ModelRef(provider="hf_local", model=entry.base or "", adapter=entry.adapter)
    else:
        primary = ModelRef(
            provider=entry.provider,
            model=entry.model or "",
            keep_alive=entry.keep_alive,
            num_ctx=entry.num_ctx,
        )
    return TaskConfig(
        task=task,
        modality=defaults.modality,
        primary=primary,
        fallbacks=[_parse_fallback(f) for f in entry.fallback],
        **behaviour,
    )


class ModelRegistry:
    """The resolved registry for every profile, with one profile active."""

    def __init__(self, profiles: dict[str, dict[str, TaskConfig]], *, profile: str) -> None:
        if profile not in profiles:
            raise ModelRegistryError(f"unknown profile {profile!r}; expected one of {PROFILES}")
        self._profiles = profiles
        self.profile = profile

    @classmethod
    def from_file(cls, path: str | Path, *, profile: str) -> ModelRegistry:
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ModelRegistryError(f"cannot read model registry {path}: {exc}") from exc
        return cls.from_dict(raw, profile=profile)

    @classmethod
    def from_dict(cls, raw: object, *, profile: str) -> ModelRegistry:
        if not isinstance(raw, dict):
            raise ModelRegistryError("model registry must be a mapping")
        unknown = set(raw) - {"tasks", "profiles", "evaluation"}
        if unknown:
            raise ModelRegistryError(f"unknown top-level keys: {sorted(unknown)}")
        task_defaults = _load_tasks(raw.get("tasks"))
        raw_profiles = raw.get("profiles")
        if not isinstance(raw_profiles, dict) or set(raw_profiles) != set(PROFILES):
            raise ModelRegistryError(f"`profiles:` must define exactly {list(PROFILES)}")

        judge = _load_judge(raw.get("evaluation"))
        profiles: dict[str, dict[str, TaskConfig]] = {}
        for name in PROFILES:
            entries = _resolve_profile(name, raw_profiles, task_defaults)
            if judge is not None:
                entries[JUDGE_TASK] = judge
            profiles[name] = entries
        return cls(profiles, profile=profile)

    def task(self, name: str, *, profile: str | None = None) -> TaskConfig:
        tasks = self._profiles[profile or self.profile]
        try:
            return tasks[name]
        except KeyError:
            raise LLMRequestError(
                f"unknown task {name!r} (profile {profile or self.profile}); known: {sorted(tasks)}"
            ) from None

    def uses_provider(self, provider: str) -> bool:
        """Whether any task of the active profile names `provider` (primary or fallback)."""
        return any(
            ref.provider == provider
            for task in self._profiles[self.profile].values()
            for ref in task.candidates
        )

    def task_names(self) -> list[str]:
        return sorted(self._profiles[self.profile])

    def with_profile(self, profile: str) -> ModelRegistry:
        return ModelRegistry(self._profiles, profile=profile)


def _fail(where: str, exc: ValidationError | ValueError) -> ModelRegistryError:
    if isinstance(exc, ValidationError):
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<entry>'}: {e['msg']}"
            for e in exc.errors(include_input=False, include_url=False)
        )
    else:
        detail = str(exc)
    return ModelRegistryError(f"{where}: {detail}")


def _load_tasks(raw: object) -> dict[str, _TaskDefaults]:
    if not isinstance(raw, dict) or not raw:
        raise ModelRegistryError("`tasks:` must be a non-empty mapping of task name → settings")
    out: dict[str, _TaskDefaults] = {}
    for name, body in raw.items():
        if name == JUDGE_TASK:
            raise ModelRegistryError(f"{JUDGE_TASK!r} is reserved for evaluation.judge")
        try:
            out[str(name)] = _TaskDefaults.model_validate(body or {})
        except ValidationError as exc:
            raise _fail(f"tasks.{name}", exc) from exc
    return out


def _load_judge(raw: object) -> TaskConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {"judge"}:
        raise ModelRegistryError("`evaluation:` must contain exactly `judge:`")
    try:
        entry = _Entry.model_validate(raw["judge"])
        return _entry_to_task(JUDGE_TASK, _TaskDefaults(), entry)
    except (ValidationError, ValueError) as exc:
        raise _fail("evaluation.judge", exc) from exc


def _resolve_profile(
    name: str, raw_profiles: dict[str, Any], defaults: dict[str, _TaskDefaults]
) -> dict[str, TaskConfig]:
    chain: list[str] = []
    cursor: str | None = name
    while cursor is not None:
        if cursor in chain:
            raise ModelRegistryError(f"profile `extends` cycle: {' → '.join([*chain, cursor])}")
        body = raw_profiles.get(cursor)
        if not isinstance(body, dict):
            raise ModelRegistryError(f"profile {cursor!r} must be a mapping of task → model")
        chain.append(cursor)
        parent = body.get("extends")
        if parent is not None and parent not in PROFILES:
            raise ModelRegistryError(f"profile {cursor!r} extends unknown profile {parent!r}")
        cursor = parent

    entries: dict[str, Any] = {}
    for ancestor in reversed(chain):  # root first, so children override
        for task, entry in raw_profiles[ancestor].items():
            if task != "extends":
                entries[str(task)] = entry

    unknown = sorted(set(entries) - set(defaults))
    if unknown:
        raise ModelRegistryError(
            f"profile {name!r} has entries for tasks not declared under `tasks:`: {unknown}"
        )
    missing = sorted(set(defaults) - set(entries))
    if missing:
        raise ModelRegistryError(f"profile {name!r} has no model for task(s) {missing}")

    resolved: dict[str, TaskConfig] = {}
    for task, entry in entries.items():
        where = f"profiles.{name}.{task}"
        try:
            resolved[task] = _entry_to_task(task, defaults[task], _Entry.model_validate(entry))
        except (ValidationError, ValueError) as exc:
            raise _fail(where, exc) from exc
    return resolved
