# P3-D3 — Local GenAI models on 4 GB: latency, VRAM, model tags

**Measured 1 Oct 2026** on the target hardware class: NVIDIA GeForce RTX 3050 Laptop GPU
(4096 MiB, driver 595.91), AMD Ryzen 5 5600H (12 threads), Ollama 0.35.0 with
`OLLAMA_MAX_LOADED_MODELS=1` and everything else default, models `qwen2.5vl:3b` and
`qwen2.5:3b` (Q4_K_M).

## What this covers vs. what it doesn't

Every number in the main tables comes through the real `LLMGateway` (LiteLLM → Ollama, GPU
lease, structured output with `response_model`), produced by
`ml/evaluation/llm_benchmark.py --runs 5` — what a service sees, not raw model speed.
Each scenario unloads all models first: the first call is a **cold start** (model load +
first prefill), the next five are **warm**. Every call differs (query text / random images)
because Ollama caches the prompt prefix and an identical repeat reports a flattering time.
The VRAM-placement column comes from Ollama's `/api/ps`, memory from `nvidia-smi`.

It does **not** cover answer quality (that is P4/P5 evaluation), concurrent load, or the
`hf_local` path (P5-D5). Five warm runs on one laptop are a sanity check, not a distribution:
the min–max spread is shown, and a throttling laptop will differ.

## Results — the model alone on the GPU

| Scenario | Cold start | Warm median (min–max) | Prompt tokens | Model on GPU | VRAM in use |
|---|---|---|---|---|---|
| `qwen2.5:3b`, structured query plan | 6.5 s | **0.25 s** (0.19–0.36) | 53 | **100 %** | 2,402 MiB |
| `qwen2.5vl:3b`, 1 image | 8.1 s | **3.1 s** (2.9–3.9) | 1,100 | 53 % | 3,196 MiB |
| `qwen2.5vl:3b`, 2 images | 11.0 s | **5.4 s** (5.3–6.5) | 2,138 | 53 % | 3,216 MiB |
| `qwen2.5vl:3b`, 4 images | 14.4 s | **11.0 s** (9.9–11.7) | 4,214 | 53 % | 3,220 MiB |

Images are 448×336 JPEG. `num_ctx` was the registry's: 8192 for the text model, 6144 for the
vision model. No call needed a validation retry (Ollama's grammar-constrained decoding gave
valid JSON every time).

## Results — with a perception-sized neighbour (≈ 0.8 GB of VRAM held)

Same harness with `--co-resident-gib 0.7` (that allocation plus torch's CUDA context ≈ 808 MiB,
about what perception holds with YOLO11s + SigLIP 2 loaded: 804 MiB in P2-D6).

| Scenario | Cold start | Warm median (min–max) | Model on GPU | VRAM in use |
|---|---|---|---|---|
| `qwen2.5:3b`, structured query plan | 7.0 s | 0.43 s (0.34–0.54) | 75 % | 2,759 MiB |
| `qwen2.5vl:3b`, 1 image | 8.3 s | 3.9 s (3.8–4.5) | 31 % | 3,221 MiB |
| `qwen2.5vl:3b`, 2 images | 14.1 s | 6.7 s (6.5–10.5) | 18 % | 3,007 MiB |
| `qwen2.5vl:3b`, 4 images | 16.1 s | 14.5 s (12.2–15.6) | 18 % | 3,009 MiB |

## Findings

1. **The vision model does not fit on a 4 GB GPU; the text model does.** `qwen2.5vl:3b` needs
   ≈ 3.3 GiB plus its context and compute buffers; Ollama puts ~53 % of it on the GPU and runs
   the rest on the CPU (18–31 % when perception is also resident). The planning estimate
   "3.2–3.6 GB" in design §11.3 was the VRAM figure; it did not say the model would be split.
   `qwen2.5:3b` is 100 % on the GPU alone (75 % with perception beside it).
2. **One image costs ≈ 1,050 prompt tokens whatever its size** (224×168 up to 672×504 all
   measured 1,070 tokens for one image). The pixel cap (`max_image_edge`) therefore does not
   reduce latency on this Ollama build — the image *count* does, at ≈ 2.3 s of CPU-bound
   prefill per image when the model runs alone.
