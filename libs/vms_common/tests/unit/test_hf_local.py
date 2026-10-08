"""hf_local (P5-D5): adapter hot-swapping, frame back-off on out-of-memory and error translation,
against a fake runtime (no torch, no GPU). The real runtime is measured separately."""

from __future__ import annotations

import asyncio
import base64
import io
import time
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from pydantic import BaseModel
from vms_common.config import LLMSettings
from vms_common.llm import ImageInput, LLMGateway, ModelRegistry
from vms_common.llm.backend import BackendError
from vms_common.llm.hf_local import (
    ADAPTER_FILES,
    Adapter,
    Generation,
    HfLocalBackend,
    drop_images,
    split_messages,
)
from vms_common.llm.registry import ModelRef

BASE = "Qwen/Qwen2.5-VL-3B-Instruct"


def jpeg(color: int = 0) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (color, 0, 0)).save(buffer, format="JPEG")
    return buffer.getvalue()


def wire(n_images: int, text: str = "Which stage is this?") -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for i in range(n_images):
        url = "data:image/jpeg;base64," + base64.b64encode(jpeg(i * 80)).decode()
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return [{"role": "user", "content": parts}]


class FakeRuntime:
    def __init__(self) -> None:
        self.events: list[tuple] = []
        self.fail_with: list[BaseException] = []
        self.delay_s = 0.0
        self.reply = '{"phases": ["baseline"]}'

    def load_base(self, model_id: str) -> None:
        self.events.append(("load_base", model_id))

    def activate(self, adapter: Adapter | None) -> None:
        self.events.append(("activate", adapter.name if adapter else None))

    def generate(self, messages, images, *, max_new_tokens, temperature) -> Generation:
        self.events.append(("generate", len(images)))
        time.sleep(self.delay_s)
        if self.fail_with:
            raise self.fail_with.pop(0)
        return Generation(self.reply, prompt_tokens=100 + len(images), completion_tokens=7)

    def empty_cache(self) -> None:
        self.events.append(("empty_cache",))

    def unload(self) -> None:
        self.events.append(("unload",))

    def names(self, kind: str) -> list:
        return [e[1] for e in self.events if e[0] == kind and len(e) > 1]

    def count(self, kind: str) -> int:
        return sum(1 for e in self.events if e[0] == kind)


def make_adapter(root: Path, name: str) -> str:
    d = root / name
    d.mkdir()
    for f in ADAPTER_FILES:
        (d / f).write_bytes(b"x")
    return str(d)


def half_an_adapter(root: Path) -> None:
    (root / "half").mkdir()
    (root / "half" / "adapter_config.json").write_text("{}")


def backend(tmp_path: Path, runtime: FakeRuntime | None = None, **kw: Any) -> HfLocalBackend:
    return HfLocalBackend(
        LLMSettings(hf_adapters_dir=str(tmp_path / "cache")), runtime=runtime or FakeRuntime(),
        **kw,
    )  # fmt: skip


async def call(b: HfLocalBackend, ref: ModelRef, n_images: int = 2, **kw: Any):
    args = (
        dict(temperature=0.0, max_tokens=64, timeout_s=5.0, response_format=None, tools=None) | kw
    )
    return await b.complete(ref, wire(n_images), **args)


# ---- messages -------------------------------------------------------------------------------


def test_wire_messages_become_placeholders_and_image_bytes_in_order() -> None:
    chat, images = split_messages(wire(3))
    assert [p["type"] for p in chat[0]["content"]] == ["text", "image", "image", "image"]
    assert len(images) == 3 and images[0] != images[1]  # decoded, in order


def test_plain_text_messages_pass_through_and_remote_images_are_refused() -> None:
    chat, images = split_messages([{"role": "user", "content": "hello"}])
    assert chat == [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
    assert images == []
    remote = [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "https://x/y.jpg"}}],
        }
    ]
    with pytest.raises(BackendError) as err:
        split_messages(remote)
    assert err.value.kind == "bad_request"


