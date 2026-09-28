# vms_common

Shared runtime library used by every service. Owned by Divyansh; `contracts/`
and `fixtures/` are co-owned with Jatin (see `CODEOWNERS`).

| Module | Purpose | Lands in |
|---|---|---|
| `contracts/` | Pydantic message/document schemas crossing service boundaries | per-phase, frozen day 1 (design_architecture.md §16) |
| `fixtures/` | Sample messages/documents for round-trip and `FakeGateway` tests | alongside each contract |
| `kafka/` | Async producer, consumer base class (validate → handle → commit, DLQ) | P1-D2 |
| `storage/` | S3 client (put/get/stream/presign), URI helpers | P1-D2 |
| `llm/` | `LLMGateway`, model registry, GPU lease, prompts | P3-D3 |
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
