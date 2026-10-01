# frontend

React dashboard for GenAI-VMS (P1-J4: scaffold & app shell). Vite + React
(JavaScript, no TypeScript) + Tailwind CSS + shadcn/ui primitives, TanStack
Query for server state, React Router for navigation.

## Run

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api to VMS_API_URL (default http://localhost:8000)
npm run build
npm run lint
npm run format:check
npm test
```

## Layout

```text
src/
├── app/            # router, providers, ProtectedRoute, AppShell (nav rail + header + alert tray)
├── components/ui/  # shadcn primitives (Button, Input, Label) — tsx: false, tokens only
├── features/<name>/
│   ├── api.js       # TanStack Query hooks
│   ├── schemas.js   # zod schemas for API responses
│   └── pages/
├── lib/             # apiClient (fetch + token refresh), tokenStore, utils
└── styles/          # tokens.css (docs/style_guide.md §B.3), globals.css
```

## Auth

`lib/apiClient.js` attaches the access token (kept in memory only) to every
request and transparently refreshes it from the refresh token (persisted in
`localStorage`) on a 401, retrying the request once. `ProtectedRoute`
redirects to `/login` when there's no refresh token or refresh itself fails.

## What's here

- **P1-J4** — shell: routing, auth, layout chrome, design tokens.
- **P1-J5** — live camera wall (`features/live-wall`) and camera settings
  (`features/cameras`): WHEP-first playback with hls.js fallback
  (`lib/mediamtx.js`, `components/VideoTile.jsx`). The fallback also fires
  when WebRTC negotiates but never shows a frame (5 s) or the connection
  fails/closes afterwards — e.g. MediaMTX drops the session of an H.264
  stream with B-frames, which WebRTC can't carry (HLS handles it, ~15 s to
  start on a 5 s keyframe interval).
- **P2-J5** — playback page (`features/playback`): camera + date/time range
  picker, hls.js loading `services/api`'s generated `.m3u8` playlist (auth
  header injected via hls.js's `xhrSetup` for the manifest only — segment
  URLs are presigned and S3 rejects a second auth type — since it loads the
  manifest directly rather than through `lib/apiClient.js`), and the timeline
  scrubber v1 (`components/TimelineScrubber.jsx`, docs/style_guide.md
  §B.6 reduced to one lane — no events/phases/correlation links yet, those
  need data phase 3+ stories haven't built): density sparkline, 2px accent
  playhead, drag/click to scrub, arrow-key steps (1s, Shift+arrow 10s).
  Player time <-> wall-clock mapping via each HLS fragment's
  `#EXT-X-PROGRAM-DATE-TIME` lives in `features/playback/lib/programDateTime.js`
  (pure, unit-tested — handles clamping past either end of the loaded range
  and scrubbing into a genuine mid-recording gap, not just a
  `#EXT-X-DISCONTINUITY`).

  Verified for real: logged into a real running `services/api` + Postgres
  (with the P2-J1..J4 migrations applied) via a scripted Playwright
  session — camera picker populated from real camera rows, timeline
  scrubber rendered and responded to both click-to-scrub and keyboard
  step, console had no unexpected errors. Not verified: actual HLS video
  frames playing, since no real ingestion pipeline has produced recorded
  segments in this environment — the page correctly shows its "Playback
  failed" fallback for that case instead of crashing. Verify the full
  happy path once real footage exists (`make sim` + the ingestion/
  perception/indexer pipeline actually running for a while).
- **P2-J6** — detection overlay on the same page
  (`components/DetectionOverlay.jsx`, `components/TrackSummaryPanel.jsx`):
  a canvas drawn on a `requestAnimationFrame` loop (not React state, which
  only updates on `timeupdate` — too coarse for the ≤200ms drift AC) that
  reads `videoEl.currentTime` directly each frame, maps it to wall-clock
  via the same `programDateTime.js` the scrubber uses, and looks up the
  nearest `/twin/{camera}/frames` frame within a 1s staleness budget.
  Bboxes are mapped through the video's own `object-contain` letterboxing
  so they land on the actual picture, not the container. A "Detections
  on/off" toggle; clicking a box opens `TrackSummaryPanel` (fetches
  `GET /tracks/{track_id}` — category, dwell, zones, attributes). The
  canvas reserves the native `<video controls>` bar's height so it stays
  clickable when overlays are on, and is `pointer-events-none` when off.
  `/twin` is queried in `OVERLAY_WINDOW_SECONDS` (60s) windows aligned to
  the active range's start, matching the endpoint's own window cap and
  keyed so TanStack Query only refetches when the playhead actually moves
  into a new window. Not verified against real footage for the same
  reason as P2-J5 (no indexed twin data in this environment yet).

Phase 2 (both tracks) is now fully implemented.
