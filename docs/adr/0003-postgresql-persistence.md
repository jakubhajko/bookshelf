# ADR-0003: PostgreSQL as the sole persistence store, via SQLAlchemy + Alembic

## Status

Accepted (approved in `APP_SPECIFICATION.md` §3.2, §8, §20 before implementation started).

## Context

The application needs relational integrity (foreign keys, unique constraints,
check constraints for the rating/Not-Interested invariant in §5.2), full-text
and trigram search (§9.6), append-only event history, and a credible path to
later semantic search via `pgvector` — all without introducing a second
datastore or a cache/queue layer this early.

## Decision

PostgreSQL is the only database, in every environment including integration
tests (never SQLite, even for speed). Access is through SQLAlchemy 2.x
(synchronous, request-scoped sessions) with Alembic migrations, `psycopg` 3 as
the driver. `pg_trgm` is enabled for fuzzy title search; `vector` (pgvector)
may be enabled later for semantic search but is not required now. Repositories
never commit; services own transaction boundaries (spec §11).

## Alternatives considered

- **SQLite for tests/dev, PostgreSQL for production** — explicitly rejected
  by spec §8, §20 ("Do not use SQLite," "No SQLite integration-test
  substitute"). SQLite's weaker constraint/type/extension support (no
  `pg_trgm`, no `jsonb`, different NUMERIC semantics) would let bugs pass
  locally and fail in production.
- **Async SQLAlchemy sessions** — rejected for now in favor of synchronous
  sessions with request-scoped lifecycles (simpler transaction reasoning,
  matches spec §11's explicit instruction); recommendation inference itself
  must not hold a DB transaction open regardless of sync/async.
- **Redis for caching/session storage** — explicitly rejected by spec §2/§20.
  Refresh sessions are DB-backed rows in `auth_sessions`, not a cache entry.

## Consequences

- Every developer and CI environment needs a real PostgreSQL instance; there
  is no "just run it in-memory" shortcut. This repo provisions that via
  Docker Compose (`db` service) or, where Docker isn't available, a
  project-local native Postgres cluster (see ADR-0010).
- Check constraints (e.g. `user_book_states`: rating is null or 1–10, rating
  and `not_interested` cannot both be set) are enforced at the database level
  in addition to service-layer validation, so the invalid state in spec §5.2
  is unreachable even if a service-layer bug exists.
- `pgvector` readiness means the Postgres image/extension story is decided
  now (Homebrew `postgresql@17` locally, matching image family in Docker/RDS
  later) even though nothing uses vector columns yet.
