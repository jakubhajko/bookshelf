# `apps/web` — Book Discovery frontend

React + TypeScript + Vite. See the repo root `README.md` for full local setup
and `APP_SPECIFICATION.md` §12 for the product/UI specification.

```bash
npm install
npm run dev         # http://localhost:5173
npm run lint         # oxlint
npm run typecheck    # tsc -b --force
npm run test          # vitest run
npm run build         # tsc -b && vite build
```

Environment variables are read from the repo root (`../../.env`), not a
local `.env` in this directory — see `vite.config.ts`'s `envDir` and the root
`.env.example`.

Current state (Phase 1): providers (`TanStack Query`, `React Router`,
Tailwind CSS) are wired, and a single smoke route (`/`) proves the frontend
can reach the backend through `GET /api/v1/health/live`. The dark design
system, shell/navigation, and real routes land in Phases 6-8
(`docs/implementation/plan.md`).
