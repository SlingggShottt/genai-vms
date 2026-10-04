"""Model registry: the shipped config/models.yaml, and the loader's validation."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import pytest
from vms_common.llm.errors import LLMRequestError, ModelRegistryError
from vms_common.llm.registry import (
    DEFAULT_TIMEOUT_S,
    JUDGE_TASK,
    PROFILES,
    ModelRef,
    ModelRegistry,
)

MODELS_YAML = Path(__file__).resolve().parents[4] / "config" / "models.yaml"


def _base() -> dict[str, Any]:
    """A minimal valid registry; tests copy and break it one way at a time."""
    return {
        "tasks": {
            "see": {"modality": "vision", "max_images": 2, "cache_ttl_s": 60},
            "think": {"max_tokens": 100},
        },
        "profiles": {
            "local": {
                "see": {"provider": "ollama", "model": "vl:3b", "num_ctx": 6144},
                "think": {"provider": "ollama", "model": "txt:3b", "keep_alive": "1m"},
            },
            "hybrid": {
                "extends": "local",
                "think": {
                    "provider": "gemini",
                    "model": "flash",
                    "fallback": ["groq/openai/gpt-oss-120b", "openrouter/vendor/model:free"],
                },
            },
            "cloud": {"extends": "hybrid", "see": {"provider": "gemini", "model": "flash"}},
        },
    }


def _load(raw: dict[str, Any], profile: str = "local") -> ModelRegistry:
    return ModelRegistry.from_dict(raw, profile=profile)


def _broken(mutate) -> dict[str, Any]:
    raw = copy.deepcopy(_base())
    mutate(raw)
    return raw


# --- the shipped file ----------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES)
def test_shipped_models_yaml_loads_for_every_profile(profile: str) -> None:
    registry = ModelRegistry.from_file(MODELS_YAML, profile=profile)
    assert registry.profile == profile
    assert {
        "event_verify", "jit_vqa", "query_decompose", "rerank", "phase_tg", "phase_vr",
        "incident_synthesis", "assistant", "daily_narrative", JUDGE_TASK,
    } <= set(registry.task_names())  # fmt: skip


def test_shipped_local_profile_runs_everything_on_ollama_or_hf_local() -> None:
    registry = ModelRegistry.from_file(MODELS_YAML, profile="local")
    providers = {
        registry.task(t).primary.provider for t in registry.task_names() if t != JUDGE_TASK
    }
    assert providers == {"ollama", "hf_local"}


def test_shipped_hybrid_and_cloud_follow_the_design_split() -> None:
    hybrid = ModelRegistry.from_file(MODELS_YAML, profile="hybrid")
    cloud = ModelRegistry.from_file(MODELS_YAML, profile="cloud")
    # hybrid: vision stays local, text reasoning moves to the cloud
    assert hybrid.task("event_verify").primary.provider == "ollama"
    assert hybrid.task("rerank").primary.provider == "gemini"
    assert hybrid.task("daily_narrative").primary.provider == "groq"
    # cloud: vision moves too; the fine-tuned adapters can only run locally
    assert cloud.task("event_verify").primary.provider == "gemini"
    assert cloud.task("jit_vqa").primary.provider == "gemini"
    assert cloud.task("phase_tg").primary.provider == "hf_local"


def test_shipped_local_tasks_get_a_context_window_big_enough_for_their_images() -> None:
    # Measured on Ollama 0.35 / qwen2.5vl:3b: ~1,050 prompt tokens per image regardless of pixel
    # size, so max_images images must fit in num_ctx or Ollama answers HTTP 400.
    registry = ModelRegistry.from_file(MODELS_YAML, profile="local")
    for name in ("event_verify", "jit_vqa"):
        task = registry.task(name)
        assert task.primary.num_ctx is not None
        assert task.primary.num_ctx >= task.max_images * 1100 + 600, name


def test_shipped_tasks_on_one_ollama_model_share_a_context_size() -> None:
    # Ollama reloads a model when num_ctx changes between requests.
    registry = ModelRegistry.from_file(MODELS_YAML, profile="local")
    by_model: dict[str, set[int | None]] = {}
    for name in registry.task_names():
        ref = registry.task(name).primary
        if ref.provider == "ollama":
            by_model.setdefault(ref.model, set()).add(ref.num_ctx)
    assert all(len(sizes) == 1 for sizes in by_model.values()), by_model


@pytest.mark.parametrize("profile", PROFILES)
def test_shipped_cloud_models_exist_in_the_litellm_catalogue(profile: str) -> None:
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    litellm = pytest.importorskip("litellm")
    registry = ModelRegistry.from_file(MODELS_YAML, profile=profile)
    for name in registry.task_names():
        task = registry.task(name)
        for ref in task.candidates:
            if ref.provider in ("ollama", "hf_local"):
                continue
            assert ref.litellm_model in litellm.model_cost, f"{name}: unknown {ref.litellm_model}"
            if task.modality == "vision":
                assert litellm.supports_vision(ref.litellm_model), (
                    f"{name}: {ref.litellm_model} cannot read images"
                )


# --- resolution ----------------------------------------------------------------------------


def test_profile_entry_replaces_the_parent_entry_whole() -> None:
    hybrid = _load(_base(), "hybrid")
    think = hybrid.task("think")
    assert (think.primary.provider, think.primary.model) == ("gemini", "flash")
    assert think.primary.keep_alive is None  # the ollama-only key did not leak from `local`
    assert hybrid.task("see").primary.num_ctx == 6144  # untouched entry is inherited


def test_extends_chain_resolves_grandparent_entries() -> None:
    cloud = _load(_base(), "cloud")
    assert cloud.task("see").primary.provider == "gemini"  # overridden here
    assert cloud.task("think").primary.provider == "gemini"  # inherited from hybrid


def test_task_defaults_apply_and_entry_overrides_win() -> None:
    raw = _base()
    raw["profiles"]["local"]["see"]["max_images"] = 1
    raw["profiles"]["local"]["see"]["timeout_s"] = 7
    task = _load(raw).task("see")
    assert task.modality == "vision"
    assert task.max_images == 1  # entry beats tasks:
    assert task.cache_ttl_s == 60  # tasks: default survives
    assert task.timeout_s == 7
    assert _load(raw).task("think").max_tokens == 100


def test_unset_behaviour_falls_back_to_builtin_defaults() -> None:
    task = _load(_base()).task("think")
    assert (task.temperature, task.validation_retries, task.cache_ttl_s) == (0.0, 2, 0)
    assert task.max_images == 4 and task.max_image_edge == 448


def test_fallbacks_parse_provider_slash_model_keeping_inner_slashes() -> None:
    think = _load(_base(), "hybrid").task("think")
    assert [f.label() for f in think.fallbacks] == [
        "groq/openai/gpt-oss-120b",
        "openrouter/vendor/model:free",
    ]
    assert think.candidates[0].provider == "gemini"
    assert think.fallbacks[0].litellm_model == "groq/openai/gpt-oss-120b"


def test_fallback_may_be_a_mapping_with_ollama_options() -> None:
    raw = _base()
    raw["profiles"]["hybrid"]["think"]["fallback"] = [
        {"provider": "ollama", "model": "txt:3b", "num_ctx": 8192}
    ]
    ref = _load(raw, "hybrid").task("think").fallbacks[0]
    assert (ref.provider, ref.num_ctx) == ("ollama", 8192)


def test_ollama_models_route_through_litellm_ollama_chat() -> None:
    assert ModelRef(provider="ollama", model="qwen2.5:3b").litellm_model == "ollama_chat/qwen2.5:3b"
    assert ModelRef(provider="gemini", model="flash").litellm_model == "gemini/flash"


def test_family_is_per_model_and_hf_adapters_share_their_base() -> None:
    a = ModelRef(provider="hf_local", model="Qwen/VL", adapter="s3://m/tg/v1")
    b = ModelRef(provider="hf_local", model="Qwen/VL", adapter="s3://m/phavr/v1")
    assert a.family == b.family == "hf_local:Qwen/VL"
    assert ModelRef(provider="ollama", model="txt:3b").family != a.family
    assert a.needs_gpu and not ModelRef(provider="gemini", model="x").needs_gpu


def test_timeout_defaults_by_provider_unless_the_task_sets_one() -> None:
    raw = _base()
    registry = _load(raw, "hybrid")
    think = registry.task("think")
    assert think.timeout_for(think.primary) == DEFAULT_TIMEOUT_S["gemini"]
    assert (
        registry.task("see").timeout_for(registry.task("see").primary)
        == (DEFAULT_TIMEOUT_S["ollama"])
    )
    raw["tasks"]["think"]["timeout_s"] = 9
    think = _load(raw, "hybrid").task("think")
    assert [think.timeout_for(r) for r in think.candidates] == [9, 9, 9]


def test_evaluation_judge_is_a_task_in_every_profile() -> None:
    raw = _base()
    raw["evaluation"] = {"judge": {"provider": "groq", "model": "judge-model"}}
    for profile in PROFILES:
        judge = _load(raw, profile).task(JUDGE_TASK)
        assert judge.primary.label() == "groq/judge-model"
        assert judge.modality == "text"


def test_hf_local_entry_uses_base_and_adapter() -> None:
    raw = _base()
    raw["tasks"]["tune"] = {"modality": "vision"}
    for name in PROFILES:
        raw["profiles"][name]["tune"] = {
            "provider": "hf_local",
            "base": "Qwen/VL",
            "adapter": "s3://m/a/v1",
        }
    ref = _load(raw).task("tune").primary
    assert (ref.provider, ref.model, ref.adapter) == ("hf_local", "Qwen/VL", "s3://m/a/v1")


# --- calling it ----------------------------------------------------------------------------


def test_unknown_task_is_a_request_error_listing_the_known_ones() -> None:
    with pytest.raises(LLMRequestError, match="unknown task 'nope'.*see"):
        _load(_base()).task("nope")


def test_with_profile_switches_without_reloading() -> None:
    registry = _load(_base(), "local")
    assert registry.task("think").primary.provider == "ollama"
    assert registry.with_profile("hybrid").task("think").primary.provider == "gemini"
    assert registry.task("think", profile="cloud").primary.provider == "gemini"
    with pytest.raises(ModelRegistryError, match="unknown profile"):
        registry.with_profile("staging")


# --- validation: a typo must stop startup, not a request ---------------------------------


def _drop_think_from_local(raw: dict[str, Any]) -> None:
    del raw["profiles"]["local"]["think"]


def _extra_task(raw: dict[str, Any]) -> None:
    raw["profiles"]["local"]["ghost"] = {"provider": "ollama", "model": "x"}


def _typo_key(raw: dict[str, Any]) -> None:
    raw["profiles"]["local"]["think"]["modle"] = "x"


def _typo_task_key(raw: dict[str, Any]) -> None:
    raw["tasks"]["think"]["max_token"] = 5


def _bad_provider(raw: dict[str, Any]) -> None:
    raw["profiles"]["local"]["think"]["provider"] = "openai"


def _no_model(raw: dict[str, Any]) -> None:
    del raw["profiles"]["local"]["think"]["model"]


def _hf_without_base(raw: dict[str, Any]) -> None:
    raw["profiles"]["local"]["think"] = {"provider": "hf_local", "model": "x"}


def _num_ctx_on_cloud(raw: dict[str, Any]) -> None:
    raw["profiles"]["hybrid"]["think"]["num_ctx"] = 4096


def _keep_alive_on_cloud_fallback(raw: dict[str, Any]) -> None:
    raw["profiles"]["hybrid"]["think"]["fallback"] = [
        {"provider": "groq", "model": "x", "keep_alive": "5m"}
    ]


def _fallback_without_provider(raw: dict[str, Any]) -> None:
    raw["profiles"]["hybrid"]["think"]["fallback"] = ["just-a-model"]


def _fallback_to_hf_local(raw: dict[str, Any]) -> None:
    raw["profiles"]["hybrid"]["think"]["fallback"] = ["hf_local/x"]


def _cycle(raw: dict[str, Any]) -> None:
    raw["profiles"]["local"]["extends"] = "cloud"


def _bad_parent(raw: dict[str, Any]) -> None:
    raw["profiles"]["hybrid"]["extends"] = "staging"


def _missing_profile(raw: dict[str, Any]) -> None:
    del raw["profiles"]["cloud"]


def _extra_profile(raw: dict[str, Any]) -> None:
    raw["profiles"]["staging"] = {"extends": "local"}


def _reserved_task(raw: dict[str, Any]) -> None:
    raw["tasks"][JUDGE_TASK] = {}


def _negative_timeout(raw: dict[str, Any]) -> None:
    raw["profiles"]["local"]["think"]["timeout_s"] = -1


def _top_level_typo(raw: dict[str, Any]) -> None:
    raw["profile"] = {}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_drop_think_from_local, "no model for task.*think"),
        (_extra_task, "not declared under `tasks:`.*ghost"),
        (_typo_key, "profiles.local.think.*modle"),
        (_typo_task_key, "tasks.think.*max_token"),
        (_bad_provider, "profiles.local.think"),
        (_no_model, "ollama needs `model:`"),
        (_hf_without_base, "hf_local"),
        (_num_ctx_on_cloud, "only apply to ollama"),
        (_keep_alive_on_cloud_fallback, "only apply to ollama"),
        (_fallback_without_provider, r"must look like '<provider>/<model>'"),
        (_fallback_to_hf_local, r"must look like '<provider>/<model>'"),
        (_cycle, "cycle"),
        (_bad_parent, "extends unknown profile 'staging'"),
        (_missing_profile, "exactly"),
        (_extra_profile, "exactly"),
        (_reserved_task, "reserved"),
        (_negative_timeout, "timeout_s"),
        (_top_level_typo, "unknown top-level keys"),
    ],
)
def test_invalid_registry_is_rejected_at_load_with_a_pointed_message(mutate, message: str) -> None:
    with pytest.raises(ModelRegistryError, match=message):
        _load(_broken(mutate))


def test_registry_must_be_a_mapping_and_the_file_must_exist(tmp_path: Path) -> None:
    with pytest.raises(ModelRegistryError, match="mapping"):
        ModelRegistry.from_dict(["not", "a", "mapping"], profile="local")
    with pytest.raises(ModelRegistryError, match="cannot read"):
        ModelRegistry.from_file(tmp_path / "missing.yaml", profile="local")
    bad = tmp_path / "bad.yaml"
    bad.write_text("tasks: [unclosed", encoding="utf-8")
    with pytest.raises(ModelRegistryError, match="cannot read"):
        ModelRegistry.from_file(bad, profile="local")
