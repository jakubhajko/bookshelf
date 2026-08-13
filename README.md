# Book Discovery

A logged-in, Pinterest-inspired book discovery application: masonry home
feed, search, ratings, Not Interested, shelves, and shelf-lens/similar-book
recommendations — built as a modular monolith (FastAPI + PostgreSQL +
React/TypeScript) with an independent, typed recommender package standing in
front of mock/popularity providers today and the modular recommendation
funnel now being built behind the same boundary (ADR-0013).

## Specifications

- [`archive_of_structural_prompts/app_building_prompts/APP_SPECIFICATION.md`](archive_of_structural_prompts/app_building_prompts/APP_SPECIFICATION.md)
  — the full product/engineering source of truth for application behavior.
  Written and delivered against from the repository root; relocated into
  `archive_of_structural_prompts/` once the application phases completed.
  Its content is unchanged and it remains authoritative for non-recommender
  product behavior.
- `RECOMMENDER_SPECIFICATION.md` — authoritative for recommender work,
  sequenced by `RECOMMENDER_IMPLEMENTATION_PLAN.md`.
- `CLAUDE.md` — persistent implementation rules and the precedence order
  between the above.

Current build state, phase by phase, lives in
[`docs/implementation/plan.md`](docs/implementation/plan.md); architectural
decisions are recorded as ADRs in [`docs/adr/`](docs/adr/).

## Repository layout

```text
apps/api/            FastAPI backend (src/book_app/{core,modules,shared,cli})
apps/web/             React + TypeScript + Vite frontend (apps/web/e2e/: Playwright E2E)
packages/recommender/ Typed recommendation engine/provider package (no FastAPI/ORM deps)
data/                 Dataset — gitignored except data/sample/ (small, checked-in fixture); see data/README.md
docs/                 Implementation plan, ADRs, architecture, API docs
infra/                Docker Compose support files, AWS architecture notes
scripts/              Data import / dev / model-management CLIs (added as their phases land)
tests/integration/     Real-PostgreSQL tests (migrations, catalog import, cover storage)
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
make seed-demo               create the demo_reader account with representative shelves/ratings
make build-popularity        build the popularity recommendation artifact
make e2e                     Playwright critical-flow tests (spec §13.5) — needs a running, migrated API
make generate-api-client     frontend client from the OpenAPI schema
```

## Current status

**All 9 phases are complete** — every phase in spec §18's list has landed,
and every Functional and Architecture item in spec §19's acceptance
checklist is satisfied. Backend: monorepo foundations; the full catalog
data layer (92,526 books imported); authentication (register/login/
refresh/logout/me/change-password, Argon2id, HttpOnly cookie sessions,
session-bound CSRF, auth-specific rate limiting); books/state/shelves
(ratings and Not Interested with the full spec §5.2-§5.3 state machine,
shelves CRUD with atomic multi-shelf sync, `/me/ratings`); the
recommendation boundary (`packages/recommender` — typed contracts, mock/
popularity/future-pipeline engines, fallback provider chain — plus all
three recommendation endpoints with persisted, cursor-paginated batches);
cover image serving (`GET /api/v1/covers/{object_key}`, ADR-0011); search
(`GET /search/books`, spec §9.6's seven-tier ranking, ADR-0012); and, new
in the final phase, security headers, general (non-auth) rate limiting
and a request-size cap, and a `make seed-demo` CLI. Frontend: the auth
flow and navigation shell; a responsive masonry grid used everywhere
books are listed (Home, Similar, Shelf-books, Shelf-discover, Rated,
Search) with infinite scroll, optimistic updates and rollback (spec
§12.11), and accurate state badges wherever a book can arrive already
rated/saved/Not-Interested; book detail as both a route-backed modal and
a full page, with an accessible half-star rating control and a confirm
-before-clearing Not-Interested control; shelves (collage overview,
create/rename/edit-description/delete, Books/Discover tabs); the Rated
page; search (debounced suggestions, recent searches, URL-encoded query
state); and, new in the final phase, root/route-level error boundaries
and a toast notification system wired into every optimistic mutation's
failure path.

348 tests total: 241 apps/api (unit + integration against real
PostgreSQL, 94% combined coverage — spec §13.6's 75% floor), 38
recommender package, 69 frontend, plus one Playwright end-to-end test
covering spec §13.5's full 13-step critical flow (register through
re-login, with two accessibility scans folded in) against a real
Chromium browser — see
[`docs/implementation/plan.md`](docs/implementation/plan.md) §5h for the
exact commands and results, and its acceptance checklist (§4) for what's
checked off item by item. The E2E test is where two real optimistic
-update race conditions in `useBookState.ts` were found and fixed this
phase (plan.md risk #68) — both reachable by any user clicking normally,
neither caught by any jsdom test before.

The one unchecked item in spec §19's Quality list: `docker compose up` is
authored (both Dockerfiles are now production-shaped multi-stage builds)
but not runtime-verified, since Docker has never been available in this
environment across any phase (plan.md risk #1/#65) — everything else has
been validated either by direct interactive testing or, as of this phase,
by real browser automation: Playwright now drives an actual Chromium
instance through the app's critical flow (plan.md risk #44/#66),
resolving the earlier "no interactive browser available" limitation for
the surfaces that flow covers.

## AWS design

Local-first now, mapped onto AWS without a rewrite later (stateless API
containers, environment-based config, storage abstractions). See
[`infra/aws/README.md`](infra/aws/README.md) and
[`docs/adr/0009-local-first-aws-ready-design.md`](docs/adr/0009-local-first-aws-ready-design.md).
Nothing in that mapping is provisioned in version one.
