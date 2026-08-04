# ADR-0002: Monorepo with explicit module boundaries

## Status

Accepted (approved in `APP_SPECIFICATION.md` §3.1, §4 before implementation started).

## Context

The system has three deployable/importable units that evolve together during
early development: the FastAPI backend, the React frontend, and the
recommender package. Keeping them in lockstep (shared types via generated
OpenAPI client, coordinated schema/contract changes) is easier in one
repository during this phase of the project.

## Decision

Single repository (`book-recommender/`) with top-level `apps/` (deployable
applications: `api`, `web`), `packages/` (importable libraries: `recommender`),
`scripts/`, `tests/` (cross-cutting integration/E2E), `data/`, `docs/`, and
`infra/`, exactly as laid out in spec §4. Each app/package owns its own
dependency manifest (`apps/api/pyproject.toml`, `apps/web/package.json`,
`packages/recommender/pyproject.toml`) — there is no single repo-wide
dependency file. Python packages are tied together with a `uv` workspace at
the repo root.

## Alternatives considered

- **Polyrepo (separate repos for api/web/recommender)** — rejected for this
  stage. Would require publishing the recommender as a versioned package and
  the OpenAPI client as a separate consumable artifact well before either is
  stable, adding release overhead with no current benefit.
- **Single flat Python project with the frontend as a static folder** —
  rejected. Conflates two different toolchains (uv/Python, npm/TypeScript)
  and makes independent versioning/CI of the frontend awkward.

## Consequences

- CI must run backend and frontend jobs independently (different toolchains,
  different lint/type/test/build commands) even though they live in one repo.
- A future split into separate repos remains straightforward: `apps/api` and
  `packages/recommender` are already independent `uv` workspace members, and
  `apps/web` is already a self-contained npm package with no path outside
  itself except the generated API client.
- Root-level tooling (Makefile, CI) must know how to fan out into each
  sub-project rather than assuming one language/toolchain.
