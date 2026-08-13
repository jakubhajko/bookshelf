# CLAUDE.md

## Project purpose

Build and evolve the local-first, AWS-ready Pinterest-inspired book discovery application described in `APP_SPECIFICATION.md`.

The full modular recommendation funnel is **now in scope** and is governed by `RECOMMENDER_SPECIFICATION.md` plus `RECOMMENDER_IMPLEMENTATION_PLAN.md`.

The existing application architecture is mature. Recommender work must integrate into it rather than replace it.

## Specification precedence

For recommender-related work, use this precedence:

1. this `CLAUDE.md`;
2. `RECOMMENDER_SPECIFICATION.md`;
3. current ADRs, unless a newer ADR explicitly supersedes one;
4. `APP_SPECIFICATION.md`;
5. `RECOMMENDER_IMPLEMENTATION_PLAN.md` for execution sequencing;
6. `docs/implementation/plan.md` for current progress/risk state;
7. verified live implementation details.

For non-recommender product behavior, `APP_SPECIFICATION.md` remains authoritative beneath this file and applicable ADRs.

If a document and live code differ, verify whether the code is current, placeholder or legacy. Do not silently choose one. Preserve approved behavior and document intentional architectural changes with ADRs.

## Before changing code

1. Read `APP_SPECIFICATION.md`.
2. For recommender work, read `RECOMMENDER_SPECIFICATION.md` and `RECOMMENDER_IMPLEMENTATION_PLAN.md`.
3. Inspect the repository and `git status`; preserve existing user/uncommitted changes.
4. Read current ADRs and `docs/implementation/plan.md`.
5. Inspect the actual call/data flow relevant to the phase. Do not implement from filenames or assumptions.
6. Do not ask questions already answered by specifications or repository evidence.

When a small detail is genuinely missing, choose a conservative, reversible default and document it. For a material architectural ambiguity, prefer a focused ADR rather than an ad-hoc implementation.

## Work style

- Plan before broad edits.
- Implement **one coherent recommender phase at a time** according to `RECOMMENDER_IMPLEMENTATION_PLAN.md`.
- Do not spill into the next phase after reaching a clean phase boundary.
- Keep the phase checklist and results in `docs/implementation/plan.md`.
- Run focused tests during implementation and full relevant quality checks before phase completion.
- Do not claim completion while required commands fail.
- Summarize changed files, commands run, unresolved issues and next phase.
- Prefer focused edits over repo-wide rewrites.
- Add an ADR for a new/changed architectural decision.
- Do not auto-commit or use destructive git operations unless explicitly instructed.
- Keep tunable recommender weights/config centralized and typed; do not scatter magic numbers.
- Prefer deterministic/reproducible offline builds and serving behavior.

## Non-negotiable application architecture

- Monorepo modular monolith.
- React/TypeScript/Vite frontend.
- Python/FastAPI backend.
- PostgreSQL with SQLAlchemy and Alembic.
- Independent typed Python recommender package.
- No microservices in version one.
- No Redis, Celery, Kafka, RabbitMQ, or Kubernetes.
- No SQLite integration-test substitute.
- No direct frontend database access.
- No recommendation algorithms in routes.
- No FastAPI/ORM imports in recommender package.
- Services own transactions; repositories never commit.
- **No open DB transaction during recommendation inference.**
- Environment configuration and storage abstractions.
- Stateless API containers.
- Preserve current auth/security architecture unless a phase explicitly requires a narrowly-scoped compatible addition.

## Non-negotiable recommender architecture

- Keep the existing `RecommendationProvider` / `RecommendationEngine` seam.
- Keep `InProcessProvider` and `FallbackProvider` behavior unless a verified bug requires a compatible fix.
- Keep application-owned eligibility/exclusion rules outside the recommender engine.
- Keep persisted recommendation batches/cursor paging and authoritative engine ordering.
- Runtime recommender inference receives immutable request/user/surface context plus loaded artifacts; it does not query PostgreSQL.
- Use `work_id` as durable catalog identity across offline/online boundaries. PostgreSQL `book_id` is not durable across a database rebuild.
- Every new artifact must carry/validate stable item mapping and catalog/model/preprocessing version metadata.
- Popularity remains a robust fallback.
- Five V1 candidate families:
  1. ALS CF;
  2. item-item CF;
  3. semantic/content retrieval;
  4. resolved Goodreads/source similarity;
  5. popularity.
