"""`hf_local`: fine-tuned LoRA adapters served in-process (P5-D5, design §8.3 / §11).

One base model (Qwen2.5-VL-3B, 4-bit) is loaded once; the TG and PhaVR adapters are PEFT LoRA
adapters hot-swapped onto it, so switching between `phase_tg` and `phase_vr` costs a pointer move,
not a model load. A call with no adapter runs the plain base (zero-shot), which is also how a task
falls back when its adapter is missing. All of it runs under the gateway's GPU lease: an
`hf_local` model's lease family is its base, so swapping adapters never evicts the base.

The heavy libraries (torch, transformers, peft, bitsandbytes) are imported on first use, inside
`TransformersRuntime`; everything else here — adapter fetching, message handling, the frame
back-off on out-of-memory, error translation — works against the small `Runtime` protocol and is
unit-tested with a fake. Install the extra with `uv sync --extra hf` (peft, bitsandbytes,
accelerate); torch and transformers come with the GPU services' own dependencies.

Not supported: tool calls, and true token streaming (`stream` answers in one piece when the
generation is finished; the vision tasks it serves are not streamed to a person).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import re
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from vms_common.config import LLMSettings, StorageSettings
from vms_common.llm.backend import BackendError, RawCompletion
from vms_common.llm.registry import ModelRef
from vms_common.llm.types import ChatChunk, Usage
from vms_common.logging import get_logger

log = get_logger(__name__)

ADAPTER_FILES = ("adapter_config.json", "adapter_model.safetensors")
_DATA_URL = re.compile(r"^data:([\w/+.-]+);base64,(.*)$", re.DOTALL)


@dataclass(frozen=True)
class Adapter:
    name: str  # PEFT adapter name: stable for one URI
    path: Path  # directory holding adapter_config.json + adapter_model.safetensors


@dataclass(frozen=True)
class Generation:
    text: str
    prompt_tokens: int
    completion_tokens: int


class Runtime(Protocol):
    """What the backend needs from the model runtime. Methods block; the backend runs them in a
    worker thread."""

    def load_base(self, model_id: str) -> None: ...

    def activate(self, adapter: Adapter | None) -> None:
        """Make `adapter` the active one (loading it the first time), or None for the plain base."""
        ...

    def generate(
        self, messages: list[dict[str, Any]], images: list[Any], *, max_new_tokens: int,
        temperature: float,
    ) -> Generation: ...  # fmt: skip

    def empty_cache(self) -> None: ...

    def unload(self) -> None: ...


# ---- messages ------------------------------------------------------------------------------


def split_messages(wire: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[bytes]]:
    """OpenAI-style wire messages -> (chat messages with `{"type": "image"}` placeholders, the
    images' bytes in order). The gateway has already capped how many images there are and how
    large; this only translates."""
    chat: list[dict[str, Any]] = []
    images: list[bytes] = []
    for message in wire:
        content = message.get("content")
        if isinstance(content, list):
            parts: list[dict[str, Any]] = []
            for part in content:
                if part.get("type") == "image_url":
                    url = (part.get("image_url") or {}).get("url", "")
                    match = _DATA_URL.match(url)
                    if not match:
                        raise BackendError("bad_request", "hf_local takes inline images only")
                    images.append(base64.b64decode(match.group(2)))
                    parts.append({"type": "image"})
                elif part.get("type") == "text":
                    parts.append({"type": "text", "text": part.get("text", "")})
            chat.append({"role": message["role"], "content": parts})
        else:
            chat.append(
                {
                    "role": message["role"],
                    "content": [{"type": "text", "text": content or ""}],
                }
            )
    return chat, images


def drop_images(
    chat: list[dict[str, Any]], images: list[bytes], keep: int
) -> tuple[list[dict[str, Any]], list[bytes]]:
    """The same conversation with only `keep` images, spread evenly over the originals (so the
    first and last frames survive, not just the first few)."""
    if keep >= len(images):
        return chat, images
    if keep <= 0:
        raise ValueError("keep at least one image")
    picked = (
        [0]
        if keep == 1
        else sorted({round(i * (len(images) - 1) / (keep - 1)) for i in range(keep)})
    )
    wanted = set(picked)
    out: list[dict[str, Any]] = []
    seen = -1
    for message in chat:
        parts = []
        for part in message["content"]:
            if part["type"] == "image":
                seen += 1
                if seen not in wanted:
                    continue
            parts.append(part)
        out.append({"role": message["role"], "content": parts})
    return out, [images[i] for i in picked]


def is_out_of_memory(exc: BaseException) -> bool:
    name = type(exc).__name__
    return "OutOfMemory" in name or "CUDA out of memory" in str(exc)


# ---- the backend ---------------------------------------------------------------------------

Fetch = Callable[[str, Path], Awaitable[None]]  # (s3 uri of a file, local path) -> None


class HfLocalBackend:
    PROVIDERS = ("hf_local",)

    def __init__(
        self,
        settings: LLMSettings | None = None,
        *,
        runtime: Runtime | None = None,
        fetch: Fetch | None = None,
        adapters_dir: Path | None = None,
    ) -> None:
        self._settings = settings or LLMSettings()
        self._runtime = runtime
        self._fetch = fetch
        self._adapters_dir = adapters_dir or Path(self._settings.hf_adapters_dir).expanduser()
        self._loaded_base: str | None = None
        self._active: str | None = None  # adapter name, "" for the plain base, None = unknown
        self._lock = asyncio.Lock()

    # --- Backend protocol --------------------------------------------------------------

    async def complete(
        self,
        ref: ModelRef,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int | None,
        timeout_s: float,
        response_format: dict[str, Any] | None,
        tools: list[dict[str, Any]] | None,
    ) -> RawCompletion:
        if tools:
            raise BackendError("bad_request", "hf_local does not support tool calls")
        chat, images = split_messages(messages)
        try:
            async with self._lock:
                generation = await asyncio.wait_for(
                    self._run(ref, chat, images, temperature, max_tokens or 512), timeout_s
                )
        except TimeoutError as exc:
            raise BackendError(
                "timeout", f"{ref.label()} did not answer in {timeout_s:.0f}s"
            ) from exc
        except BackendError:
            raise
        except Exception as exc:  # anything the runtime throws is a failed call, not a bug here
            raise _translate(exc) from exc
        return RawCompletion(
            text=generation.text,
            usage=Usage(
                prompt_tokens=generation.prompt_tokens,
                completion_tokens=generation.completion_tokens,
            ),
            finish_reason="stop",
        )

    async def stream(
        self,
        ref: ModelRef,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int | None,
        timeout_s: float,
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[ChatChunk]:
        done = await self.complete(
            ref, messages, temperature=temperature, max_tokens=max_tokens, timeout_s=timeout_s,
            response_format=None, tools=tools,
        )  # fmt: skip
        yield ChatChunk(delta=done.text, finish_reason="stop", usage=done.usage)

    async def unload(self, family: str) -> None:
        if self._runtime is None or family != f"hf_local:{self._loaded_base}":
            return
        async with self._lock:
            await asyncio.to_thread(self._runtime.unload)
            self._loaded_base = None
            self._active = None

    # --- one generation ----------------------------------------------------------------

    def _rt(self) -> Runtime:
        if self._runtime is None:
            self._runtime = TransformersRuntime(load_4bit=self._settings.hf_load_4bit)
        return self._runtime

    async def _run(
        self,
        ref: ModelRef,
        chat: list[dict[str, Any]],
        images: list[bytes],
        temperature: float,
        max_new_tokens: int,
    ) -> Generation:
        runtime = self._rt()
        adapter = await self._adapter(ref)
        if self._loaded_base != ref.model:
            if self._loaded_base is not None:
                await asyncio.to_thread(runtime.unload)
            await asyncio.to_thread(runtime.load_base, ref.model)
            self._loaded_base, self._active = ref.model, None
        wanted = adapter.name if adapter else ""
        if self._active != wanted:
            await asyncio.to_thread(runtime.activate, adapter)
            self._active = wanted

        keep = len(images)
        for attempt in range(self._settings.hf_oom_retries + 1):
            shown, pictures = drop_images(chat, images, keep) if images else (chat, images)
            try:
                return await asyncio.to_thread(
                    runtime.generate, shown, pictures,
                    max_new_tokens=max_new_tokens, temperature=temperature,
                )  # fmt: skip
            except Exception as exc:
                if not is_out_of_memory(exc) or attempt == self._settings.hf_oom_retries:
                    raise
                await asyncio.to_thread(runtime.empty_cache)
                if keep <= 1:
                    raise
                keep = max(1, keep // 2)
                log.warning("hf_local_oom_retry", images_left=keep, attempt=attempt + 1)
        raise AssertionError("unreachable")  # pragma: no cover

    async def _adapter(self, ref: ModelRef) -> Adapter | None:
        """The adapter this reference names, fetched to the local cache the first time (adapter
        URIs are versioned paths, `.../v1`, so a cached copy is never stale)."""
        if not ref.adapter:
            return None
        uri = ref.adapter
        name = "a" + hashlib.sha1(uri.encode()).hexdigest()[:10]  # noqa: S324 - a cache key
        if uri.startswith("s3://"):
            path = self._adapters_dir / name
            missing = await asyncio.to_thread(_missing_files, path, make=True)
            if missing:
                fetch = self._fetch or _s3_fetch(StorageSettings())
                for filename in missing:
                    await fetch(f"{uri.rstrip('/')}/{filename}", path / filename)
        else:
            path = await asyncio.to_thread(_local_path, uri)
        absent = await asyncio.to_thread(_missing_files, path)
        if absent:
            raise BackendError("not_found", f"adapter {uri} lacks {', '.join(absent)}")
        return Adapter(name=name, path=path)


def _local_path(uri: str) -> Path:
    return Path(uri.removeprefix("file://")).expanduser()


def _missing_files(path: Path, *, make: bool = False) -> list[str]:
    if make:
        path.mkdir(parents=True, exist_ok=True)
    return [f for f in ADAPTER_FILES if not (path / f).is_file()]


def _s3_fetch(storage: StorageSettings) -> Fetch:
    from vms_common.storage.s3 import S3Client  # noqa: PLC0415 - only needed to fetch

    client = S3Client(
        endpoint_url=storage.endpoint_url,
        access_key=storage.access_key,
        secret_key=storage.secret_key,
        region=storage.region,
    )

    async def fetch(uri: str, local: Path) -> None:
        await client.download_file(uri, str(local))

    return fetch


def _translate(exc: Exception) -> BackendError:
    if is_out_of_memory(exc):
        return BackendError("unavailable", "the GPU ran out of memory")
    if isinstance(exc, ImportError):
        return BackendError(
            "unavailable", f"hf_local needs peft, bitsandbytes and accelerate ({exc})"
        )
    if isinstance(exc, FileNotFoundError):
        return BackendError("not_found", str(exc))
    if isinstance(exc, ValueError):
        return BackendError("bad_request", str(exc))
    return BackendError("unavailable", f"{type(exc).__name__}: {exc}")


# ---- the real runtime (torch, transformers, peft, bitsandbytes) -----------------------------


class TransformersRuntime:
    """Qwen2.5-VL on the GPU in 4-bit, with PEFT adapters. Never imported by the unit tests."""

    def __init__(self, *, load_4bit: bool = True) -> None:
        self._load_4bit = load_4bit
        self._lock = threading.Lock()  # one generation at a time, even after a timed-out call
        self.model: Any = None
        self.processor: Any = None
        self._peft = False
        self._adapter_on = False  # False: run the base as it is, whatever adapters are loaded
        self._known: set[str] = set()

    def load_base(self, model_id: str) -> None:
        import torch  # noqa: PLC0415
        from transformers import AutoModelForImageTextToText, AutoProcessor  # noqa: PLC0415

        kwargs: dict[str, Any] = {"torch_dtype": torch.float16, "device_map": {"": 0}}
        if self._load_4bit:
            from transformers import BitsAndBytesConfig  # noqa: PLC0415

            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
            )
        with self._lock:
            self.model = AutoModelForImageTextToText.from_pretrained(model_id, **kwargs).eval()
            self.processor = AutoProcessor.from_pretrained(model_id)
            self._peft, self._adapter_on, self._known = False, False, set()

    def activate(self, adapter: Adapter | None) -> None:
        with self._lock:
            if adapter is None:
                self._adapter_on = False  # generate() runs the base with the adapters disabled
                return
            from peft import PeftModel  # noqa: PLC0415

            if not self._peft:
                self.model = PeftModel.from_pretrained(
                    self.model, str(adapter.path), adapter_name=adapter.name
                )
                self._peft = True
            elif adapter.name not in self._known:
                self.model.load_adapter(str(adapter.path), adapter_name=adapter.name)
            self._known.add(adapter.name)
            self.model.set_adapter(adapter.name)
            self._adapter_on = True

    def generate(
        self, messages: list[dict[str, Any]], images: list[Any], *, max_new_tokens: int,
        temperature: float,
    ) -> Generation:  # fmt: skip
        import torch  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        pictures = [Image.open(io.BytesIO(b)).convert("RGB") for b in images]
        with self._lock:
            text = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self.processor(text=[text], images=pictures or None, return_tensors="pt").to(
                self.model.device
            )
            sampling = (
                {"do_sample": True, "temperature": temperature}
                if temperature > 0
                else {"do_sample": False}
            )
            with torch.inference_mode():
                if self._peft and not self._adapter_on:
                    with self.model.disable_adapter():
                        out = self.model.generate(
                            **inputs, max_new_tokens=max_new_tokens, **sampling
                        )
                else:
                    out = self.model.generate(**inputs, max_new_tokens=max_new_tokens, **sampling)
            produced = out[:, inputs["input_ids"].shape[1] :]
            reply = self.processor.batch_decode(
                produced, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0]
            return Generation(
                text=reply,
                prompt_tokens=int(inputs["input_ids"].shape[1]),
                completion_tokens=int(produced.shape[1]),
            )

    def empty_cache(self) -> None:
        import torch  # noqa: PLC0415

        torch.cuda.empty_cache()

    def unload(self) -> None:
        import gc  # noqa: PLC0415

        import torch  # noqa: PLC0415

        with self._lock:
            self.model = self.processor = None
            self._peft, self._adapter_on, self._known = False, False, set()
        gc.collect()
        torch.cuda.empty_cache()
