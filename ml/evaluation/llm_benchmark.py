"""P3-D3 benchmark: latency and VRAM of the local GenAI models on a 4 GB GPU.

Every number comes through the real `LLMGateway` (LiteLLM → Ollama, lease, structured output),
so it is what a service sees. Two things the gateway deliberately hides are read from Ollama
and `nvidia-smi` instead: how much of the model sits on the GPU, and the memory in use.

Each scenario unloads all models first, so its first call is a *cold start* (model load +
first prefill) and the next `--runs` calls are *warm*. Every call is distinct — different
query text / different random images — because Ollama caches the prompt prefix and an
identical repeat would report an unrealistically fast "warm" time.

    uv run python ml/evaluation/llm_benchmark.py --runs 5
    uv run python ml/evaluation/llm_benchmark.py --runs 5 --co-resident-gib 1.0  # + 1 GiB neighbour

Needs Ollama serving `qwen2.5:3b` and `qwen2.5vl:3b` and a Redis (a scratch db is flushed).
Results of the last run: ml/evaluation/results/p3-d3-llm-benchmark.md
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import random
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw
from pydantic import BaseModel
from redis.asyncio import Redis
from vms_common.config import LLMSettings
from vms_common.llm import ImageInput, LLMGateway


class Plan(BaseModel):
    objects: list[str]
    colour: str | None = None


class Verdict(BaseModel):
    verdict: str
    reason: str


QUERIES = [
    "a person in a red jacket carrying a black backpack",
    "two men walking a dog near the gate after dark",
    "white van parked next to the loading dock",
    "someone running across the parking lot",
    "a woman with a yellow umbrella waiting at the bus stop",
    "bicycle left leaning against the north wall",
    "group of students crossing the road at noon",
    "man in a blue hoodie loitering by the service door",
]
PLAN_SYSTEM = (
    "Extract the object classes and any colour from the search query. Reply as JSON: "
    '{"objects": [string], "colour": string or null}.'
)
VERIFY_PROMPT = (
    "These frames come from a security camera. Is a person standing inside the marked area? "
    'Reply as JSON: {"verdict": "confirmed" or "rejected", "reason": string}.'
)


def random_frame(seed: int, width: int = 448, height: int = 336) -> ImageInput:
    rng = random.Random(seed)  # noqa: S311  (test images, not security)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for _ in range(6):
        x, y = rng.randint(0, width - 80), rng.randint(0, height - 80)
        draw.rectangle(
            [x, y, x + rng.randint(30, 150), y + rng.randint(30, 110)],
            fill=rng.choice(["red", "blue", "green", "black", "orange"]),
        )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return ImageInput(data=buffer.getvalue())


def vram_used_mib() -> int:
    out = subprocess.run(  # noqa: S603
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],  # noqa: S607
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return int(out.strip().splitlines()[0])


async def ollama_loaded(http: httpx.AsyncClient) -> list[dict[str, Any]]:
    return (await http.get("/api/ps")).json().get("models", [])


async def unload_all(http: httpx.AsyncClient) -> None:
    for model in await ollama_loaded(http):
        await http.post("/api/generate", json={"model": model["name"], "keep_alive": 0})
    for _ in range(60):
        if not await ollama_loaded(http):
            return
        await asyncio.sleep(0.5)
    raise RuntimeError("Ollama did not unload its models")


async def run_scenario(
    gateway: LLMGateway, http: httpx.AsyncClient, name: str, images: int, runs: int, offset: int
) -> dict[str, Any]:
    async def one(i: int) -> dict[str, Any]:
        started = time.monotonic()
        if images == 0:
            result = await gateway.chat(
                "query_decompose",
                [
                    {"role": "system", "content": PLAN_SYSTEM},
                    {"role": "user", "content": f"{QUERIES[i % len(QUERIES)]} (#{offset + i})"},
                ],
                response_model=Plan,
            )
        else:
            frames = [random_frame((offset + i) * 10 + k) for k in range(images)]
            result = await gateway.vision(
                "event_verify", f"{VERIFY_PROMPT} (#{offset + i})", frames, response_model=Verdict
            )
        return {
            "seconds": time.monotonic() - started,
            "prompt_tokens": result.usage.prompt_tokens,
            "completion_tokens": result.usage.completion_tokens,
            "attempts": result.attempts,
        }

    await unload_all(http)
    before = vram_used_mib()
    cold = await one(0)
    loaded = (await ollama_loaded(http))[0]
    after = vram_used_mib()
    warm = [await one(i) for i in range(1, runs + 1)]
    seconds = [w["seconds"] for w in warm]
    return {
        "scenario": name,
        "model": loaded["name"],
        "cold_s": round(cold["seconds"], 2),
        "warm_median_s": round(statistics.median(seconds), 2),
        "warm_min_s": round(min(seconds), 2),
        "warm_max_s": round(max(seconds), 2),
        "prompt_tokens": warm[-1]["prompt_tokens"],
        "completion_tokens_median": statistics.median(w["completion_tokens"] for w in warm),
        "extra_attempts": sum(w["attempts"] - 1 for w in [cold, *warm]),
        "model_size_gib": round(loaded["size"] / 2**30, 2),
        "on_gpu_pct": round(100 * loaded["size_vram"] / loaded["size"]),
        "vram_before_mib": before,
        "vram_loaded_mib": after,
        "context": loaded.get("context_length"),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--runs", type=int, default=5, help="warm calls per scenario")
    parser.add_argument("--redis-url", default="redis://localhost:6379/9", help="scratch db")
    parser.add_argument(
        "--co-resident-gib",
        type=float,
        default=0.0,
        help="hold this much GPU memory, as perception would (needs torch + CUDA)",
    )
    parser.add_argument("--json", help="also write the rows to this file")
    args = parser.parse_args()

    ballast = None
    if args.co_resident_gib > 0:
        import torch

        ballast = torch.empty(int(args.co_resident_gib * 2**30), dtype=torch.uint8, device="cuda")

    settings = LLMSettings()
    redis = Redis.from_url(args.redis_url, decode_responses=True)
    await redis.flushdb()
    gateway = LLMGateway.from_settings(settings, redis=redis)
    rows = []
    async with httpx.AsyncClient(base_url=settings.effective_ollama_url, timeout=60) as http:
        version = (await http.get("/api/version")).json()["version"]
        for index, (name, images) in enumerate(
            [("text", 0), ("vision 1 image", 1), ("vision 2 images", 2), ("vision 4 images", 4)]
        ):
            rows.append(await run_scenario(gateway, http, name, images, args.runs, index * 1000))
        await unload_all(http)
    await gateway.aclose()
    await redis.flushdb()
    await redis.aclose()

    print(f"ollama {version}, profile {settings.profile}, co-resident {args.co_resident_gib} GiB")
    print(
        "| scenario | model | cold s | warm median s (min–max) | prompt tok | on GPU "
        "| VRAM MiB (before→loaded) |"
    )
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {r['scenario']} | {r['model']} | {r['cold_s']} | {r['warm_median_s']} "
            f"({r['warm_min_s']}–{r['warm_max_s']}) | {r['prompt_tokens']} | {r['on_gpu_pct']}% "
            f"| {r['vram_before_mib']}→{r['vram_loaded_mib']} |"
        )
    if args.json:
        report = {"ollama": version, "co_resident_gib": args.co_resident_gib, "rows": rows}
        await asyncio.to_thread(Path(args.json).write_text, json.dumps(report, indent=2), "utf-8")
    del ballast


if __name__ == "__main__":
    asyncio.run(main())
