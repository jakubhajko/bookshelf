# Book Discovery

A logged-in, Pinterest-inspired book discovery application: masonry home
feed, search, ratings, Not Interested, shelves, and shelf-lens/similar-book
recommendations — built as a modular monolith (FastAPI + PostgreSQL +
React/TypeScript) with an independent, typed recommender package standing in
front of mock/popularity providers today and the real recommendation funnel
later.

`APP_SPECIFICATION.md` is the full product/engineering source of truth.
`CLAUDE.md` carries the persistent implementation rules. Current build state,
phase-by-phase, lives in [`docs/implementation/plan.md`](docs/implementation/plan.md);
architectural decisions are recorded as ADRs in [`docs/adr/`](docs/adr/).

## Repository layout

```text
apps/api/            FastAPI backend (src/book_app/{core,modules,shared,cli})
apps/web/             React + TypeScript + Vite frontend
packages/recommender/ Typed recommendation engine/provider package (no FastAPI/ORM deps)
data/                 Dataset — gitignored except data/sample/ (small, checked-in fixture); see data/README.md
docs/                 Implementation plan, ADRs, architecture, API docs
infra/                Docker Compose support files, AWS architecture notes
scripts/              Data import / dev / model-management CLIs (added as their phases land)
tests/integration/     Real-PostgreSQL tests (migrations, catalog import, cover storage)
tests/end_to_end/      Playwright E2E (Phase 9, not created yet)
```

## Prerequisites

- Python >=3.12 and [`uv`](https://docs.astral.sh/uv/)
- Node >=20 and npm
- PostgreSQL 17 (client + server) — via Homebrew, system package, or Docker
- Docker + Docker Compose (optional — see below)

## Quickstart

```bash
make setup       # uv sync (api + recommender) and npm install (web)
cp .env.example .env
```

**Option A — no Docker required** (this is what was used to build/validate
Phase 1 in the reference environment):

```bash
make db-start     # creates + starts a project-local Postgres at .pgdata/ (port 5434)
make dev-api       # terminal 1: FastAPI with reload on :8000
make dev-web       # terminal 2: Vite dev server on :5173
make db-stop       # when done
```

**Option B — Docker Compose** (`db` + `api` + `web` services, spec §16):

```bash
make up            # docker compose up --build
make down
```

Then open <http://localhost:5173>. `GET http://localhost:8000/api/v1/health/live`
and `/api/v1/health/ready` (the latter checks PostgreSQL connectivity) are
available directly against the API.

## Common commands

```text
make setup                 install all dependencies
make dev-api / make dev-web run the backend / frontend dev servers
make db-start / db-stop     project-local Postgres (no Docker needed)
make up / down / logs       Docker Compose stack
make test                   backend + recommender + frontend test suites (fast, no live Postgres)
make test-integration        catalog/migration tests against real Postgres
make lint                   ruff (backend/recommender/tests) + oxlint (frontend)
make typecheck              mypy (backend/recommender) + tsc (frontend)
make migrate                 apply Alembic migrations
make import-data[-dry-run]   import books.parquet into PostgreSQL
make cleanup-sessions        delete expired/revoked auth sessions
make seed-demo               demo user/data (Phase 9)
make build-popularity        build the popularity recommendation artifact
make e2e                     Playwright critical-flow tests (Phase 9)
make generate-api-client     frontend client from the OpenAPI schema
```

Targets tagged with a future phase above print what phase adds them and
exit 0 rather than fail — see `docs/implementation/plan.md` §6.

## Current status

Phases 0-7 are complete: monorepo foundations, the full catalog data layer
(92,526 books imported, search indexes proven against a live fuzzy query),
authentication — register/login/refresh/logout/me/change-password (spec
§9.1), Argon2id passwords, HttpOnly cookie sessions with DB-backed revocable
refresh sessions, session-bound CSRF, and a pluggable per-IP/per-username
login rate limiter — books/state/shelves: book detail (`GET /books/{id}`),
half-star ratings and Not Interested with the full spec §5.2-§5.3 state
machine and append-only event log, shelves CRUD with atomic multi-shelf
sync, and `/me/ratings` (all 5 sorts, rating-range/genre filters, cursor
pagination) — the recommendation boundary: `packages/recommender`
(typed contracts, mock/popularity/future-pipeline engines, in-process/
fallback/remote providers, artifact manifest + local storage), a
Bayesian-shrunk popularity ranking CLI (`make build-popularity`), and all
three recommendation endpoints (`GET /recommendations/home`,
`.../shelves/{id}`, `.../books/{id}/similar`) with persisted, cursor
-paginated batches and product-eligibility exclusion (spec §5.5) — the
frontend shell and auth flow: a generated, fully-typed API client, the dark
design token system, register/login/account pages, `AuthProvider`, and the
navigation shell with every spec §12.3 route wired behind the appropriate
auth guard — and now the core visual product: a real, cover-image-serving
backend route (`GET /api/v1/covers/{object_key}`, ADR-0011 — the app
renders actual book covers now, not placeholders), a responsive masonry
Home feed with infinite scroll wired to `GET /recommendations/home`, book
cards with a searchable/multi-select/create-capable shelf selector and a
Pinterest-style Save/Saved quick action, and book detail — as both a
route-backed modal (desktop) and a full page (direct navigation/mobile) —
with an accessible half-star rating control, a Not-Interested control that
confirms before clearing an existing rating, and a similar-books grid,
all wired with optimistic updates and rollback on failure (spec §12.11).
293 tests (118 apps/api unit + 100 integration + 38 recommender package
against real PostgreSQL + 37 frontend), 94% combined backend coverage. The frontend routes beyond Home/detail (search, shelves, rated)
are still placeholders — see the phase-by-phase plan and acceptance
checklist in [`docs/implementation/plan.md`](docs/implementation/plan.md)
for exactly what's done versus what Phase 8 onward adds. Frontend UI has
been verified via a production build, 37 component/integration tests, and
an HTTP-level smoke test against the live backend (which caught and fixed a
real cover-image path-resolution bug, plan.md risk #47) — not via an
interactive browser, none is available in this environment (plan.md risk
#44).

## AWS design

Local-first now, mapped onto AWS without a rewrite later (stateless API
containers, environment-based config, storage abstractions). See
[`infra/aws/README.md`](infra/aws/README.md) and
[`docs/adr/0009-local-first-aws-ready-design.md`](docs/adr/0009-local-first-aws-ready-design.md).
Nothing in that mapping is provisioned in version one.
