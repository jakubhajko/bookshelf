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
make seed-demo               demo user/data (Phase 4+)
make build-popularity        popularity recommendation artifact (Phase 5)
make e2e                     Playwright critical-flow tests (Phase 9)
make generate-api-client     frontend client from the OpenAPI schema (Phase 6)
```

Targets tagged with a future phase above print what phase adds them and
exit 0 rather than fail — see `docs/implementation/plan.md` §6.

## Current status

Phases 0-2 are complete: monorepo foundations (config, logging, health
endpoints, CI, a Vite/React/TypeScript shell), plus the full catalog data
layer — SQLAlchemy models and Alembic migrations for books/authors/genres/
shelf-tags/similarities, a dataset adapter + CLI that imports
`books.parquet` into PostgreSQL (idempotent, batched, dry-run capable,
report-generating), trigram/full-text search indexes, and local cover
storage. The full 92,526-book catalog has been imported and verified
end-to-end, including a live fuzzy-search check against the trigram index.
Authentication, product API endpoints, and UI don't exist yet — see the
phase-by-phase plan and acceptance checklist in
[`docs/implementation/plan.md`](docs/implementation/plan.md) for exactly
what's done versus what Phase 3 onward adds.

## AWS design

Local-first now, mapped onto AWS without a rewrite later (stateless API
containers, environment-based config, storage abstractions). See
[`infra/aws/README.md`](infra/aws/README.md) and
[`docs/adr/0009-local-first-aws-ready-design.md`](docs/adr/0009-local-first-aws-ready-design.md).
Nothing in that mapping is provisioned in version one.
