# CodeXRay web

Marketing landing page and live operations console for CodeXRay, built with
Next.js 16 (App Router), React 19, and TypeScript.

## Routes

- `/` — landing page: product story, interactive service graph, demo video, FAQ.
- `/dashboard` — operations console: live telemetry feed, service graph, incidents,
  trace waterfalls, log explorer, incident replay, and the BYOK AI investigation drawer.

## Development

```bash
npm install
npm run dev          # http://127.0.0.1:3100
```

The dashboard talks to the CodeXRay API, which defaults to `http://127.0.0.1:3101`
(see `services/api` in the repo root). Point it elsewhere with:

```bash
NEXT_PUBLIC_CODEXRAY_API=https://api.example.com npm run dev
```

## Checks

```bash
npm run lint
npm run build
```

CI builds with `next build --webpack`: on Next 16.3.5 the default Turbopack build
fails to resolve the three `next/font/google` queries in `app/layout.tsx`.

## Structure

- `app/` — routes, root layout, global and dashboard styles.
- `components/` — landing sections and dashboard panels.
- `lib/api.ts` — typed API client and WebSocket helpers.