@pytest.mark.parametrize(
    "keep,kept", [(1, [0]), (2, [0, 4]), (3, [0, 2, 4]), (5, [0, 1, 2, 3, 4]), (9, [0, 1, 2, 3, 4])]
)
def test_dropping_frames_keeps_the_first_and_last_and_the_placeholders_follow(
    keep: int, kept: list[int]
) -> None:
    chat, images = split_messages(wire(5))
    shown, pictures = drop_images(chat, images, keep)
    assert pictures == [images[i] for i in kept]
    assert sum(p["type"] == "image" for p in shown[0]["content"]) == len(kept)
    assert shown[0]["content"][0]["type"] == "text"  # the question is never dropped


# ---- adapters -------------------------------------------------------------------------------


async def test_the_base_is_loaded_once_and_adapters_are_switched_not_reloaded(
    tmp_path: Path,
) -> None:
    rt = FakeRuntime()
    b = backend(tmp_path, rt)
    tg = ModelRef(provider="hf_local", model=BASE, adapter=make_adapter(tmp_path, "tg"))
    vr = ModelRef(provider="hf_local", model=BASE, adapter=make_adapter(tmp_path, "phavr"))
    plain = ModelRef(provider="hf_local", model=BASE)

    for ref in (tg, tg, vr, tg, plain, plain, vr):
        await call(b, ref)

    assert rt.names("load_base") == [BASE]  # once, for seven calls
    activations = rt.names("activate")
    assert len(activations) == 5  # tg, vr, tg, base, vr: a repeat of the same one costs nothing
    assert activations[3] is None  # the plain base switches the adapters off
    assert len({a for a in activations if a}) == 2  # two distinct, stable adapter names


async def test_an_adapter_with_files_missing_is_a_not_found_not_a_crash(tmp_path: Path) -> None:
    half_an_adapter(tmp_path)
    ref = ModelRef(provider="hf_local", model=BASE, adapter=str(tmp_path / "half"))
    with pytest.raises(BackendError) as err:
        await call(backend(tmp_path), ref)
    assert err.value.kind == "not_found" and "adapter_model.safetensors" in str(err.value)


async def test_an_s3_adapter_is_downloaded_once_into_the_cache(tmp_path: Path) -> None:
    fetched: list[str] = []

    async def fetch(uri: str, local: Path) -> None:
        fetched.append(uri)
        await asyncio.to_thread(local.write_bytes, b"x")

    rt = FakeRuntime()
    b = backend(tmp_path, rt, fetch=fetch)
    ref = ModelRef(provider="hf_local", model=BASE, adapter="s3://vms-models/tg/v1/")
    await call(b, ref)
    await call(b, ref)

    assert fetched == [f"s3://vms-models/tg/v1/{f}" for f in ADAPTER_FILES]  # once, not per call
    assert len(rt.names("activate")) == 1


# ---- memory and failure ---------------------------------------------------------------------


class OutOfMemoryError(RuntimeError):
    """Named like torch.cuda.OutOfMemoryError, which is what the backend recognises."""


async def test_out_of_memory_retries_with_half_the_frames_after_freeing_the_cache(
    tmp_path: Path,
) -> None:
    rt = FakeRuntime()
    rt.fail_with = [OutOfMemoryError("CUDA out of memory. Tried to allocate 1.2 GiB")]
    result = await call(backend(tmp_path, rt), ModelRef(provider="hf_local", model=BASE), 8)

    assert rt.names("generate") == [8, 4]  # the second try had half the frames
    assert rt.count("empty_cache") == 1
    assert result.usage.prompt_tokens == 104


async def test_out_of_memory_that_keeps_happening_is_an_unavailable_error(tmp_path: Path) -> None:
    rt = FakeRuntime()
    rt.fail_with = [OutOfMemoryError("CUDA out of memory")] * 5
    with pytest.raises(BackendError) as err:
        await call(backend(tmp_path, rt), ModelRef(provider="hf_local", model=BASE), 8)
    assert err.value.kind == "unavailable" and "out of memory" in str(err.value)
    assert rt.names("generate") == [8, 4, 2]  # two retries, then it gives up


async def test_a_single_frame_is_not_retried_smaller(tmp_path: Path) -> None:
    rt = FakeRuntime()
    rt.fail_with = [OutOfMemoryError("CUDA out of memory")]
    with pytest.raises(BackendError):
        await call(backend(tmp_path, rt), ModelRef(provider="hf_local", model=BASE), 1)
    assert rt.names("generate") == [1]


