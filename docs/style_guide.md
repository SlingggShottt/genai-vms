# Style Guide

Part A covers code, Git, APIs and messages. Part B covers the dashboard's visual and interaction design. When in doubt, match the surrounding code and ask in the PR.

---

# Part A — Engineering conventions

## A.1 Python

**Tooling (enforced in pre-commit + CI):** `ruff format` (line length 100), `ruff check` with rules `E,F,W,I,B,UP,SIM,ASYNC,S,N`, `pytest`.

**Rules**
- Python 3.11, type hints on every public function and method. No bare `except:`.
- Async all the way in services: no blocking I/O inside `async def` (use `asyncio.to_thread` for CPU/GPU work such as model inference).
- Pydantic v2 models for anything crossing a boundary (HTTP, Kafka, S3 JSON, LLM output). Plain dataclasses internally are fine.
- Configuration only through `vms_common.config` settings classes; never read `os.environ` directly in business code.
- Logging only via `vms_common.logging.get_logger(__name__)`; log events as `snake_case` names with key-value context: `log.info("segment_indexed", segment_id=sid, tracks=n)`. Never log secrets, tokens, or full prompts containing user data at INFO.
- Docstrings: Google style on public functions; one-line docstrings are fine when obvious.
- Timestamps: timezone-aware UTC `datetime` everywhere; convert to IST only in presentation.
- IDs: `uuid7()` helper from `vms_common.ids`.

**Naming**
| Thing | Style | Example |
|---|---|---|
| Modules, functions, variables | `snake_case` | `build_query_plan` |
| Classes, Pydantic models | `PascalCase` | `QueryPlan`, `EventV1` |
| Constants | `UPPER_SNAKE` | `DEFAULT_SAMPLE_FPS` |
| Kafka topics | `vms.<domain>.v<n>` | `vms.events.v1` |
| Prometheus metrics | `vms_<area>_<name>_<unit>` | `vms_search_stage_seconds` |
| Env vars | `VMS_<AREA>_<NAME>` | `VMS_KAFKA_BOOTSTRAP` |

**Service layout** (every service)
```text
services/<name>/
├── pyproject.toml
├── Dockerfile
├── src/<name>/
│   ├── main.py          # app/worker entrypoint only
│   ├── settings.py
│   ├── api/             # FastAPI routers (HTTP services)
│   ├── consumers/       # Kafka handlers (worker services)
│   ├── domain/          # pure logic — no I/O, most tests live here
│   ├── adapters/        # DB, S3, Qdrant, gateway wrappers
│   └── schemas.py       # service-local Pydantic models
└── tests/
    ├── unit/
    └── integration/     # testcontainers (Kafka, Postgres, Qdrant)
```
- `domain/` must not import `adapters/` (import-linter rule).
- Services never import another service's package — only `libs/*`.

**Testing**
- Unit tests for `domain/` are mandatory for every story. Integration tests for consumers and repositories.
- LLM calls in tests use `FakeGateway` with recorded responses; no network calls in CI.
- Test names: `test_<unit>_<condition>_<expected>`.

## A.2 JavaScript / React

**Tooling:** ESLint (`eslint-plugin-react`, `react-hooks`, `jsx-a11y`, `import`), Prettier (2 spaces, single quotes, semicolons on, trailing commas `all`, print width 100), Vitest.

**Rules**
- Function components + hooks only. No class components.
- Files: components `PascalCase.jsx`, hooks `useThing.js`, utilities `camelCase.js`.
- Feature folders:
```text
frontend/src/
├── app/            # router, providers, layout shell
├── components/ui/  # shadcn-generated (do not hand-edit beyond tokens)
├── components/     # shared app components (VideoTile, Timeline, SeverityBadge…)
├── features/<feature>/
│   ├── api.js      # TanStack Query hooks for this feature
│   ├── schemas.js  # zod schemas for responses/forms
│   ├── components/
│   └── pages/
├── lib/            # apiClient, sse, time, format
└── styles/         # tokens.css, globals.css
```
- All API responses are parsed with zod in `features/*/api.js` before reaching components.
- Server state in TanStack Query; UI/transient state in component state or Zustand. Never copy query data into Zustand.
- Document non-obvious prop shapes with JSDoc `@typedef` / `@param`.
- Times: store ISO UTC strings; format with `lib/time.js` (`formatClock`, `formatRange`) in Asia/Kolkata.
- No inline hex colours or arbitrary Tailwind values for colour/spacing; use tokens (Part B).

