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
├── components/      # shared app components (VideoTile, SeverityBadge)
├── components/ui/  # shadcn primitives (Button, Input, Label, Dialog, Textarea, Sonner toaster) — tsx: false, tokens only
├── features/<name>/
│   ├── api.js       # TanStack Query hooks
│   ├── schemas.js   # zod schemas for API responses
│   └── pages/
├── lib/             # apiClient (fetch + token refresh), tokenStore, ws (live channel), time, utils
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

- **P3-J4** — alerts and events (`features/alerts`, `features/events`):
  - **Alert tray** (`AppShell` → `AlertTray`, `AlertItem`): the open and acknowledged alerts, newest
    first, each with a 3 px severity bar, `SeverityBadge` (colour + label + shape: ○ ◐ ▲ ■), camera,
    "2 min ago, 15:45:20" (relative only ever next to the absolute IST time) and _Acknowledge_ /
    _Resolve_ / _Open_. Acknowledge and Resolve open a note dialog (`AlertNoteDialog`; the button
    keeps the action's name, a toast says "Alert acknowledged"); a 409 (someone else got there first)
    says what the alert is now and refreshes the tray. Focus returns to the button that opened the
    dialog (Radix only does that for a `Trigger`; `AlertNoteDialog` is opened by state).
  - **Live updates** (`LiveAlertsProvider`, `lib/ws.js`): one WebSocket per tab for operators and
    admins (a viewer gets 403 on the api and no socket here). New and changed alerts go straight
    into the TanStack Query caches (`liveCache.js`); a push carries no presigned keyframe urls, so an
    update is _merged_ and never wipes urls already held. The socket reconnects with backoff
    (1, 2, 5, 10, 30 s), re-mints the access token on the server's 4401 close (token expiry), and
    after any reconnect refetches the alerts — pub/sub keeps nothing, a push is a hint. While it is
    down the tray says "Live updates paused. Reconnecting…".
  - **Accessibility** (§B.10): two always-mounted live regions — new alerts are announced
    `polite`, critical ones `assertive`; only a new high/critical alert pulses, once, for 600 ms
    (`prefers-reduced-motion` cuts it to nothing); visible 2 px focus ring; every action is
    keyboard-operable.
  - **Events page** (`/events`) with filters for status, severity, camera and time range, kept in the
    url so a view can be shared; cursor pagination ("Show more"). **Event detail**
    (`/events/:id`): the clip (hls.js on `GET /recordings/{camera}/playlist.m3u8`, 10 s either side),
    keyframes (presigned urls; an expired link says how to get a fresh one), the vision model's
    description with its confidence ("Low confidence — review the clip before acting."), the facts,
    and the correlated events with why they were linked (`GET /correlations/{id}`). Operators and
    admins only; a viewer is told so.
  - The JSON the tests use is generated from the api's own response models
    (`services/api/tests/unit/test_frontend_fixtures.py` writes
    `features/alerts/fixtures/*.json` and fails if they drift), and the zod schemas are tested against
    the same files.

  Verified for real, in headless Brave against a real `services/api` (uvicorn) with a scratch
  Postgres, the dev Kafka, Redis and MinIO, and the last minutes of the dev stack's `cam01`
  recordings: sign in through the UI as operator, second operator and viewer; Kafka
  `event.v1` → alert in the tray with no reload, the 600 ms pulse and its end, the polite and
  assertive announcements; a second operator acknowledges and the first sees it live; correlation
  links appear live; filters, shared links and the empty states; the clip really decodes (a 40 s
  HLS clip), keyframes load from presigned MinIO urls; a viewer gets no nav item, no alerts and no
  socket; `prefers-reduced-motion`; keyboard-only acknowledge with focus restored; the access token
  (set to 1 minute) really expiring → 4401 → refresh → reconnect → alerts still arrive; the api
  stopped and restarted → "paused" notice → recovery. 74 checks, 0 failures. A 112-variant mutation
  check of the frontend (one deliberate bug at a time) is killed 112/112; the first run missed 14
  and found real test gaps (two stale-socket races, the nav gating, history `replace`, ordering).

  Not verified / not done: only Chromium (Brave) was driven, no Firefox or Safari; screen-reader
  announcements are verified as live-region DOM, not with an actual screen reader; the light theme
  is not visually checked; at 1024–1439 px the tray stays a collapsible column rather than becoming a
  drawer (§B.5; the shell never had that). **The Events page lists events that raised an alert**
  (`GET /alerts`), not every verified event: `GET /events` needs P3-D4's `events.events` table, and the
  page switches its source then. The time-range inputs are `datetime-local` (the browser's own time
  zone, as on the Playback page) while every displayed time is IST. The WebSocket token is a url
  parameter (browsers cannot set headers on a WebSocket): a failed connection attempt shows that url in
  the browser console.

- **P3-J5** — zones and camera links, under Settings (`/settings/{cameras,zones,links}`; the
  shared tabs are `app/SettingsLayout.jsx`). Admins edit; operators and viewers see the same pages
  read-only (the api answers anyone else's write with 403, and the buttons are not offered).
  - **Zone editor** (`features/zones`, `/settings/zones?camera=<id>`): _Add zone_, then _Capture
    frame_ takes a still from the camera's live view (`captureFrame.js`, at the stream's own
    resolution) and the outline is drawn on it with `PolygonEditor`. Click the frame to add a point
    (onto an edge if you hit one); drag a point; each point is a real button, so Tab reaches it, the
    arrow keys nudge it 1 % (Shift: 5 %) and Delete removes it; _Add point_ / _Remove last point_ /
    _Clear outline_ do the same for someone who can't aim. Points are normalised 0..1 of the frame,
    which is the api's contract. A zone has a name, a type (General, Restricted, Entrance, Exit) and
    optional normal hours (an after-hours alert fires for a person outside them; the window may run
    past midnight). It is checked before it is sent — 3 to 32 points, no crossing edges
    (`polygon.js`, which also guards a sliver) — with messages that say how to fix it. The captured
    frame is kept after saving, so adding or editing another zone needs no new capture; the camera's
    other zones are drawn on it, dashed and named, with a dark glow so they read on any footage.
    Switching camera starts clean and frees the frame's blob URL.
  - **Camera links** (`features/topology`, `/settings/links`; "camera links", not "topology edges"):
    a table plus a node diagram (`CameraGraph`: cameras on a circle, dashed line = overlap, solid
    with an arrow = transit, an arrowhead at each end when people walk both ways, the timing on the
    line, links between the same two cameras in lanes of their own). The diagram is a picture; the
    table beside it is the text equivalent, and the diagram also carries a sentence-long
    `aria-label`. The form follows the api's rules (`lib.js`): an overlap takes a tolerance (0–600 s),
    a transit a shortest and longest trip (0–3600 s, longest not shorter) and a direction; when
    editing, the cameras and type are locked, because for the api they are the link's identity.
  - Deleting asks first (`components/ConfirmDialog.jsx`: names the action, can't be dismissed while
    it runs, returns focus). Errors say what happened and how to fix it
    (`lib/errorMessage.js`: the api's own 400/404/409 message, or fixed wording for a 403 and for a
    network failure).
  - Fixtures for both are generated from the api's response models
    (`services/api/tests/unit/test_frontend_fixtures_config.py`), as in P3-J4.
  - The test setup (`test/setup.js`) now defines `PointerEvent`, which jsdom lacks: without it
    `fireEvent.pointerDown({ button, clientX })` builds a plain `Event` that drops both, and a drag
    test passes or fails for the wrong reason.
  - **Found on the way, fixed in the api**: after a save the list sometimes did not refresh. The api
    commits in the exit code of a `yield` dependency, which FastAPI (0.118+) runs _after_ the response
    is sent, so the refetch could read the old rows (and nothing refetches twice). Every write
    endpoint now takes `SessionDep` (`scope="function"`: commit first, then respond); see
    `services/api/README.md`. Cameras, users and the rest had the same race.

  Verified for real, in headless Brave against a real `services/api` (uvicorn) with a scratch
  Postgres and a real MediaMTX stream (the 1.2 Mbps `cam01_lite.mp4` over WebRTC): sign in through
  the UI; the live view plays and a captured frame is a real 1280×720 picture; draw, drag, nudge,
  insert-on-edge and delete points with the mouse and keyboard (focus lands on a neighbour); save a
  zone and read it back from the api (normalised outline, the dragged and nudged points where they
  were left, Mon–Fri 22:00–06:00); edit, clear its schedule, a crossing outline refused in the UI with
  nothing sent, delete with the question first; two links between the same cameras, the api's 409 for
  a duplicate shown in the form, edit with the cameras locked, delete; an operator sees both pages
  read-only and the api refuses their write (403); no sideways scrolling at 1024 px. 59 checks, 12
  consecutive full runs with 0 failures. Before the commit-order fix the same script failed in about
  2 of 8 runs; the failing run showed the refetch returning `items=0` for a link the api already held.
  Looking at the screenshots (not only the assertions) found two more things, both fixed: saved
  zones were nearly invisible on busy footage, and two labels in the links diagram collided. A
  227-variant mutation check (one deliberate bug at a time) of the new logic and components is killed
  220/227; the first run missed 33, which found real test gaps (the api's limits as literals, the
  boundary of "too small", a click on an edge's extension, each way two segments can touch, the
  "Saving…" state, focus on pointer-down) and 4 branches that could never run (removed). The 7 that
  survive are equivalent: tie-breaks and exact floating-point boundaries, `count < 3` for a triangle,
  focusing index −1, and `isConnected` where jsdom behaves the same.
  Not verified: Firefox and Safari, a real screen reader, the light theme, touch input, the HLS
  fallback for capturing a frame (WebRTC was used), and that the events service picks a new zone up
  (it reads `/internal/v1/zones`; nothing here ran it). Zones can only be drawn while a camera is
  streaming, because the api has no snapshot endpoint.
