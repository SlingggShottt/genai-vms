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

## What's here vs. what's next

This story is the shell: routing, auth, layout chrome, design tokens. The
live camera wall and camera settings pages are placeholders — P1-J5 builds
them against the camera API that already exists (`services/api`, P1-J3).