## A.3 Git workflow

- **Trunk-based:** `main` is always deployable. Short-lived branches (≤ 3 days).
- **Branch names:** `<track>/<story-id>-<slug>` → `d/P2-D2-bytetrack-state`, `j/P3-J2-correlation-core`. Contracts: `contract/<name>-v<n>`.
- **Commits:** Conventional Commits with scope = service/area: `feat(perception): persist tracker state in redis`, `fix(api): refresh token rotation`, `docs(srs): add FR-SRC-10`, `contract(event): add verification.latency_ms`.
- **PRs:** one story per PR where possible; template includes story id, acceptance-criteria checklist, screenshots for UI, test evidence. The **other builder reviews** every PR; contract PRs need both.
- **CODEOWNERS** mirrors `design_architecture.md §3`.
- Merge by squash. No force-push to `main`.
- Tags: `phase-1`, `phase-2`… at each review demo.

## A.4 Contracts & Kafka

- Contracts live only in `libs/vms_common/contracts/`; each model has `schema_version: Literal["<name>.v<n>"]`.
- Adding an **optional** field = minor, same topic. Removing/renaming/retyping = new major version + new topic.
- Every contract has ≥ 1 fixture in `libs/vms_common/fixtures/` and a round-trip test.
- Handlers are idempotent; never commit an offset before the side effect is durable.
- Message size ≤ 1 MB; put blobs in object storage.

## A.5 REST API conventions

- Base path `/api/v1`; plural nouns (`/cameras`, `/incidents`); actions as sub-resources (`POST /alerts/{id}/ack`).
- JSON `snake_case` fields; ISO-8601 UTC timestamps; ids as strings.
- Pagination: cursor-based `?limit=50&cursor=…` → `{ "items": [], "next_cursor": null }`.
- Filtering: `?start=&end=&camera=cam01&camera=cam02`.
- Errors (all services):
```json
{ "error": { "code": "CAMERA_NOT_FOUND", "message": "Camera cam09 does not exist.", "details": {}, "request_id": "…" } }
```
- Status codes: 400 validation, 401 unauthenticated, 403 forbidden, 404 not found, 409 conflict, 422 unprocessable GenAI output, 429 rate limited, 503 dependency unavailable (GPU/LLM) with `Retry-After`.
- Long-running work returns `202 Accepted` + job id; progress via WS `job.progress`.

## A.6 Prompts

- Prompts live in `libs/vms_common/llm/prompts/<task>/<version>.md` (Jinja2). Never inline long prompts in code.
- Every prompt declares: role, inputs (inside `<data>` tags), output schema, refusal/"not found" behaviour.
- Bump the version when wording changes; the version is recorded in provenance and evaluation results.

## A.7 Notebooks & ML code

- Notebooks in `ml/training/` are thin: they call functions from `ml/` packages. Clear outputs before commit (`nbstripout`).
- Every experiment logs: git commit, dataset manifest hash, hyperparameters, metrics, adapter URI.
- Dataset splits are by **source video**, fixed seed, manifest committed.

## A.8 Documentation

- Update the relevant doc in the same PR when behaviour, contract or requirement changes.
- Each service has a short `README.md`: purpose, run, config, topics, metrics.

---

# Part B — UI design system

## B.1 Brief

**Subject:** a security operations console for a campus control room. **Audience:** operators on long shifts, supervisors reading reports, investigators reconstructing incidents. **Primary job:** notice what matters, find it fast, trust the explanation.

The visual language borrows from the night-shift control room: slate monitors, camera feeds as the brightest things on screen, and colour used as a signal, never as decoration. The one memorable element is the **timeline scrubber** — the thread that ties cameras, events, phases and incidents together. Everything else stays quiet.

## B.2 Principles

1. **Footage first.** Video tiles are the brightest, largest surfaces; chrome recedes.
2. **Warm means attention, cool means interface.** Warm hues are reserved for severity. Interactive selection, focus and the playhead use the cool accent. Never mix the two meanings.
3. **Every GenAI claim shows its evidence.** Citations, evidence thumbnails and model provenance are part of the component, not an afterthought.
4. **Density without clutter.** Operators want information density; achieve it with alignment and tabular numbers, not boxes around everything.
5. **Calm by default, loud on purpose.** Only new high/critical alerts may animate.

