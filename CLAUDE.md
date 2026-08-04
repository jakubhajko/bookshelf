# CLAUDE.md

## Project purpose

Build the local-first, AWS-ready Pinterest-inspired book discovery application described in `APP_SPECIFICATION.md`.

The application is the current scope. The full modular recommendation funnel is not.

## Before changing code

1. Read `APP_SPECIFICATION.md`.
2. Inspect the repository.
3. Read current ADRs and `docs/implementation/plan.md`.
4. Preserve approved architecture unless the specification contains a contradiction.
5. Do not ask questions already answered by the specification.

When a detail is genuinely missing, choose a conservative, reversible default and document it.

## Work style

- Plan before broad edits.
- Implement one coherent phase or vertical slice at a time.
- Keep a checklist in `docs/implementation/plan.md`.
- Run tests, lint, and type checks after each phase.
- Do not claim completion while commands fail.
- Summarize changed files and remaining issues.
- Prefer focused edits over repo-wide rewrites.
- Add an ADR for a new architectural decision.

## Non-negotiable architecture

- Monorepo modular monolith.
- React/TypeScript/Vite frontend.
- Python/FastAPI backend.
- PostgreSQL with SQLAlchemy and Alembic.
- Independent typed Python recommender package.
- No microservices in version one.
- No Redis, Celery, Kafka, RabbitMQ, or Kubernetes.
- No SQLite integration-test substitute.
- No final recommendation funnel yet.
- No direct frontend database access.
- No recommendation algorithms in routes.
- No FastAPI/ORM imports in recommender package.
- Services own transactions; repositories never commit.
- No open DB transaction during recommendation inference.
- Environment configuration and storage abstractions.
- Stateless API containers.

## Domain rules

- One catalog row equals one book.
- Public ratings 0.5–5.0; internal integer 1–10.
- Rating means read/known; no separate read state.
- Rating and Not Interested are mutually exclusive.
- Shelf membership is independent.
- One book may be in multiple shelves.
- Not Interested may remain shelved.
- Other-shelf books remain eligible in shelf discovery.
- Historical rating 0 is implicit, not negative.
- Historical users are not application users.
- Historical data has no timestamps; never invent them.

## Security

- Argon2id.
- HttpOnly auth cookies.
- Hashed refresh tokens.
- CSRF protection.
- Exact credentialed CORS.
- No secrets, tokens, passwords, or stack traces in logs/responses.
- Ownership checks.
- Safe cover path resolution.

## Quality

A feature is not done until:

- critical tests exist;
- type checking passes;
- lint passes;
- PostgreSQL migrations work;
- loading/error/empty states exist;
- critical controls are keyboard accessible;
- documentation is updated.

## Commands to maintain

```text
make setup
make dev
make up
make down
make migrate
make import-data
make seed-demo
make build-popularity
make test
make lint
make typecheck
make e2e
make generate-api-client
```

Follow the phases in `APP_SPECIFICATION.md`. Do not attempt all phases in one uncontrolled edit.