@pytest.mark.parametrize(
    "error,kind",
    [
        (ImportError("No module named 'peft'"), "unavailable"),
        (FileNotFoundError("no such weights"), "not_found"),
        (ValueError("bad shape"), "bad_request"),
        (RuntimeError("boom"), "unavailable"),
    ],
)
async def test_runtime_errors_are_translated(tmp_path: Path, error, kind: str) -> None:
    rt = FakeRuntime()
    rt.fail_with = [error]
    with pytest.raises(BackendError) as err:
        await call(backend(tmp_path, rt), ModelRef(provider="hf_local", model=BASE))
    assert err.value.kind == kind


async def test_a_slow_generation_times_out_and_tools_are_refused(tmp_path: Path) -> None:
    rt = FakeRuntime()
    rt.delay_s = 0.4
    ref = ModelRef(provider="hf_local", model=BASE)
    with pytest.raises(BackendError) as err:
        await call(backend(tmp_path, rt), ref, timeout_s=0.05)
    assert err.value.kind == "timeout"
    with pytest.raises(BackendError) as err:
        await call(backend(tmp_path), ref, tools=[{"type": "function"}])
    assert err.value.kind == "bad_request"


# ---- lifecycle ------------------------------------------------------------------------------


async def test_unload_frees_the_base_only_for_its_own_family_and_the_next_call_reloads(
    tmp_path: Path,
) -> None:
    rt = FakeRuntime()
    b = backend(tmp_path, rt)
    ref = ModelRef(provider="hf_local", model=BASE)
    await call(b, ref)
    await b.unload("ollama:qwen2.5vl:3b")  # someone else's family: nothing happens
    assert rt.count("unload") == 0
    await b.unload(ref.family)
    assert rt.count("unload") == 1
    await call(b, ref)
    assert rt.names("load_base") == [BASE, BASE]


async def test_stream_answers_in_one_piece_with_usage(tmp_path: Path) -> None:
    b = backend(tmp_path)
    chunks = [
        c
        async for c in b.stream(
            ModelRef(provider="hf_local", model=BASE),
            wire(1),
            temperature=0.0,
            max_tokens=8,
            timeout_s=5.0,
            tools=None,
        )  # fmt: skip
    ]
    assert [c.delta for c in chunks] == ['{"phases": ["baseline"]}']
    assert chunks[0].finish_reason == "stop" and chunks[0].usage.completion_tokens == 7


# ---- through the gateway --------------------------------------------------------------------


class _Labels(BaseModel):
    phases: list[str]


async def test_a_task_on_hf_local_runs_through_the_gateway_with_its_adapter(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path, "tg")
    registry = ModelRegistry.from_dict(
        {
            "tasks": {"phase_tg": {"modality": "vision", "max_images": 8, "max_image_edge": 64}},
            "profiles": {
                "local": {"phase_tg": {"provider": "hf_local", "base": BASE, "adapter": adapter}},
                "hybrid": {"phase_tg": {"provider": "hf_local", "base": BASE, "adapter": adapter}},
                "cloud": {"phase_tg": {"provider": "hf_local", "base": BASE, "adapter": adapter}},
            },
        },
        profile="local",
    )
    assert registry.uses_provider("hf_local") and not registry.uses_provider("ollama")
    rt = FakeRuntime()
    gateway = LLMGateway(registry, {"hf_local": backend(tmp_path, rt)})

    result = await gateway.vision(
        "phase_tg", "Label each frame.", [ImageInput(data=jpeg(1)), ImageInput(data=jpeg(2))],
        response_model=_Labels,
    )  # fmt: skip

    assert result.parsed == _Labels(phases=["baseline"])
    assert result.provider == "hf_local" and result.model == BASE
    assert rt.names("load_base") == [BASE] and len(rt.names("activate")) == 1
    assert rt.names("generate") == [2]


def test_the_defaults_suit_a_4gb_card() -> None:
    s = LLMSettings()
    assert s.hf_load_4bit is True and s.hf_oom_retries == 2
    assert s.hf_adapters_dir.endswith("/adapters")