## B.3 Colour tokens

Dark theme is the default (control rooms are dim). A light theme exists for reports/print.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg` | `#1A222C` night slate | `#F5F7F9` | App background |
| `--surface` | `#222C38` console | `#FFFFFF` | Panels, sidebars |
| `--surface-raised` | `#2A3645` | `#EEF1F4` | Popovers, hovered rows |
| `--rule` | `#35434F` | `#D5DCE3` | Dividers, input borders |
| `--text` | `#D3DBE3` fog | `#1C2733` ink | Primary text |
| `--text-muted` | `#8A99A8` | `#5A6978` | Secondary text, timestamps labels |
| `--accent` | `#5EC4CF` monitor cyan | `#16808B` | Focus ring, selection, playhead, primary buttons |
| `--accent-ink` | `#0E2A2E` | `#FFFFFF` | Text on accent |
| `--sev-low` | `#8FB3C9` steel | `#3F6F8C` | Low severity |
| `--sev-medium` | `#D9B64A` ochre | `#9A7A12` | Medium severity |
| `--sev-high` | `#E57C3C` sodium | `#B4531A` | High severity |
| `--sev-critical` | `#E5484D` signal red | `#B8272D` | Critical severity |
| `--ok` | `#6FB58A` | `#2F7A4B` | Camera online, success |
| `--video-bg` | `#000000` | `#000000` | Behind video only |

Rules: severity is always shown with **colour + label + icon shape** (low ○, medium ◐, high ▲, critical ■) for colour-blind safety. Contrast ≥ 4.5:1 for text. Defined as CSS variables in `styles/tokens.css` and mapped into Tailwind/shadcn theme variables — components never use raw hex.

## B.4 Typography

| Role | Typeface | Notes |
|---|---|---|
| UI and body | **Barlow** (400, 500, 600) | Grotesk derived from highway signage — legible at small sizes, fits an infrastructure product |
| Camera names, tile labels, dense tables | **Barlow Semi Condensed** (500, 600) | Saves width on the camera wall |
| Report PDFs body | **Source Serif 4** (400) | Long-form reading; paired with Barlow headings |

- All numbers that change or align (timestamps, counts, scores) use `font-variant-numeric: tabular-nums`. No monospace font for data.
- Scale (1.2 minor third, base 14 px): 11.7 · 14 · 16.8 · 20.2 · 24.2 · 29 px. Line height 1.45 for body, 1.2 for headings.
- Sentence case everywhere: buttons, labels, headings. No all-caps labels, no eyebrow labels above headings.
- Line length ≤ 80 characters in reports and assistant answers.

## B.5 Layout

```text
┌──────┬───────────────────────────────────────────────────────┬─────────────┐
│ nav  │  page header: title · camera/time context · actions   │ alert tray  │
│ rail │───────────────────────────────────────────────────────│ (collapsible│
│ 56px │                                                       │  320px)     │
│      │   main work area (video / results / report)           │             │
│      │                                                       │             │
│      │───────────────────────────────────────────────────────│             │
│      │   timeline dock (playback, investigation)             │             │
└──────┴───────────────────────────────────────────────────────┴─────────────┘
```
- Left-aligned content; the camera wall is the only grid of equal tiles.
- Spacing scale 4 px base: 4, 8, 12, 16, 24, 32, 48.
- Radius carries hierarchy: video tiles **2 px** (they are monitors), panels and inputs **6 px**, badges/pills **full**. Do not use one radius for everything.
- Separation by `--rule` hairlines and surface steps, not drop shadows. Shadows only on floating layers (popover, dialog, toast).
- Breakpoints: ≥ 1440 full console; 1024–1439 alert tray becomes a drawer; < 1024 read-only views (incidents, reports, assistant) remain usable.

## B.6 Signature component — the timeline

The timeline appears in Playback, Event detail, Investigation and Incident views with the same visual grammar:

```text
 cam02 ┤▁▂▂▃▅▇▅▂▁ ▁▁▂▁        ▲intrusion
 cam04 ┤   ▁▁▂▃▃▂▁▁▁  ▁▂▅▇▅▂   ▲intrusion ─ ─ ─ ─ ─ ┐ link 38 s
       ├───baseline──┼precursor┼escal.┼──action──┼aftermath┤
       10:14:30        10:15:00        10:15:30        10:16:00
                               │ playhead (accent)
```
- **Lanes:** one per camera; density sparkline in `--text-muted` at 40 % opacity.
- **Events:** severity shape markers on the lane; correlation links drawn as dashed connectors between lanes.
- **Phases:** a band under the lanes with the five phases, labelled in text (not colour-coded) — phase is structure, not severity.
- **Playhead:** 2 px `--accent` line with a time label using tabular numbers.
- **Interactions:** drag to scrub, wheel + Ctrl to zoom, click marker to jump, shift-drag to select a range (→ "Search in range", "Save to case").
- Keyboard: ← → step 1 s, Shift ← → step 10 s, `[` `]` previous/next event.

## B.7 Components

| Component | Spec |
|---|---|
| **VideoTile** | Black bg, 2 px radius. Overlay top-left: camera name (Semi Condensed 500) + status dot (`--ok`/`--sev-high`/`--text-muted`). Bottom-left: wall-clock time. Bboxes: 1.5 px `--accent` stroke with track id label; the matched object in search results uses a 35 % `--accent` mask fill. No gradients over video. |
| **SeverityBadge** | Pill, shape icon + label, tinted background at 16 % of the severity colour, text in full colour. |
| **AlertItem** | Left 3 px severity bar, title, camera, relative + absolute time, actions *Acknowledge* / *Open*. New high/critical: one 600 ms background pulse, then still. Respect `prefers-reduced-motion`. |
| **EvidenceChip** | Small thumbnail + label (`cam02 10:15:04`), opens clip at timestamp. Used for citations in reports and assistant answers. |
| **ReasoningTrace** | Collapsed by default to one line; expands to steps with evidence chips. Title "Why this matched". |
| **ProvenanceNote** | Muted single line under generated content: "Generated by gemini-2.5-flash, hybrid profile, prompt synth-1.0". |
| **Search bar** | Full-width input, placeholder shows a real example ("Someone left a bag near the entrance this morning"). Filter chips for cameras/time below. Image search via "Search by image" button and from any paused frame. |
| **Incident report view** | Reading layout max 760 px column; sections: Summary, Scene, Phases (with timeline), Causal chain (numbered — it is a sequence), Contributing factors, Recommended actions, Evidence. Export button "Export PDF". |
| **Assistant** | Chat column max 760 px; streaming text; tool activity shown as a single muted line ("Searched footage for …"); citations as EvidenceChips inline. |
| **Empty states** | Say what to do next: "No cameras yet. Add a camera to start recording." |

Use shadcn/ui primitives (Button, Dialog, DropdownMenu, Tabs, Table, Tooltip, Sheet, Toast/Sonner, Command) themed through tokens.

## B.8 Writing in the UI

- Name things by what operators know: "Cameras", "Zones", "Camera links" (not "topology edges"), "Search", "Incidents", "Daily reports".
- Buttons say exactly what happens and keep the name through the flow: *Acknowledge* → toast "Alert acknowledged"; *Export PDF* → "PDF exported".
- Errors state what happened and how to fix it: "Camera cam03 is unreachable. Check the RTSP address or network." No apologies.
- GenAI uncertainty is stated plainly: "Low confidence — review the clip before acting."
- Times: `10:15:04` for clock times, `5 Oct, 10:15` for dates in IST; relative time only alongside absolute ("2 min ago, 10:15").

## B.9 Motion

- User-triggered transitions ≤ 200 ms (drawers, dialogs, expanding traces).
- Only one ambient motion: the new high/critical alert pulse.
- Live video and the playhead are the motion; nothing else moves on its own.

## B.10 Accessibility checklist

- Visible 2 px `--accent` focus ring on every interactive element.
- All video overlays have text equivalents in adjacent panels (event list, results list).
- Keyboard access for timeline, camera wall layout switch, alert actions.
- `aria-live="polite"` for new alerts; `assertive` only for critical.
- Respect `prefers-reduced-motion` and `prefers-contrast`.

## B.11 PDF reports

Light theme tokens; A4; Barlow headings, Source Serif 4 body 10.5 pt; header with site name and report period; footer with page number and "Generated by GenAI-VMS, <profile>, <timestamp>"; severity badges reproduced with shape + label; evidence thumbnails in a two-column grid with captions.
