# vms_common

Shared runtime library used by every service. Owned by Divyansh; `contracts/`
and `fixtures/` are co-owned with Jatin (see `CODEOWNERS`).

| Module | Purpose | Lands in |
|---|---|---|
| `contracts/` | Pydantic message/document schemas crossing service boundaries | per-phase, frozen day 1 (design_architecture.md §16) |
| `fixtures/` | Sample messages/documents for round-trip and `FakeGateway` tests | alongside each contract |
| `kafka/` | Async producer, consumer base class (validate → handle → commit, DLQ) | P1-D2 |
| `storage/` | S3 client (put/get/stream/presign), URI helpers | P1-D2 |
| `llm/` | `LLMGateway`, model registry, GPU lease, response cache, prompts, `FakeGateway` | P3-D3 |
| `auth.py` | Access-token JWT encode/decode (`JWTSettings`-shaped, no service state) | P1-J2 |
| `config.py` | pydantic-settings base classes | P1-D2, `DatabaseSettings`/`JWTSettings` added P1-J1/J2 |
| `logging.py` | structlog JSON logger with context binding | P1-D2 |
| `metrics.py` | Prometheus metric helpers | P1-D2 |
| `ids.py` | `uuid7()` helper | P1-D2 |

No business logic here — only what genuinely crosses a service boundary
(style_guide.md §A.1). Services never import each other, only `libs/*`.

`auth.py` and the `DatabaseSettings`/`JWTSettings` additions to `config.py`
were added from Track J (P1-J1/P1-J2) — cross-track edits to Divyansh's file,
flagged per CLAUDE.md rather than merged silently; review on next sync.

## `llm/` — the LLM gateway

Every LLM/VLM call in the system goes through `LLMGateway` (CLAUDE.md hard rule); a call names a
*task*, and `config/models.yaml` says which model serves it under the active `VMS_LLM_PROFILE`.
Design and behaviour: `docs/design_architecture.md §11`.

It lives behind the `llm` extra so ingestion/indexer/api/perception images do not ship LiteLLM:
a service that calls LLMs depends on `vms-common[llm]`.

```python
from vms_common.llm import LLMGateway, ImageInput, render_prompt

gateway = LLMGateway.from_settings()  # registry + LiteLLM + Redis lease/cache
plan = await gateway.chat(
    "query_decompose", [{"role": "user", "content": q}], response_model=QueryPlan
)  # validated, re-asked on failure
verdict = await gateway.vision(
    "event_verify",
    render_prompt("event_verify", "1.0", ...),
    [ImageInput(data=jpeg_bytes)],
    response_model=Verdict,
)
print(plan.parsed, verdict.provider, verdict.model, verdict.cached)
```

| Module | What it does |
|---|---|
| `gateway.py` | `LLMGateway` + the `Gateway` protocol services type against |
| `registry.py` | `models.yaml` loader: profiles, `extends`, per-task behaviour, validated at startup |
| `backend.py` | `LiteLLMBackend` (ollama/gemini/groq/openrouter); the `Backend` seam where `hf_local` plugs in |
| `lease.py` | Redis GPU lease (Lua; one model family at a time, heartbeat, queue, unload hint) |
| `cache.py` | Redis response cache (key = task + model + messages incl. image data + schema + params) |
| `structured.py` | JSON extraction from messy replies, validation, repair message |
| `images.py` | VLM image caps (count, long edge) |
| `prompts.py` + `prompts/` | Versioned Jinja2 prompt files (`render_prompt(task, version, **vars)`) |
| `metrics.py` | `vms_llm_request_seconds`, `vms_llm_tokens_total`, retries, fallbacks, cache, lease wait |
| `testing.py` | `FakeGateway` (scripted/recorded answers for service tests), `ScriptedBackend` (for gateway tests) |

**Testing a service that calls the gateway** — no network, no model:

```python
from vms_common.llm.testing import FakeGateway

gateway = FakeGateway(
    {"event_verify": [{"verdict": "confirmed", "confidence": 0.9, "reason": "x"}]}
)
result = await gateway.vision("event_verify", "prompt", [image], response_model=Verdict)
assert gateway.calls_for("event_verify")[0].images  # what the code under test sent
```

Replies go through the same JSON extraction and validation as production, a list is a queue
(running past its end fails loudly), and recordings can be loaded from JSON
(`FakeGateway.from_recording(path)`, failures as `{"$error": "unavailable"}`).

Config (`VMS_LLM_*`, see `.env.example`): `PROFILE`, `MODELS_PATH`, `OLLAMA_URL` (default
`http://$VMS_GENAI_HOST:11434`), `LEASE_NODE`, `LEASE_TTL_SECONDS`, `LEASE_WAIT_SECONDS`; provider keys
`GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` (env only, never logged).