- Home, Shelf and Similar Books share pipeline implementation but use different typed surface configuration.
- Candidate union uses weighted RRF in V1.
- V1 ranker is deterministic/interpretable; no learned engagement ranker before adequate click/open labels exist.
- Reranking/diversity happens inside the engine before the authoritative result leaves it.
- No vector database/ANN service merely for the current ~92k catalog unless profiling demonstrates a real need.
- No learned sequence/session model in V1; instrument the data for it first.

## User-behavior/data principles

- Store raw product actions and attribution, not one universal ML interaction score.
- Different generators may interpret the same raw evidence differently.
- Add/retain high-value raw signals:
  - ratings;
  - shelf saves/removals with timestamps and shelf attribution;
  - Not Interested;
  - recommendation impressions;
  - intentional `book_opened`;
  - short-lived browsing `session_id` distinct from auth session;
  - recommendation request/surface/rank attribution where known;
  - meaningful submitted searches and search→open attribution;
  - explicit onboarding taste seeds.
- Impression-without-open is exposure, not a V1 negative.
- Do not add dwell time, hover, mouse movement or scroll-depth tracking in this scope.
- Onboarding taste seeds are not fake ratings and not fake shelf saves.
- Preserve human-readable evidence/provenance so recommender behavior can be debugged.

## Semantic-interest requirements

- Default offline encoder: `Qwen/Qwen3-Embedding-0.6B`, swappable via versioned artifact configuration.
- Default embedding dimension: 512, configurable.
- Encoder runs offline during artifact build, not inside API serving.
- Deterministic book text uses title, author, description, genre and cleaned/bounded useful catalog shelf tags.
- Represent semantic user preference with both:
  - explicit shelf profiles;
  - inferred interest clusters.
- Do not force fixed K interests. Use threshold-based hierarchical/agglomerative cosine clustering with clear fallbacks.
- Inferred interest clusters must be human-inspectable with deterministic label, representative/medoid book, weight, member books, top terms/tags/genres and evidence summary.
- Inspection tooling must call the same profiling implementation used by serving.

## Collaborative-filtering requirements

- Historical rating `0` is implicit positive, never negative.
- Historical data has no timestamps; never invent them.
- Historical integer users are not application UUID users and must never be joined as identities.
- ALS global model trains offline. Live app users are folded into fixed item factors from current preference evidence on fresh batch generation; do not retrain the global model for one user mutation.
- Item-item CF trains offline; live profile changes affect seeds/weights only.
- Keep training transforms versioned/configurable and evaluate reasonable defaults rather than embedding unexplained constants.

## Domain rules

- One catalog row equals one book/work in the application domain.
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

## Security/privacy

- Argon2id.
- HttpOnly auth cookies.
- Hashed refresh tokens.
- CSRF protection.
- Exact credentialed CORS.
- No secrets, tokens, passwords, stack traces, raw high-dimensional user embeddings, or unnecessary personal data in logs/responses.
- Ownership checks.
- Safe cover/artifact path resolution.
- Recommendation diagnostics must not become an accidental sensitive-data dump.

## Quality

A feature/phase is not done until:

- critical tests exist;
- type checking passes;
- lint passes;
- PostgreSQL migrations work when changed;
- generated API client is refreshed when OpenAPI changes;
- loading/error/empty states exist for user-facing additions;
- critical controls are keyboard accessible;
- artifact build failures are explicit and safe;
- documentation/ADRs/progress plan are updated;
- fallback behavior is tested for recommender changes.

## Commands to preserve

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

Recommender implementation may add focused commands such as:

```text
make build-recommender-artifacts
make evaluate-recommender
make inspect-recommender-profile USERNAME=<name>
```

Choose exact names consistent with the existing Makefile/CLI patterns and document them.

## Heavy/offline ML dependencies

- Use the existing uv workspace/lock.
- Do not manually edit the lock file.
- Keep training-only dependencies separated from lightweight API runtime dependencies where practical.
- The transformer text encoder is an offline artifact-build dependency.
- Prefer compact NumPy/NPZ artifacts and exact batched retrieval before introducing new infrastructure.

## Phase discipline

Follow `RECOMMENDER_IMPLEMENTATION_PLAN.md`.

When resuming in a new Claude Code session, determine the first incomplete recommender phase from `docs/implementation/plan.md`, inspect the current code, work on that phase only, run its quality gates, update the plan, and stop at a clean boundary.