3. **`num_ctx` is mandatory for multi-image calls.** Ollama sized the context at 4096 from free
   VRAM; a 4-image request (≈ 4,200 tokens) was refused with HTTP 400 "exceeds the available
   context size". `config/models.yaml` therefore sets `num_ctx` per local model (6144 for the
   vision tasks, 8192 for the text tasks) and a test pins `num_ctx ≥ max_images × 1,100 + 600`.
   Tasks sharing a model must share a `num_ctx`: measured on `qwen2.5:3b`, alternating
   8192 → 4096 → 8192 reloaded the model on every change (load 3.2–3.8 s each time).
4. **Cold starts are 6–16 s**, dominated by loading plus the first prefill; the first-ever
   load after `ollama pull` took 54 s (cold disk cache + CUDA initialisation), so the first
   call after installing is not representative. A family switch under the lease costs one
   unload plus one cold start.
5. **Inputs for P3-D4 (VLM gate).** The Phase 3 demo target is a verified alert in < 30 s. With
   the vision model warm: 2 keyframes ≈ 5–7 s, 4 keyframes ≈ 11–15 s; a cold start adds the model
   load (≈ 2–7 s in these runs). So verification fits the budget, but 4 keyframes with perception
   running on the same GPU leaves little slack — default to 2–3 keyframes there and let
   `keep_alive` (Ollama's default is 5 min) hold the model warm.
6. **Single-laptop mode works but degrades**: perception + local VLM on one 4 GB GPU is ~25–30 %
   slower for the VLM and pushes the text model partly to CPU. The two-laptop topology
   (design §11.3) remains the recommended demo setup; `hybrid` avoids the problem for text.
7. **Flash attention + q8 KV cache were tried and not adopted** (one-off probe, not in the
   harness): vision GPU share 53 → 55 %, model 3.33 → 3.23 GiB, 4-image warm ≈ 12.5 → 11.8 s,
   text VRAM 2,402 → 2,270 MiB — a few percent, not a change of regime.

Indicative Ollama-native breakdown from the same session (direct `/api/chat`, one-off probe,
not committed): vision prefill ≈ 450 tokens/s (1 image 2.3 s, 4 images 9.4 s), vision decode
≈ 30 tokens/s, text decode ≈ 70 tokens/s, model load ≈ 4 s.

## Model tags (FR-CFG: "verified at setup")

| Registry entry | Status on 1 Oct 2026 |
|---|---|
| `ollama` `qwen2.5vl:3b` | **Verified.** Exists in the Ollama registry, pulled (3.2 GB), runs on the RTX 3050, accepts images, honours a JSON schema. |
| `ollama` `qwen2.5:3b` | **Verified.** Exists, pulled (1.9 GB), runs 100 % on the GPU, honours a JSON schema. |
| `gemini` `gemini-2.5-flash` | **Not verified against the live API** (no key on this machine). LiteLLM's catalogue lists it with vision, tools and JSON-schema support and no deprecation date. |
| `groq` `openai/gpt-oss-120b` | **Not verified live.** In LiteLLM's catalogue with tools + JSON-schema support, no deprecation date. Replaces `llama-3.3-70b-versatile`, which the same catalogue marks **deprecated from 2026-08-16** — the design's original Groq pick. |
| `hf_local` `Qwen/Qwen2.5-VL-3B-Instruct` + adapters | Not touched (P5-D5). |

First thing to do once a Gemini/Groq key is available: one call per entry in `config/models.yaml`
(`VMS_LLM_PROFILE=cloud` covers all of them), and fix any tag that answers "model not found".

## Not yet measured

- Long-context latency (rerank / incident synthesis prompts near the 8192-token window).
- Tool-calling reliability of `qwen2.5:3b` (the assistant's loop) — an answer-quality question for P6-D2.
- Throughput under concurrent requests (Ollama serialises with `OLLAMA_NUM_PARALLEL=1`; the
  lease already serialises different families).
- `hf_local` VRAM and latency with the two LoRA adapters (P5-D5).
- End-to-end event → verified alert latency with the real `event_verify` prompt (P3-D4).

## Reproduce

```bash
OLLAMA_MAX_LOADED_MODELS=1 ollama serve &                 # default settings otherwise
ollama pull qwen2.5vl:3b && ollama pull qwen2.5:3b
uv run python ml/evaluation/llm_benchmark.py --runs 5      # the model alone
uv run python ml/evaluation/llm_benchmark.py --runs 5 --co-resident-gib 0.7   # + perception-sized neighbour
```

Stop perception first for the first run (`nvidia-smi` should show ~12 MiB used), and use a
scratch Redis db (`--redis-url`, default db 9 — it is flushed).
