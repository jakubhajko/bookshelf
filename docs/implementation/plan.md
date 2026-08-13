# Implementation plan

Status: living document, updated after every phase.

This plan does not restate product rationale — see the specifications for
that. It tracks what exists, what's missing, and what to run to prove each
phase.

**Two phase sequences are tracked here.** Phase numbers are meaningless
unqualified; always say which sequence.

| Sequence | Source of truth | Phases | State |
|---|---|---|---|
| **Application** (§3) | `APP_SPECIFICATION.md` §18 | 0-9 | complete |
| **Recommender** (§3R) | `RECOMMENDER_SPECIFICATION.md`, sequenced by `RECOMMENDER_IMPLEMENTATION_PLAN.md` | 0-9 | Phase 0 done |

`APP_SPECIFICATION.md` now lives at
`archive_of_structural_prompts/app_building_prompts/APP_SPECIFICATION.md`
(relocated after the application phases completed; content byte-identical to
the version that was at the repository root throughout Phases 0-9). It
remains authoritative for non-recommender product behavior. Every `spec §N`
reference in §1-§3 and §5-§6 below means that document; recommender sections
name their specification explicitly.

---

## 1. Current repository assessment (as of Phase 0 inspection)

Before this pass the repository contained only planning artifacts and a raw
dataset — no application code, no dependency manifests, no version control.

**Present before Phase 0/1:**

- `APP_SPECIFICATION.md`, `CLAUDE.md`, `BUILD_PROMPT.md`, `README.md` — planning docs.
- A pre-built dataset at the repo root: `books.parquet`, `interactions.parquet`,
  `books_editions.parquet`, `interactions_editions.parquet`, `covers_manifest.parquet`,
  `covers/` (102,435 images), plus the raw sources used to build them
  (`goodreads_*.json` ~8.9 GB total, `archive/` = Book-Crossing CSVs), two
  Jupyter notebooks, and a `.feature_cache.pkl` build cache.
- No `.git` repository, no `.gitignore`, no `pyproject.toml`, no `package.json`,
  no `apps/`, `packages/`, `docs/adr/`, `docker-compose.yml`, `Makefile`, or
  `.env.example`.

**Dataset validated against spec §7 during inspection:**

| File | Spec claim | Observed | Match |
|---|---|---|---|
| `books.parquet` | 92,526 rows, 39 columns, unique `work_id` | 92,526 rows, 39 columns | Yes, with one caveat below |
| `interactions.parquet` | 775,090 rows, 83,200 users, 92,526 works, no dup pairs, no timestamps | 775,090 rows, 83,200 users, 92,526 works, 0 duplicate `(user_id, work_id)`, columns exactly `user_id int32, work_id str, rating int8, is_explicit bool` | Yes |
| `covers/` | files named `<isbn>.jpg` | 102,435 files matching that pattern | Yes |

**Data-quality finding:** one row in `books.parquet` has `work_id == ""` (empty
string, not null) — 92,526 total rows but only 92,525 non-empty unique
`work_id`s (all non-empty values are unique, zero duplicates otherwise). The
Phase 2 import adapter must treat this as a validation failure for that single
row (report and skip), not upsert a book keyed by an empty string.

**Files beyond the spec's documented dataset contract:** `books_editions.parquet`
(126,217 rows, ISBN/edition-level), `interactions_editions.parquet` (782,927
rows, keyed by `isbn` not `work_id`), and `covers_manifest.parquet` (55,394
rows) are intermediate artifacts already rolled up into the work-level files
via `n_editions`, `edition_isbns`, `bx_ratings`, `bx_explicit`, `cover_file`,
`cover_source`. Per spec §2/§5.1 ("no separate book-edition entities", "one
catalog row equals one recommendable book") these three files are **not**
import inputs — see `data/README.md` and ADR-0010.

**Environment:**

- The user's `$HOME` (`/Users/jakubhajko`) is itself an unrelated, empty,
  zero-commit git repository — a pre-existing environment quirk, not
  introduced by this project. Sibling projects (`BubbLive`, `rack`, etc.) each
  have their own nested `.git` inside their project directory, which git
  treats as an independent repo boundary. This project now follows the same
  pattern: `git init` was run inside `/Users/jakubhajko/Projects/bookshelf`
  only; the outer repo was not touched. See ADR-0010.
- Tooling confirmed available: Python 3.13.3, `uv` 0.10.4, Node v26.4.0, npm
  11.17.0, PostgreSQL 17.10 client+server binaries (Homebrew, not running as a
  brew service), `pg_trgm` extension present.
- **Docker is not installed** (`docker` binary absent). `docker-compose.yml`
  and both Dockerfiles are authored to spec but could not be executed or
  validated with `docker compose config`/`docker compose up` in this
  environment — see Risks.
- `pgvector` extension is not installed. Spec marks it optional ("optionally
  enable vector for later use"); not required for Phases 0–4.

## 2. Gaps relative to the specification

Everything in spec §4 (repository structure), §8 (schema), §9 (API), §10
(recommender), and §12 (frontend) is unimplemented — this was a docs-and-data-only
repository. Rather than enumerate every missing file, the phased plan below
*is* the gap list: each phase names exactly what closes which gap. This pass
closes Phase 0 (this document + ADRs) and Phase 1 (foundations) only, per
`BUILD_PROMPT.md`.

## 3. Application phased implementation plan

Phases mirror spec §18 exactly. Status is updated as work lands. This
sequence is **complete**; the active sequence is §3R.

### Phase 0 — Inspect and plan — **done, this pass**

- Repository inspected; dataset validated against §7.
- `data/` reorganized into `raw/` / `processed/` / `notebooks/` / `sample/`
  with provenance documented (`data/README.md`).
- This plan created.
- ADRs 0001–0010 created (`docs/adr/`).

### Phase 1 — Foundations — **done, this pass**

- Monorepo directory skeleton per spec §4.
- `uv` workspace: root `pyproject.toml` with `apps/api` and
  `packages/recommender` as members.
- `apps/api`: FastAPI app factory, typed `Settings` (pydantic-settings)
  covering every category spec §11 requires (database, JWT/session, cookie,
  CORS, CSRF, cover storage, artifact storage, provider selection, logs,
  demo toggle), production-safe-defaults validator, structured JSON stdout
  logging, request-ID + access-log middleware, CORS middleware, a shared
  error envelope (spec §9.8) and exception handlers, and
  `GET /api/v1/health/live` / `GET /api/v1/health/ready` (the latter pings
  PostgreSQL through a request-scoped connection, no ORM models needed yet).
- `packages/recommender`: bare installable package, zero FastAPI/ORM
  dependencies (enforced by omission + a repo-hygiene test suite: dependency
  manifest check, source-import grep, importability). Contracts/providers/
  artifacts are explicitly **Phase 5** — not created yet.
- `apps/web`: Vite + React + TypeScript, Tailwind CSS wired (directives +
  config, not the dark design system — that's Phase 6), React Router +
  TanStack Query providers wired, a single smoke route that calls
  `/api/v1/health/live` to prove the vertical slice works end to end (happy
  path + error state, 2 tests), Vitest + React Testing Library, `oxlint`
  (the current Vite react-ts template's default linter) + `tsc -b --force`
  for typecheck.
- `docker-compose.yml` + `apps/api/Dockerfile` + `apps/web/Dockerfile` +
  `infra/docker/` per spec §16 (db/api/web services, DB volume, covers
  mounted read-only, artifacts mounted read-only). **Not runtime-validated —
  Docker is not installed in this environment; see Risks.**
- `.github/workflows/ci.yml`: backend job (Postgres service container, `uv
  sync`, ruff format/check, mypy, pytest, then a real boot + curl of both
  health endpoints), frontend job (npm ci, lint, typecheck, test, build).
- `Makefile` with every target CLAUDE.md lists. Targets whose phase hasn't
  landed yet (`migrate`, `import-data`, `import-data-dry-run`, `seed-demo`,
  `build-popularity`, `e2e`, `generate-api-client`) print which phase adds
  them and exit 0, rather than fail — see the note in §6 Risks/Assumptions.
- `.env.example` mirroring the full `Settings` surface, with obviously-fake
  local dev values.
- A project-local PostgreSQL 17 cluster (`.pgdata/`, port 5434, gitignored)
  for local dev/health-check validation, matching the pattern already used in
  this user's other local-Postgres projects — no Docker required to develop.

### Phase 2 — Database/catalog — **done, this pass**

- **Models** (`apps/api/src/book_app/modules/books/models.py`): `Book` (spec
  §8.3, `has_cover`/`has_description` as derived Python properties, never
  stored columns) + catalog relationships (§8.4): `Author`/`BookAuthor`,
  `Genre`/`BookGenre`, `CatalogShelfTag`/`BookCatalogShelfTag`,
  `BookSourceSimilarity`. Only catalog tables — users/shelves/etc. come with
  their own phases per the migration order in §8.11. `catalog_status` is a
  native Postgres enum, not a plain text column.
- **Migrations** (`apps/api/migrations/`, three, autogenerated then reviewed
  by hand): extensions/enums (`pg_trgm`, `catalog_status` type) → catalog
  core + relationships (8 tables) → search indexes (trigram on `title` and
  `primary_author_name`, full-text on `description` — hand-written, not
  autogenerated, since they're expression/opclass indexes). Verified against
  a genuinely empty local PostgreSQL: `upgrade head` → `downgrade base`
  (leaves zero tables/types besides `alembic_version`) → `upgrade head` again
  — both manually and as an automated test
  (`tests/integration/test_migrations.py`).
- **Dataset adapter** (`apps/api/src/book_app/modules/books/import_adapter.py`):
  the only code that knows raw `books.parquet` column names (ADR-0005).
  Handles the parallel-array columns (`authors`/`author_ids`/`author_roles`,
  `genres`/`genre_counts`, `shelves`/`shelf_counts`), passes through the
  source's own `primary_author` pick rather than re-deriving it, and
  computes `metadata_quality` as a documented 5-signal completeness
  fraction (not a source column — spec doesn't define one). Validates two
  things per row: non-empty `work_id`, non-empty `title` — both found as
  real, not hypothetical, issues in the full dataset (see below).
- **Repository** (`repository.py`): batched native Postgres upserts
  (`INSERT ... ON CONFLICT DO UPDATE ... RETURNING`) keyed by `work_id`
  (books) / `source_author_id` (authors) / `normalized_name` (genres, shelf
  tags). Two-pass import, driven by the CLI: books + authors/genres/tags
  sync per batch while streaming; `book_source_similarities` resolved in a
  second pass afterward, once the complete `work_id`/`source_book_id` → 
  internal-id map exists, because it's self-referential (`similar_book_id`
  points at another row in the same table still being populated).
  `similar_books` source values are resolved against **both** the `work_id`
  and `book_id` (source edition id) spaces — real data showed references
  split across both conventions, and ~66% resolve to neither (they point
  outside our 92,526-row catalog) — those are dropped and counted, not
  treated as errors.
- **CLI** (`apps/api/src/book_app/cli/import_catalog.py`,
  `uv run python -m book_app.cli.import_catalog`, wired to
  `make import-data` / `make import-data-dry-run` / `make migrate`):
  explicit (never runs at API startup), idempotent, batched (`itertools.batched`,
  default 500), dry-run capable (rolls back every batch; the similarity pass
  computes stats but skips the DB write in dry-run, since the books it would
  reference were themselves rolled back), report-generating (human-readable
  summary always; `--report path.json` for the full structured report).
- **Local cover storage** (`apps/api/src/book_app/shared/storage/`): a
  generic `ObjectStorage` protocol + `LocalFileStorage` implementation,
  reusable later for model artifacts (Phase 5) — safe against path
  traversal (`UnsafeObjectKeyError`), unit-tested against synthetic paths
  and integration-tested against the real sample fixture's cover files. No
  S3 implementation yet — Phase 2's own spec §18 scope says "local cover
  storage" specifically; see plan §6.
- **Sample fixture** (`scripts/data_import/build_sample_fixture.py` →
  `data/sample/books.parquet` + `data/sample/covers/`, 301 rows / 151
  covers, deterministic seed): sampled from the real dataset, deliberately
  keeping the one known-invalid row so the rejection path is tested against
  real data, not a hand-crafted stand-in.
- **Integration tests** (`tests/integration/`, real PostgreSQL, a dedicated
  `book_app_test` database recreated from nothing every session — this
  *is* the "empty-db migrations" proof, not a separate setup step): 12
  tests across migrations, import (upsert correctness, rejection, dry-run
  no-op, idempotency), and local cover resolution. New `make
  test-integration` target.
- **Full dataset actually imported** into the local dev database as a real
  end-to-end run, not just the sample: 92,524 books, 51,642 authors,
  131,848 book-author links, 10 genres, 246,378 book-genre links, 173,787
  shelf tags, 1,699,225 book-shelf-tag links, 269,276 similarity edges, in
  ~103s. A fuzzy trigram query for "Hary Potter" correctly surfaces the
  Harry Potter collection, confirming the search indexes work, not just
  exist.
- `interactions.parquet` is **not** imported into PostgreSQL at all — there
  is no interactions/ratings table in spec §8's schema for historical data;
  it stays a flat file for Phase 5's training/popularity CLIs to read
  directly, consistent with spec §6.7 ("historical users are not
  application users").

### Phase 3 — Authentication — **done, this pass**

- **`modules/users`**: `User` model (spec §8.1, native `account_status`
  enum); `username_rules.py` — pure validation (length, Unicode
  letter/digit/underscore/hyphen only, no leading/trailing whitespace, no
  control/format characters, reserved-name list, case/Unicode-fold
  uniqueness via the same `normalize_for_uniqueness` Phase 2 already uses)
  independent of any database session; `repository.py`; `UserPublic`
  schema (id + username only — never the password hash).
- **`modules/auth`**: `AuthSession` model (spec §8.2); `service.py` owns
  every use case and its own transaction (register, login, refresh,
  logout, change-password); `dependencies.py` — `get_access_token_claims`
  → `get_current_session` → `get_current_user`/`require_csrf`, sharing one
  FastAPI-cached dependency chain; `cookies.py` — HttpOnly access/refresh,
  readable CSRF cookie (spec §6.4-§6.5), refresh cookie scoped to
  `/api/v1/auth` only; `api.py` — all six endpoints (spec §9.1).
- **`core/security.py`**: Argon2id (explicit `Type.ID`, spec §6.3) for
  passwords; SHA-256 for refresh/CSRF token storage/lookup — a fast
  deterministic hash is correct there (high-entropy random tokens, not
  human-guessable secrets), Argon2id is reserved for passwords only; a
  focused JWT (`sub`, `sid`, `iat`, `exp` — nothing else) via `pyjwt`,
  confirming the Phase 1 plan (§6 risk 4).
- **`shared/rate_limit.py`**: pluggable `RateLimiter` protocol + an
  in-process fixed-window default, applied to login (keyed by IP +
  normalized username) and register (keyed by IP) — spec §14's "pluggable
  auth rate-limit boundary," with AWS WAF/shared-store limiting documented
  as the production swap-in, not built.
- **CSRF**: session-bound, random-token-hashed-at-rest (matches spec
  §8.2's `csrf_token_hash` column existing at all — an HMAC-derived design
  wouldn't need to store anything). Rotated on every `/auth/refresh` call
  (spec §6.5: "rotate when appropriate"). Applied to logout and
  change-password; not to register/login (no session yet to bind to) or
  refresh (an attacker triggering a refresh cross-site gains nothing — they
  can't read the HttpOnly response cookies it sets).
- **`cli/cleanup_sessions.py`** (`make cleanup-sessions`): deletes
  expired-or-revoked `auth_sessions` rows; dry-run capable.
- **Migration** (`4a6ac23b959d`): `account_status` enum + `users` +
  `auth_sessions`, indexed per spec §8.2 ("user/revoked/expiry and
  expiry"). Verified with the same empty-db round trip as Phase 2 — and
  confirmed the hand-written catalog search indexes from migration
  `43bc30e307a2` survive it (autogenerate initially proposed dropping them,
  since they aren't represented in any model; stripped from this migration
  before applying — see the file's own docstring).
- **Tests**: 36 new unit tests (username rules, password/token/JWT
  primitives, rate limiter — all with no database) + 16 new integration
  tests (full HTTP lifecycle, CSRF accepted/rejected, duplicate/reserved
  usernames, disabled accounts, session-cleanup repository logic, and two
  checks the schema doesn't just describe: refresh/CSRF/password values
  are genuinely unrecoverable from what's stored). 69 unit + 28 integration
  total across the whole backend now.
- **Not built**: security headers, general (non-auth) request rate
  limiting, and CSRF-cascaded revocation of a user's *other* sessions on
  password change — all explicitly Phase 9 scope or a documented,
  deliberately out-of-scope enhancement (see §6).

### Phase 4 — Books/state/shelves — **done, this pass**

- **`shared/pagination/`**: opaque keyset cursor codec (`encode_cursor`/
  `decode_cursor` — base64 of a sorted-key JSON object) plus a generic
  `Page[T]` response envelope, written with PEP 695 syntax
  (`class Page[T](BaseModel)`) and confirmed to work correctly with both
  Pydantic v2 validation and FastAPI's `response_model` (distinct OpenAPI
  schemas per `T`). Distinct from Phase 5's persisted-batch recommendation
  cursors (spec §9.9) — these encode a plain last-seen-value + tiebreaker,
  with no persisted batch behind them.
- **`modules/interactions`**: `UserBookState` (composite PK, spec §8.5,
  `CheckConstraint`s for the rating range and the Neutral/Rated/Not-Interested
  mutual exclusion — spec §5.2) and `InteractionEvent` (append-only, spec
  §8.9, six indexes, deliberately no FK on `shelf_id`/`session_id`/
  `recommendation_request_id`/`search_query_id` so a later delete can't
  erase what a historical event says happened). `rating_scale.py` converts
  the public half-star float (0.5–5.0) to the internal integer (1–10) and
  back, rejecting anything off the ten allowed steps. `service.py`
  implements every spec §5.3 transition (set/change/remove rating, set/remove
  Not Interested) — each idempotent, each preserving shelf memberships, each
  appending exactly the event spec §5.3 names. `GET /me/ratings` (spec §9.4)
  supports all five sorts (recent/highest/lowest/title/author), rating-range
  and genre filters, and cursor pagination.
- **`modules/shelves`**: `Shelf` (unique per user after
  `normalize_for_uniqueness`, spec §5.4) and `ShelfBook` (composite PK,
  `CASCADE` on shelf delete only — spec §5.4: deleting a shelf must not
  touch ratings, other shelves, or events). `service.py` covers CRUD, PATCH
  semantics driven by key-presence (`model_dump(exclude_unset=True)`, not
  None-checks — absent vs. explicit-`null` mean different things for
  `description`), single add/remove (idempotent), and `sync_book_shelves` —
  validates every requested `shelf_id` is owned *before* changing anything,
  diffs current vs. requested, and commits once. Shelf list/detail responses
  include up to 4 most-recently-added cover keys per shelf (spec §9.3:
  "enough cover data for a collage without N+1 frontend requests").
- **`modules/books`** extended: `service.get_book_detail` assembles the
  catalog row plus authors/genres (Phase 2 repository reads) plus this
  user's rating/Not-Interested/shelf-ids into one `BookDetail` (spec §12.7's
  fields, minus the similar-books grid — that's Phase 5's
  `GET /recommendations/books/{id}/similar`). `api.py` implements all six
  spec §9.2 routes, delegating every write to `interactions.service`/
  `shelves.service` rather than re-implementing those transitions.
- **Authorization**: every new route requires `Depends(get_current_user)` —
  spec §2 rules out anonymous persistent accounts, so unlike catalog
  browsing there's no unauthenticated read path here; every mutating route
  also requires `Depends(require_csrf)`. Ownership failures on shelves
  return `SHELF_NOT_FOUND` (404), identical to nonexistence, never 403 (spec
  §6.6) — verified by an integration test that a foreign shelf's PATCH/DELETE/
  GET are indistinguishable from a random UUID's.
- **Migration** (`fc95559d9639`): `interaction_events`, `shelves`,
  `user_book_states`, `shelf_books`. Verified with the same empty-db
  `upgrade head` → `downgrade base` → `upgrade head` round trip as prior
  phases (confirmed via `alembic check` too — the only reported diff is the
  same pre-existing hand-written-trigram-index false positive noted in
  migration `4a6ac23b959d`, nothing from this migration). The round trip
  necessarily wiped the dev database's catalog rows; re-ran
  `make import-data` afterward and got back the identical 92,524 books.
- **Tests**: 33 new unit tests (rating-scale conversion incl. float-noise
  tolerance, shelf-name validation, cursor codec incl. non-dict-JSON
  rejection) + 45 new integration tests (every §5.3 transition and its
  event, mutual-exclusion, shelf CRUD/ownership/collage-cap, multi-shelf
  sync atomicity under a foreign `shelf_id`, all five `/me/ratings` sorts
  including a dedicated pagination round trip for the `recent` sort's
  datetime cursor — see risk #27 below — genre/rating-range filters, CSRF
  and auth-required checks throughout). 175 tests total now (102 unit + 73
  integration), 94% combined coverage; every new module lands at 96–100%.
- **Live smoke-tested** against the real dev database (92,524 real books):
  full detail → rate → not-interested → shelf-create → shelf-add → shelf-sync
  → `/me/ratings` flow with real cover keys and author/genre data, plus the
  401/403/404 authorization paths, with a clean server log throughout.
- **Not built**: search (`GET /search/books`) and recommendations — both
  explicitly later phases; the frontend never renders any of this yet
  (Phase 6+).

### Phase 5 — Recommendation boundary — **done, this pass**

- **`packages/recommender` (`book_recommender`)** gets its real shape.
  `contracts/` — `UserContext`/`HomeContext`/`ShelfContext`/
  `SimilarBooksContext`/`SearchContext` (discriminated union, spec §10.4),
  `RecommendationEngineRequest`/`Result` (sync layer) and
  `RecommendationRequest`/`Batch` (async layer, spec §10.6-§10.7) kept as
  distinct named types per the spec's own naming even though identical in
  content today — the seam a remote provider needs later. `engines/` (not
  one of the spec's literal four directories — added as a natural sibling
  to `providers/`, documented as a deliberate, additive deviation) —
  `MockRecommendationEngine` (seeded-but-varied via `hashlib.sha256`, never
  Python's randomized `hash()`; supports configurable failure/latency, spec
  §10.11), `PopularityRecommendationEngine` (serves a precomputed ranking,
  never re-sorts it), `FuturePipelineRecommendationEngine` (placeholder,
  raises clearly — spec §2 forbids building the real funnel).
  `providers/` — `InProcessProvider` (runs the sync engine via
  `asyncio.to_thread`, spec §10.3), `FallbackProvider` (spec §10.10's
  chain: primary → popularity fallback → `ProviderError`; skips the
  redundant wrap when primary already *is* popularity), `RemoteProvider`
  (skeleton, spec §10.3). `artifacts/` — `ArtifactManifest` (spec §10.13,
  §7.5's book_id/work_id/model_item_index triple) + `LocalArtifactStorage`
  (stdlib-only; deliberately does not import `book_app.shared.storage` —
  that would invert the intended dependency direction). Zero FastAPI/ORM
  imports, verified by the existing hygiene test.
- **`modules/recommendations`**: `eligibility.py` — pure functions over an
  already-built `UserContext` implementing spec §5.5 exactly (home excludes
  rated/Not-Interested/shelved-anywhere; shelf excludes rated/Not-Interested/
  this-shelf-only; similar excludes rated/Not-Interested/the source book).
  `context_builder.py` assembles `UserContext` from `interactions`/`shelves`
  repository reads. `service.py` implements spec §11's ten-step workflow
  end to end for all three surfaces plus cursor-page continuation: build
  context → end the read transaction *before* calling the provider → call
  it → defensively validate every candidate against currently-active books
  (`books_repository.get_catalog_cards`) → persist the request+full batch →
  serve the first page → persist its impressions → encode
  `{request_id, position}` as the next cursor (reusing `shared.pagination`'s
  codec, spec §9.9/ADR-0007). A malformed cursor, one pointing at another
  user's batch, and one pointing at an expired batch all raise the same
  `RECOMMENDATION_CURSOR_INVALID` (spec §6.6's existence-hiding principle).
  A fully-exhausted provider (`ProviderError`) maps to `RECOMMENDATION_UNAVAILABLE`
  (503, spec §10.10). `wiring.py` selects the provider from
  `settings.recommendation_provider` — **lazily, on first request**, not
  eagerly in `create_app()` (`main.py`'s own docstring: tests must be able
  to construct the app without a live database; the mock engine's
  candidate pool needs one, spec §10.11 — see risk #34).
- **`cli/build_popularity.py`** (`make build-popularity`): computes a
  Bayesian-shrunk popularity score per active book — support (`ratings_count`
  `+ bx_ratings + bx_explicit`, `bx_explicit` deliberately counted again as
  an extra weight for explicit engagement, verified never to exceed
  `bx_ratings` in the real data first) pulls the score toward the
  catalog-wide mean when low, so two five-star ratings can't outrank
  thousands averaging 4.5 (spec §10.12's "support adjustment"). Writes
  `manifest.json` + `scores.json` via the shared `LocalArtifactStorage`,
  retires any previously-ACTIVE `model_versions` row for `popularity`, and
  activates the new one. Verified against the real dev database: 92,524
  books ranked in under a second, sensible top results (classics with
  large, consistently-high rating support).
- **Migration** (`b61e97f578c1`): `model_versions` (new native enum
  `model_version_status`: `READY`/`ACTIVE`/`RETIRED` — no explicit value
  list in the spec unlike catalog/account status, a conservative minimal
  set since nothing yet builds an activation UI beyond the CLI writing
  ACTIVE directly), `recommendation_requests` (CASCADE on `shelf_id`/
  `source_book_id` rather than `interaction_events`' SET-NULL-and-preserve
  pattern — deliberately different governance: these rows are an ephemeral,
  `expires_at`-bounded cache per ADR-0007, not permanent history),
  `recommendation_results`, `recommendation_impressions`. Verified with the
  same empty-db round trip as prior phases; `alembic check` reports only
  the same pre-existing hand-written-index false positive.
- **API**: `GET /recommendations/home`, `.../shelves/{shelf_id}`,
  `.../books/{book_id}/similar` (spec §9.5) — GET-only, no CSRF dependency.
  All three accept `limit`, `cursor`, and an optional `exclude` (comma
  -separated book ids) mapped to `session_exclusions` — spec §5.5's "already
  returned in the current feed session" is otherwise automatically satisfied
  by the persisted-batch design itself (unique book_ids per batch, fixed
  positions), so `exclude` only matters *across* separate top-level requests
  within a session; a genuinely underspecified detail, resolved this way
  and documented rather than guessed at silently (risk #33).
- **Tests**: recommender package now has 38 tests (was 3 hygiene-only) —
  shared engine-contract tests parametrized across mock/popularity (spec
  §13.2: unique ids, exclusions, count, determinism, valid metadata/reasons,
  empty pool/user, typed errors), engine-specific behavior, provider
  fallback-chain behavior, artifact manifest round trip. apps/api gained 7
  unit tests (eligibility pure functions, artifact-path anchoring — the
  latter caught by writing a test that checks the hardcoded `parents[N]`
  index actually resolves to the repo root, exactly the kind of off-by-one
  a future file move could silently break) and 27 integration tests (all
  three surfaces incl. cursor pagination, eligibility exclusion end to end,
  cross-user cursor rejection, the 503 fallback-exhausted path via a
  dependency-override test double, `build-popularity`'s CLI logic incl. the
  support-adjustment formula against deliberately crafted rating
  distributions, provider-selection wiring). 247 tests total across the
  whole backend (109 apps/api unit + 100 integration + 38 recommender), 95%
  combined coverage on `book_app`.
- **Live smoke-tested** against the real dev database (92,524 real books,
  a real `make build-popularity` artifact) under *both* `mock` and
  `popularity` provider configurations: full home → cursor-continuation →
  rate-then-re-fetch-excluded → similar → shelf flow, 401/404 authorization
  paths, clean server logs throughout.
- **Not built**: search (`GET /search/books`) — not in Phase 5's own spec
  §18 bullet list (contracts/mock/popularity/fallback/persistence/cursors/
  endpoints/tests only); the real recommendation funnel (explicitly out of
  scope, spec §2/§20); an S3 artifact backend (deferred, matching the exact
  precedent already set for cover storage in Phase 2); any admin UI/CLI to
  activate a *non-latest* model version; the frontend never renders any of
  this yet (Phase 6+).

### Phase 6 — Frontend shell/auth — **done, this pass**

- **Generated API client pipeline**: new backend CLI `book_app.cli.export_openapi`
  (`apps/api/src/book_app/cli/export_openapi.py`) exports `app.openapi()` to
  `apps/web/openapi.json` without needing a live database (verified:
  `create_app()` + `.openapi()` alone never touches Postgres) — 2 new unit
  tests. `openapi-typescript` turns that into
  `apps/web/src/api/generated/schema.d.ts` (gitignored, regenerated on
  demand). `make generate-api-client` now runs both steps in sequence.
  `openapi-fetch` provides the typed runtime client on top of the generated
  types — verified 20 real routes exported end to end against the live
  backend schema.
- **Design tokens** (`apps/web/src/index.css`): full Tailwind v4 `@theme`
  block (background/surface/surface-hover/border/text/text-muted/accent/
  accent-hover/accent-text/sidebar/topbar colors, radii) — CSS-first config
  per ADR-0008, not a JS `tailwind.config`. `prefers-reduced-motion` handled
  at the base layer (spec §12.12).
- **API client wrapper** (`apps/web/src/api/client.ts`): `apiClient`
  (openapi-fetch instance) with two middlewares — CSRF header injection from
  the readable `csrf_token` cookie, and transparent single-flight
  session-refresh-and-retry on a 401 (request cloning via openapi-fetch's
  per-request `id`, since a `Request` body can only be read once). `unwrap()`
  turns the `{data,error}` discriminated union into throw-on-error;
  `ApiError` carries status/message/code. `api/auth.ts` — typed
  `register`/`login`/`fetchCurrentUser` (401 → `null`, not a thrown
  error)/`logout`/`changePassword`. `api/queryKeys.ts` centralizes TanStack
  Query keys per spec §12.11.
- **Auth subsystem** (`apps/web/src/auth/`): `AuthContext`/`useAuth` split
  from `AuthProvider` (Fast Refresh compliance, oxlint's
  `react/only-export-components`); `AuthProvider` bootstraps via one
  `useQuery` (`staleTime: Infinity`, `retry: false`) and updates the cache
  directly on login/logout rather than refetching; `RequireAuth`/`GuestOnly`
  layout-route guards (`<Outlet/>`/`<Navigate/>`, remembering `location` as
  `state.from` so a successful login returns the visitor where they were
  headed).
- **Shell** (`apps/web/src/shell/`): `LeftRail` (desktop) / `BottomNav`
  (mobile) share one `navItems` source of truth (Home/Shelves/Rated,
  `lucide-react` icons); `TopBar` (search form + `AvatarMenu`); `AvatarMenu`
  built on Radix `DropdownMenu` (ADR-0008: accessible headless primitives
  over hand-rolled widgets) — username, Account, Change password, Logout.
- **Pages**: `Register`/`Login` (controlled forms via a shared `TextField`,
  server error shown via `role="alert"`); `Account` (real page — username +
  change-password form, not a placeholder, since `AvatarMenu` needed
  somewhere to navigate and `changePassword` already existed from Phase 3);
  `Search`/`BookDetail`/`Shelves`/`ShelfBooks`/`ShelfDiscover`/`Rated`/
  `NotFound` — placeholders (`ComingSoon`) reading their real route
  params/search params, real content lands in Phase 7/8. `App.tsx` wires
  every spec §12.3 route through `GuestOnly`/`RequireAuth`/`AppShell` as
  appropriate.
- **Tests**: 15 tests across 7 files (was 2, Phase 1's health-check smoke
  test) — `AuthProvider` (bootstrap-authenticated, bootstrap-anonymous,
  clears-on-logout), `Register`/`Login` (success navigation + server-error
  display), `RequireAuth`/`GuestOnly` (redirect behavior both directions,
  including that `RequireAuth` preserves the origin path in redirect
  state), `AvatarMenu` (username render, menu opens, logout calls the API
  and navigates — spec §13.4's explicit "logout" coverage requirement).
- **Live smoke-tested** at the HTTP level against the real backend (no
  interactive browser tool available in this environment — see risk #44):
  booted both dev servers (`make dev-api` against the project-local
  Postgres cluster on :5434, `npm run dev`), then drove the exact register
  → login → `/me` → logout → `/me` cycle with `curl` and a cookie jar,
  confirming cookie flags (`access_token`/`refresh_token` HttpOnly,
  `csrf_token` readable), CSRF enforcement (logout without `X-CSRF-Token` →
  403, with it → 204), and post-logout 401 — the same contract `client.ts`'s
  middleware is written against. CORS confirmed exact-origin
  (`http://localhost:5173`, credentialed). Server logs stayed clean
  (structured JSON, no stack traces) throughout.
- **Not built**: the real content behind
  Search/BookDetail/Shelves/ShelfBooks/ShelfDiscover/Rated (Phase 7/8); any
  interactive-browser/DOM verification (no such tool in this environment —
  mitigated by the HTTP-level smoke test above plus a clean production
  build).

### Phase 7 — Core frontend — **done, this pass**

- **Cover image serving** (`apps/api/src/book_app/core/covers.py`, new):
  `GET /api/v1/covers/{object_key}` — the first thing in this codebase to
  actually render an image, and spec §20 forbids constructing cover paths
  in the frontend, so something on the backend had to turn the opaque
  `cover_object_key` every book/shelf/recommendation response already
  carries into a fetchable URL. Deliberately the one **unauthenticated**
  route in the app (cover art is public; a browser `<img>` tag never gets
  `client.ts`'s session-refresh-and-retry treatment, so gating it behind
  the ~15-minute access token would turn covers into broken images
  mid-session). Reuses Phase 2's `LocalFileStorage`/`UnsafeObjectKeyError`
  for safe path resolution — new here is `app.state.cover_storage` actually
  being constructed and wired into a request path for the first time. See
  ADR-0011.
- **A real, live-smoke-test-only bug, found and fixed**:
  `cover_storage_local_path`'s documented default is a bare relative path
  (`data/processed/covers`), which resolves against the process's *current
  working directory* — `apps/api/` for `make dev-api` (its own
  `cd apps/api &&`), not the repo root where `data/` actually lives. Every
  cover 404'd the moment this was tested against a real dev server started
  the documented way, even though the exact same fixture-based unit tests
  (§ below) passed cleanly first, since `tmp_path` fixtures are always
  absolute and never exercise that branch. Fixed with
  `resolve_cover_storage_root()`, anchoring relative paths at the repo root
  via `Path(__file__).resolve().parents[5]` — the identical pattern
  Phase 5's `modules/recommendations/artifact_paths.py` already established
  for the same class of problem (and Phase 2/6's `import_catalog.py`/
  `export_openapi.py` each have their own copy too) — kept as a fourth,
  separate local copy rather than refactored into one shared utility (spec
  §20: "do not add unused abstractions"; CLAUDE.md: "three similar lines is
  better than a premature abstraction" — this is the established,
  repeated convention in this codebase, not something to consolidate
  mid-bugfix). See risk #47.
- **Frontend API layer**: `api/covers.ts` (`coverUrl()` — the one
  URL-building helper in the app, appending an opaque backend-issued key to
  a fixed backend-owned route, which is what spec §20 actually rules out
  avoiding, not this), `api/books.ts`, `api/shelves.ts`,
  `api/recommendations.ts`, and `queryKeys.ts` extended with
  `shelves`/`books.detail`/`books.state`/`recommendations.home`/
  `recommendations.similar`.
- **Shared per-book state cache** (`hooks/useBookState.ts`): one TanStack
  Query cache entry per book (`queryKeys.books.state`), shared by every
  card and the detail page showing that book — necessary because no single
  endpoint returns full state (`PreferenceState` has rating/not-interested
  but not `shelf_ids`; `ShelfIdsResponse` is the reverse), and because
  Home-feed cards never fetch it directly at all: spec §5.5 eligibility
  guarantees every book `GET /recommendations/home` returns starts Neutral
  and unsaved, so a `NEUTRAL_STATE` default is correct, not a
  loading placeholder. `useBookDetailQuery` seeds this cache from
  `GET /books/{id}`'s authoritative `user_state`; five mutation hooks
  (`useSetRatingMutation`, `useRemoveRatingMutation`,
  `useSetNotInterestedMutation`, `useRemoveNotInterestedMutation`,
  `useSyncShelvesMutation`) each optimistically patch it via `onMutate`,
  roll back via `onError`, and reconcile with the real server response via
  `onSuccess` — spec §12.11's "optimistic updates ... with rollback and
  authoritative invalidation," applied uniformly everywhere a card or the
  detail page can act on a book.
- **Masonry grid** (`components/BookMasonryGrid.tsx`,
  `hooks/useGridTier.ts`): items distributed round-robin by index into
  N column arrays (N from a `resize`-driven breakpoint hook — jsdom
  implements neither `matchMedia` nor `IntersectionObserver`, verified
  directly, so `matchMedia` was avoided rather than requiring a test
  polyfill for a hook that a plain `resize` listener does just as well),
  each column an independent vertical flex stack. Deliberately **not** CSS
  multi-column layout, which rebalances the *entire* list into new columns
  as it grows and would violate spec §12.4's explicit "stable rendered
  order" the moment infinite scroll appends a page; round-robin's
  per-item column assignment never changes when items are appended at the
  end, and unlike a shortest-column-fill algorithm it needs no real image
  height measurement to decide placement. Breakpoint→column mapping, and
  the separate percentage gutter that sets cover size independently of it,
  are documented in risk #52.
- **Cards** (`components/BookCard.tsx`, `ShelfSelectorPopover.tsx`,
  `BookCover.tsx`): cover (real aspect ratio preserved, title/author
  placeholder tile on a missing or failed-to-load cover, spec §12.5) +
  title/author below it + a hover/focus overlay (visible by default below
  `md`, hover-gated above it — spec §12.6's "touch controls remain usable
  without hover") with a shelf-selector pill (left) and a Save/Saved button
  (right), the two as flex siblings in one row so the shelf name truncates
  instead of colliding with Save on a narrow column. The shelf selector is
  a Radix `Popover` around plain native checkboxes rather than a custom
  listbox/combobox — searchable, multi-select, create-a-shelf-inline, all
  satisfied with maximally accessible native controls instead of
  hand-rolled ARIA (ADR-0008). Its trigger names the shelf in play (the
  shelf the book is on, else the one a quick Save would use), so the pill
  is a truthful preview of the button beside it; with nothing to name it
  falls back to a bare add affordance rather than a dropdown arrow
  pointing at nothing. The visible shelf name is part of the trigger's
  accessible name (WCAG 2.5.3), not replaced by an `aria-label`.
  Clicking "Saved" opens the same selector (review/edit) rather than
  instantly unsaving; clicking "Save" saves straight to the session's
  last-used shelf (`hooks/useLastUsedShelf.ts`, `sessionStorage`-backed)
  or opens the selector if there isn't one yet — a Pinterest-informed
  reading of an underspecified interaction, documented at risk #49.
  `useLastUsedShelf` is a shared `useSyncExternalStore` over
  `sessionStorage`, not per-instance `useState` seeded at mount: with the
  latter, choosing a shelf on one card left every card already on screen
  holding the value it read when *it* mounted, so their quick-Save target
  (and the shelf their pill names) stayed stale until they remounted.
- **Detail** (`components/BookDetailContent.tsx`,
  `routes/BookDetail.tsx`, `routes/BookDetailModal.tsx`): every spec §12.7
  field (cover, title/authors, description, year/pages/publisher/
  language/format, genres, external rating, user rating, shelf controls,
  Not Interested, similar grid) — **except** a dedicated "series" display,
  which real data showed has no honest way to render (risk #48).
  `RatingStars.tsx` — five stars, ten accessible half-step values, built
  from native radio inputs sharing one `name` (roving-tabindex/arrow-key
  navigation is a browser feature at that point, not custom JS) plus a
  separate remove action. `NotInterestedControl.tsx` — confirms via a
  Radix `AlertDialog` only when clearing an existing rating (spec §12.7),
  proceeds immediately otherwise. **Route-backed modal**
  (`routing/modalNavigation.ts`, `App.tsx`'s `AppRoutes`): desktop modal
  over the prior page, mobile full-screen, direct navigation renders the
  plain full page — the standard React Router "two `<Routes>`, one keyed
  off a `state.backgroundLocation`" pattern, which also means the page
  underneath a modal never unmounts, so its scroll position survives for
  free without any extra code.
- **Home** (`routes/Home.tsx`): shelf-lens row (For You + each shelf,
  fetched from `GET /shelves` — clicking a shelf chip navigates to that
  shelf's own `/shelves/:id/discover` rather than rendering shelf-scoped
  recommendations inline, since that route's actual content is Phase 8
  scope, risk #50) — a dismissible guidance banner for a visitor with no
  shelves yet (spec §12.4's "subtle guidance message... no forced
  onboarding," risk #53) — `useInfiniteQuery` against
  `GET /recommendations/home` with an `IntersectionObserver` sentinel
  driving `fetchNextPage` — skeleton/retry/empty states — manual
  `sessionStorage`-keyed scroll restoration (`hooks/useScrollRestoration.ts`;
  React Router's built-in `<ScrollRestoration>` only exists for the
  data-router API, not the declarative `<BrowserRouter>` this app's modal
  pattern needs, risk #57).
- **Tests**: 22 new frontend tests across 5 new files (was 15/7 after
  Phase 6) — `RatingStars` (half-step values, checked state, remove
  action), `ShelfSelectorPopover` (search/filter, multi-select sync,
  create-new, no-duplicate-create), `NotInterestedControl` (confirms only
  when clearing a rating, cancel leaves state untouched), `BookCard`
  (optimistic Saved badge, rollback to Save on a failed request),
  `App.test.tsx` (direct navigation renders the plain page with no
  `role="dialog"`; in-app navigation renders the modal with the background
  page still mounted underneath) — 37 frontend tests total. Backend: 7 new
  tests for `core/covers.py` (found/missing/path-traversal/no-auth/
  relative-path-anchoring/absolute-passthrough/repo-root-sanity) — 218
  apps/api tests total (94% coverage), 38 recommender (unchanged).
  `test/setup.ts` gained two environment stubs after live-diagnosing real
  jsdom gaps: `IntersectionObserver` (unimplemented in jsdom entirely) and
  `localStorage`/`sessionStorage` (Node 26's own native, experimental
  implementation shadows jsdom's working one and throws without a
  `--localstorage-file` flag this repo has no reason to require) — risk
  #56.
- **Live smoke-tested** against the real dev database and the exact
  `make dev-api` launch convention (catching the cover-path bug above):
  home feed → rate a book → book detail reflects it → create a shelf →
  sync a different book onto it → similar books → cover bytes for a key
  taken from a real home-feed response, all against real data (92,524
  books), clean server logs throughout. No interactive browser tool is
  available in this environment (see risk #44 from Phase 6, still true) —
  both dev servers were left running for manual verification.
- **Not built**: Shelf/Rated/Search page content (Phase 8 — cards, the
  masonry grid, and the shared book-state cache built this phase are
  already reusable there); `exclude`-based cross-request duplicate
  suppression for Home (risk #55); infinite scroll on the detail page's
  similar-books section (single page, risk #54); an automated accessibility
  audit (Phase 9).

### Phase 8 — Shelves/Rated/Search — **done, this pass**

- **`modules/search` (new — backend, spec §9.6)**: `GET /search/books?q=...`.
  `repository.py`'s `_rank_tier` collapses spec §9.6's seven tiers into one
  SQL `CASE` (exact title → exact title/author combination → title prefix →
  trigram fuzzy title → trigram fuzzy author → full-text description →
  popularity tiebreak), evaluated in order so an exact-title match is never
  double-counted as merely fuzzy. Tiers 4-5 use pg_trgm's `%` operator
  (`Column.op('%')`, not a bare `similarity()` call — verified only the
  operator form is planner-recognized against the `gin_trgm_ops` indexes
  from migration `43bc30e307a2`); tier 6 matches the full-text GIN index's
  own `to_tsvector('english', ...)` expression exactly; tier 7 uses the
  dataset's own `ratings_count`, not `packages/recommender`'s Bayesian
  -shrunk popularity artifact (a different concept for a different
  purpose — see ADR-0012). Every query fragment was executed against the
  real 92,524-book dataset before being written into the module, not
  assumed — e.g. confirmed a "harry potter" query correctly ranks
  title-prefix matches ahead of a merely-fuzzy biography title. Pagination
  is a 3-key keyset cursor (`tier`, `popularity`, `book_id`), verified by
  executing an actual page-boundary query and confirming a clean resume.
  Unlike `RecommendationBookItem`, `SearchResultItem` carries a full
  `user_state` per result (spec §9.6: "search keeps prior user states
  visible") — batch-fetched via two new repository functions
  (`interactions_repository.get_states_for_books`,
  `shelves_repository.get_shelf_ids_for_books`), not one query per row.
  See ADR-0012 for the full design and alternatives considered.
- **Tests**: 2 unit (`cursor_value_for_row`) + 10 integration — each tier
  independently, popularity tiebreak within a tier, inactive books
  excluded, no-match returns empty, and the two tests that matter most:
  rated/Not-Interested/shelved books all stay visible with *accurate*
  per-result state (not just "not excluded"), and cursor pagination across
  a real multi-page scenario has no duplicates or gaps. 230 backend tests
  total (was 218 after Phase 7), 95% coverage (up from 94%).
- **Frontend — shared groundwork**: `BookCard`'s prop type generalized from
  the concrete `RecommendationBookItem` to a minimal structural
  `BookCardData` interface, so `SearchResultItem`/`RatedBookItem` pass
  directly into the same card/grid components Home already used — no
  adapter layer. Added always-visible (not hover-gated, unlike the
  shelf-selector/Save overlay) rating/Not-Interested badges to `BookCard`
  — dead code on Home (spec §5.5 guarantees Neutral there) but real on
  every surface this phase adds. Two new `useBookState` seeding hooks
  (`useSeedBookStatesFromSearchResults` — full authoritative replace;
  `useSeedRatingsIntoBookState` — partial merge, since `RatedBookItem` has
  no `shelf_ids`) populate the shared per-book cache from a page of
  results, using `useLayoutEffect` rather than `useEffect` so an
  already-rated result never flashes as unrated for one frame first.
  `hooks/useInfiniteScrollSentinel.ts` extracted once Home, Shelf-books,
  Shelf-discover, and Search all needed the identical
  `IntersectionObserver` wiring (Home refactored to use it too).
- **Shelves overview** (`routes/Shelves.tsx`): board-like cover collages
  (2x2 grid of each shelf's most-recent covers, spec §12.8) + inline
  create form. Rename/edit-description/delete deliberately live on the
  shelf *detail* page, not this grid (risk #58).
- **Shelf detail** (`routes/ShelfDetailLayout.tsx` + `ShelfBooks.tsx`):
  `/shelves/:shelfId/books` — the shelf itself. The layout route holds the
  header (name/description, book count, rename via an inline form, delete
  via a Radix `AlertDialog` confirming spec §5.4's "ratings/other shelves
  unaffected" guarantee); the child route is `GET /shelves/{id}/books`,
  infinite-scrolled.
- **Shelf lens** (`routes/ShelfLens.tsx` + `ShelfDiscover.tsx` +
  `components/ShelfLensRow.tsx`): `/shelves/:shelfId/discover` — the shelf
  as a lens on the feed. Keeps the lens row exactly where Home had it (that
  shelf marked `aria-current`), puts the shelf's own header under it (name,
  count, cover preview strip, and a "View shelf" button through to the page
  above), and runs `GET /recommendations/shelves/{id}` underneath. Cards
  here default their quick-Save to *this* shelf rather than the session's
  last-used one (spec §12.8: "defaults Save to current shelf"), via a
  `defaultShelfId` prop threaded through `BookMasonryGrid` → `BookCard`
  (risk #59).

  Phase 7-9 built these as one route with Books/Discover tabs. Phase 10
  split them: picking a shelf from the lens row is an act of *browsing*, so
  it should swap the feed in place rather than navigate into a section
  whose landing tab is the books the visitor already knows about. Tabs also
  made shelf-scoped discovery the less obvious half of a shelf, reachable
  only after two navigations. The pairing is now: lens row → lens view
  (discovery), "View shelf"/Shelves overview → the shelf page (contents).
- **Rated** (`routes/Rated.tsx`): all 5 sorts (backend complete since
  Phase 4) as toggle buttons, rating-range as two `<select>`s, genre as a
  plain text filter (no "list genres" endpoint exists to populate a
  dropdown from, risk #61) — every control re-fetches immediately on
  change, no separate "Apply" step.
- **Search** (`shell/SearchBar.tsx` + `routes/Search.tsx`): the search bar
  moved out of `TopBar.tsx` into its own component with a debounced (300ms)
  suggestions dropdown — built on Radix `Popover.Anchor` (not `Trigger`:
  the popover is driven by focus/typing on the input, not a click-toggle)
  with `onOpenAutoFocus` suppressed so opening it never steals focus from
  the input. Suggestions call the *same* `GET /search/books` with a small
  `limit` (spec §9.6 lists exactly one search route, no separate
  suggestions endpoint) and navigate straight to the book; recent searches
  (`localStorage`, 5 max, deduplicated) show when the input is empty and
  focused. Individual suggestion/recent-search rows are plain tabbable
  buttons inside a `Popover`, not a full ARIA 1.2 combobox with
  `aria-activedescendant`/arrow-key roving — keyboard-operable via Tab, a
  deliberate scope trim in the same spirit as Phase 7's shelf-selector
  (risk #62). The results page (`routes/Search.tsx`) reads `?q=` from the
  URL (spec §12.10: "query in URL"), infinite-scrolls, and seeds each
  result's state so badges are accurate immediately.
- **Tests**: 21 new frontend tests across 5 new files — shelf detail
  (header above its contents; the Books/Discover tab assertions here became
  `ShelfLens.test.tsx` in Phase 10), shelf rename/delete, shelf CRUD on the overview
  (create/empty/error), search suggestions (debounced fetch, click
  -through to a book, recent searches, submit-and-record), search results
  (empty/error/badge-accuracy), rated sort/filter re-fetching. 58 frontend
  tests total (was 37 after Phase 7).
- **Live smoke-tested** against the real dev database: search for "Dune"
  (exact match ranks first ahead of a far-more-popular sequel — tier order
  dominates the popularity tiebreak, as designed) and "Frank Herbert"
  (title-tier matches like a biography outrank the pure author-tier match
  on "Dune" itself — also as designed, confirming tier separation is
  working correctly, not a bug); full shelf lifecycle (create → rename →
  add a book → list its books → shelf-scoped discover recommendations →
  delete); rate a book and confirm it appears correctly sorted in
  `/me/ratings`. Clean server logs throughout.
- **Not built**: an automated accessibility audit (Phase 9); a "list all
  genres" endpoint for the Rated page's genre filter to become a dropdown
  instead of free text; cross-request duplicate suppression for Search
  (same `exclude`-not-wired scope trim as Home, Phase 7 risk #55 — search
  has no analogous mechanism at all, since ADR-0012 deliberately skips
  ADR-0007's persisted-batch design for search).

### Phase 9 — Hardening — **done, this pass**

- **Security headers** (`core/middleware.py::SecurityHeadersMiddleware`):
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, conditional `Strict-Transport-Security`
  when `cookie_secure` is true (spec §14). Deliberately **no CSP on the
  API** — a CSP header on Swagger's own docs response would break Swagger,
  and CORP/COOP would block the frontend's own cross-origin fetches to it;
  CSP instead lives on the frontend's production nginx config (see below).
- **General rate limiting + request size cap** (`core/request_limits.py`,
  new): `check_general_rate_limit`/`check_request_size` as global FastAPI
  `dependencies=[...]` at the `FastAPI(...)` constructor (not
  `BaseHTTPMiddleware`, which has known issues with exceptions not
  reaching `@app.exception_handler`s) — 600 requests/60s per IP, 1MB body
  cap, health checks exempted. Distinct from the auth-specific rate limit
  that's existed since Phase 3 (spec §14 asks for both: a tight bound on
  auth attempts specifically, plus a coarser backstop everywhere else).
- **Real pre-existing bug found and fixed**: every settings-dependent
  route was using `Depends(get_settings)`, which reads a process-wide
  `@lru_cache`d singleton populated by whichever `Settings()` call happens
  *first* in the process — in practice `main.py`'s own module-level
  `app = create_app()` on first import — completely ignoring a specific
  `create_app(settings=...)` call's actual settings. Dormant since Phase 3
  because no test had ever overridden an auth-relevant settings field.
  Found while writing this phase's own settings-dependent tests. Fixed via
  a new `get_request_settings(request) -> Settings: return
  request.app.state.settings` (`core/dependencies.py`), replacing
  `Depends(get_settings)` at all 4 call sites
  (`core/request_limits.py`, `modules/auth/api.py` ×3,
  `modules/auth/dependencies.py` ×1). Proved with a new regression test
  using a non-default `cookie_samesite="strict"` and checking the actual
  `Set-Cookie` header.
- **`make seed-demo`** (`cli/seed_demo.py`, new): idempotent (resets via
  the service layer before reseeding, not raw deletes), gated on
  `settings.demo_mode_enabled` (finally consuming a Phase-1-provisioned
  -but-unused field), built entirely from real service-layer calls rather
  than direct inserts. Username `demo_reader`, not `demo` — `demo` is
  itself in `username_rules.RESERVED_USERNAMES`.
- **Production Docker builds**: both Dockerfiles rewritten multi-stage
  (`apps/api`: base/dev/production — production runs `uv sync --no-dev`,
  a non-root `appuser`, no `--reload`; `apps/web`: dev/build/production —
  production is `nginx:1.27-alpine` serving the Vite build). New
  `apps/web/nginx.conf.template` uses the base image's built-in envsubst
  templating for a CSP (`connect-src 'self' ${API_ORIGIN}`, `style-src
  'self' 'unsafe-inline'` — the latter specifically because
  `RatingStars.tsx` uses inline `style={{clipPath:...}}`) plus SPA
  `try_files` fallback and gzip. `docker-compose.yml` now pins
  `target: dev` explicitly on both services — without it, Compose
  defaults to the *last* stage, now `production`, which would silently
  break local dev (no bind mount, no reload). **Still not runtime
  -verified** — Docker remains unavailable in this environment, risk #1,
  revisited at #65 below.
- **Frontend resilience**: shared `api/queryClient.ts` singleton
  (extracted from `App.tsx`) so `api/client.ts` can reach it from outside
  React; `client.ts` now distinguishes `/auth/me`'s own 401 (the normal
  "not logged in yet" bootstrap signal) from every *other* route's
  401-after-failed-refresh (genuine mid-session expiry), clearing the auth
  cache and showing a toast on the latter. Root (`App.tsx`) and route
  -level (`AppShell.tsx`, `resetKeys={[pathname]}` so navigating away
  clears a stuck error automatically) error boundaries via
  `react-error-boundary`. A toast system (`toast/toastStore.ts` — a plain
  module-level external store, not React context, specifically so
  `client.ts` can raise toasts from outside the React tree;
  `toast/ToastViewport.tsx` — Radix Toast + `useSyncExternalStore`) wired
  into all 5 optimistic `useBookState.ts` mutations' rollback paths and
  `ShelfDetailLayout.tsx`'s delete-shelf failure path (previously
  unhandled entirely).
- **Two real concurrency bugs found and fixed in `useBookState.ts`**,
  both via the new E2E test actually double-clicking controls a real
  browser fires fast — neither was hit by any jsdom/RTL test, which never
  drives two overlapping mutations against the same book:
  - `useSyncShelvesMutation`'s `onSuccess` wrote its *own* server response
    over the shared cache on every success. Checking two shelf checkboxes
    back to back fires two overlapping "full desired set" mutations for
    the same book; the earlier one's now-stale response could land *after*
    the later one's optimistic update and clobber it back to the
    incomplete set — a real lost-click bug for a real user, not just a
    test artifact. Fixed by dropping the `onSuccess` write entirely: the
    optimistic patch already *is* the correct end state for a full-replace
    sync, so there was nothing correct left for it to do.
  - `optimisticallyPatch` (shared by all 5 mutations) opened with `await
    queryClient.cancelQueries(...)` — the standard optimistic-update
    recipe, meant to stop an in-flight *refetch* from overwriting the
    optimistic value. But `useBookState`'s query is `queryFn: skipToken`,
    a pure cache mirror with no fetcher of its own — there is never
    anything to cancel, so the `await` was dead weight whose only real
    effect was delaying the optimistic write by a tick. A native
    radio/checkbox flips its own DOM state instantly on click; if React's
    controlled re-render lands late, the old value can briefly win the
    race and snap the control back. Made the function synchronous —
    closes the window entirely, matches native click semantics exactly.
  Both are documented in place (`useBookState.ts`), not just here.
- **Playwright + real Chromium** (`@playwright/test`, `@axe-core/playwright`
  added to `apps/web/package.json`; `playwright.config.ts`, new) — the
  first real, interactive browser automation available in this project at
  any phase (risk #44, revisited at #66 below). `apps/web/tsconfig.e2e.json`
  (new, referenced from `tsconfig.json`) so `npm run typecheck` actually
  covers `e2e/**` and the config file, not just `src/`; `vite.config.ts`'s
  `test.include` narrowed to `src/**/*.test.{ts,tsx}` so Vitest's default
  glob doesn't also try to execute Playwright's `.spec.ts` as jsdom tests.
- **`e2e/critical-flow.spec.ts`** (new): spec §13.5's exact 13-step flow
  as one sequential `test.step`-annotated journey (register → login →
  browse → open → rate → verify Rated → create shelf → save to multiple
  shelves → open shelf Discover → reject another book → logout → login →
  verify persistence) against a fresh, randomly-suffixed account each run
  — safe to run repeatedly against a persistent database, not just a
  throwaway CI one. Steps that need to return to a *specific* book
  navigate to it directly by captured id rather than re-picking "the first
  card" from a feed, since rating/rejecting a book makes it recommendation
  -ineligible (spec §5.5) and could otherwise reorder or remove it from
  the next feed view. Two `@axe-core/playwright` scans are folded in at
  natural checkpoints (Home after login, the book-detail dialog) — the
  first genuinely automated accessibility audit this project has run;
  only "critical"/"serious" impact violations fail the test,
  "moderate"/"minor" are logged, not enforced (risk #67). Found one real,
  moderate finding: Home has no `<h1>` (`page-has-heading-one`) — logged,
  not fixed this phase (risk #67).
- **CI**: new `e2e` job in `.github/workflows/ci.yml` — its own Postgres
  service container, `alembic upgrade head` against it directly (spec
  §13.6: "CI must apply migrations to empty PostgreSQL" — the existing
  `backend` job already does this per-integration-test against throwaway
  databases; this job additionally does it once against the persistent
  one the API actually runs against), imports `data/sample/books.parquet`
  (the small, checked-in fixture — the real dataset is gitignored and was
  never an option in CI) with `COVER_STORAGE_LOCAL_PATH=data/sample/covers`,
  boots the API in the background with the same health-check-poll pattern
  the `backend` job already uses, then `npx playwright test`. Uploads the
  HTML report as an artifact on failure. `Makefile`'s `e2e` target now
  curl-checks the API is reachable first (clear, actionable error instead
  of an opaque Playwright network failure if not) and otherwise just runs
  `playwright test`, matching `test-integration`'s existing "assumes
  Postgres is already up" convention rather than trying to orchestrate
  servers itself. Also fixed, found while checking the new target actually
  showed up: `help`'s own `grep -E '^[a-zA-Z_-]+:...'` excluded any target
  name containing a digit from the listing — `e2e` (present since Phase 1
  as a stub) had silently never appeared in `make help`'s output. One
  -character fix (`[a-zA-Z_-]+` → `[a-zA-Z0-9_-]+`); harmless as long as
  `e2e` was a no-op stub, worth fixing now that it's a real command.
- **Tests**: 241 backend (94% combined coverage — see §5h), 38 recommender
  (unaffected), 69 frontend unit/component tests (unaffected — the race
  -condition fixes above changed no observable behavior any existing test
  asserted on, only removed a redundant write and an unnecessary await),
  plus the new 13-step E2E flow with 2 accessibility scans, run 4
  consecutive times with no flakes once the two race conditions above were
  fixed.
- **Not built**: a "list all genres" endpoint (pre-existing gap, risk #62,
  untouched); solving the *error*-path variant of the shelf-sync race
  (`onError`'s rollback can still restore a stale snapshot if an earlier
  mutation genuinely fails after a later one's optimistic update landed —
  rarer, needs an actual request failure not just a slow one, left as a
  documented gap in `useBookState.ts`); a fix for the `page-has-heading-one`
  finding on Home (risk #67); Docker runtime verification (risk #1/#65).

## 3R. Recommender phased implementation plan

Source of truth: `RECOMMENDER_SPECIFICATION.md`, sequenced by
`RECOMMENDER_IMPLEMENTATION_PLAN.md`. Section references written as
`rec-spec §N` mean the former. One phase per pass; each phase leaves the
repository valid, tested and resumable.

| Phase | Scope | Status |
|---|---|---|
| R0 | Reconcile, baseline, lock architectural decisions | done |
| R1 | Interaction instrumentation, attribution, impression correctness | done |
| R2 | Rich user context, profile version, cold-start taste seeds | done |
| R3 | Artifact substrate, data validation, source-similarity export | done |
| R4 | CF artifacts: ALS + item-item | done |
| R5 | Content embeddings, multi-interest profiling, human inspection | **done, this pass** |
| R6 | Candidate-generator framework and the five generators | not started |
| R7 | Surface config, weighted RRF, deterministic ranking, UX reranking | not started |
| R8 | Pipeline engine integration, cold-start UI, serving switch | not started |
| R9 | Evaluation, performance hardening, diagnostics, documentation | not started |

### Phase R0 — Reconcile, baseline and lock architectural decisions — **done, this pass**

Goal: prepare the repository for recommender implementation **without
changing any recommendation behavior**. No models, no generators, no schema
changes. Nothing in `packages/recommender` or
`modules/recommendations` was modified.

#### R0 checklist

- [x] Read the live recommender boundary, provider/engine contracts,
  `FuturePipelineRecommendationEngine`, artifact code, recommendation
  service/transaction boundary, eligibility, persistence, context builder,
  `interaction_events`, shelves, search, frontend recommendation cards and
  settings — rather than trusting the architectural investigation.
- [x] Verify the codebase still matches what `RECOMMENDER_SPECIFICATION.md`
  §2 assumes it preserves (it does — see "Verified intact" below).
- [x] Identify and preserve uncommitted user changes (the root-document
  reorganization and the `CLAUDE.md` rewrite; both left in place, nothing
  reverted, no destructive git command run).
- [x] Add ADRs for the seven decisions that materially change the previous
  architecture/scope (ADR-0013 … ADR-0019) and amend ADR-0006's status.
- [x] Reconcile root docs so no active instruction still says the funnel is
  out of scope or that there is no next phase.
- [x] Add this checklist and the R1-R9 phase table to this document.
- [x] Restore a green baseline (`make test` / `lint` / `typecheck`).

#### Verified intact (matches rec-spec §2, confirmed against live code)

- `packages/recommender` has zero FastAPI/SQLAlchemy imports; the hygiene
  test (`tests/test_package_boundaries.py`) still enforces it.
- `RecommendationProvider`/`RecommendationEngine` protocols, the
  discriminated-union `SurfaceContext`, and the deliberately-distinct
  engine-level vs provider-level request types are all as ADR-0006 records.
- `FuturePipelineRecommendationEngine` exists and raises `EngineError`
  clearly rather than fabricating data — the plug point is real and unused.
- `InProcessProvider` + `FallbackProvider` implement spec §10.10's chain,
  including the correct skip when popularity is already the primary.
- `modules/recommendations/service.py` commits (ends) the read transaction
  before `await provider.recommend(...)` and re-validates every returned
  candidate against `get_catalog_cards` before persisting — ADR-0007's hard
  ordering constraint holds in the live code.
- Persisted batches, `(request_id, position)` ordering, opaque cursors, and
  the existence-hiding `RECOMMENDATION_CURSOR_INVALID` path are intact.
- `ArtifactManifest` carries the `book_id`/`work_id`/`model_item_index`
  triple plus model/catalog version and `trained_at`.
- Application-owned eligibility (`eligibility.py`) is pure, outside the
  recommender package, and passed in as hard exclusions.
- `data/processed/books.parquet` (92,526 rows) and `interactions.parquet`
  (775,090 rows, `user_id`/`work_id`/`rating`/`is_explicit`, no timestamps)
  are present as documented.
- `book_source_similarities` holds 269,276 catalog-resolved edges from the
  Phase 2 import.

#### Drift and gaps found (each is a later phase's input, none fixed here)

1. **Root-document reorganization broke two tests.**
   `APP_SPECIFICATION.md`, `BUILD_PROMPT.md` and
   `RECOMMENDER_CODEBASE_REPORT.md` were moved into
   `archive_of_structural_prompts/` (archived `APP_SPECIFICATION.md`
   verified byte-identical to the deleted root copy). Two backend tests
   used root `APP_SPECIFICATION.md` as the sentinel proving a hardcoded
   `parents[N]` repo-root index still resolves correctly, so both failed.
   **Fixed this phase** — see "Changed files". The sentinel is now the
   workspace's structural markers (`Makefile`, root `pyproject.toml`,
   `apps/`, `packages/`), which change only when the thing being asserted
   really does. This is the *only* code change in R0.
2. **This document contradicted `CLAUDE.md`.** §7 read "Next phase:
   **None**" and stated the funnel was permanently out of scope.
   Reconciled this phase (ADR-0013).
3. **ADR-0006 recorded the funnel as out of scope** as a live decision.
   Status amended to point at ADR-0013; its boundary decision is untouched
   and still binding.
4. **Impression writes are not idempotent — a live defect.**
   `recommendations/repository.py::create_impressions` is a plain
   `session.add_all` into a table with
   `UNIQUE(request_id, book_id)` (`uq_recommendation_impressions_*`).
   Re-fetching a persisted cursor page — an ordinary client behavior under
   ADR-0007 — will violate it. Not fixed here (R0 changes no behavior);
   this is R1's first backend task, and impression data cannot be trusted
   until it is. rec-spec §4.5.
5. **All six `interaction_events` attribution columns have zero writers.**
   `surface`, `session_id`, `recommendation_request_id`, `search_query_id`,
   `source_book_id`, `rank_position` exist and are correctly typed;
   `interactions/service.py` accepts no attribution arguments whatsoever.
   The schema barely changes in R1 — the write paths do.
6. **`shelf_books.source_surface` is plumbed but never supplied.** The
   column exists, `shelves/service.py::add_book_to_shelf` and
   `repository.py` both accept `source_surface`, and every caller omits it.
7. **No `book_opened` event type.** `EventType` has the seven Phase 4
   members only. rec-spec §4.2 needs an eighth plus a dedicated write
   endpoint; `GET /books/{id}` must stay side-effect free.
8. **No `search_queries` table** and no submitted-search persistence.
   `modules/search` is read-only (ADR-0012), which is correct — R1 adds an
   explicit write path rather than side effects on the debounced GET.
9. **`UserContext` is thinner than rec-spec §5 requires.** It has global
   `saved_book_ids` but no per-shelf membership, no `added_at`, no taste
   seeds, and `RecentInteractionSnapshot` carries only
   `event_type`/`book_id`/`occurred_at` — dropping the shelf/session/
   attribution fields R1 starts populating. `profile_version` is declared
   and optional, and **no producer sets it** (R2).
10. **Popularity artifact parsing lives in application wiring.**
    `wiring.py::_load_popularity_engine` reads `manifest.json` and
    `scores.json` inline. Correct for one artifact of one shape; does not
    generalize to five families (ADR-0014 — R3 moves loading into the
    recommender artifact layer).
11. **No source-similarity artifact export.** The 269,276 resolved edges
    are PostgreSQL-only, so nothing can use them without a database read
    during inference, which ADR-0014 forbids (R3).
12. **No numerical/ML dependencies anywhere in the workspace.** No NumPy,
    SciPy, `implicit`, `scikit-learn` or `sentence-transformers` in the
    root, `apps/api` or `packages/recommender` manifests. Every artifact
    family lands with its dependency group (R3-R5), and the text encoder
    must stay out of the API runtime set (ADR-0018).
13. **`interactions.parquet` is read by nothing.** Present since Phase 2
    and deliberately never imported into PostgreSQL (historical users are
    not application users). R4 is its first consumer.
14. **The frontend preserves no recommendation attribution.**
    `RecommendationPageResponse` already returns `request_id`, and each
    item already carries its `rank` — but `routes/Home.tsx` reads neither,
    and nothing carries them into card actions or detail navigation. The
    API-side data needed for attribution is already there; the propagation
    is not (R1/R8).
15. **`ArtifactManifest.item_mapping` is a full tuple of per-item models.**
    Fine for a manifest listing ~92k popularity entries once at startup;
    a Pydantic object per catalog item per artifact family will not scale
    to five. R3 should validate this against real load times rather than
    assume either way.

#### Decisions locked (ADRs added this phase)

| ADR | Decision |
|---|---|
| [0013](../adr/0013-recommendation-funnel-in-scope.md) | The modular recommendation funnel is in scope; supersedes ADR-0006's scope limitation only |
| [0014](../adr/0014-artifact-backed-recommender-runtime.md) | Artifact-backed runtime, no DB access from the engine, `work_id` durability, compact NumPy artifacts |
| [0015](../adr/0015-raw-events-and-attribution.md) | Raw events + optional typed attribution; no universal preference score; impression ≠ negative |
| [0016](../adr/0016-multi-interest-semantic-profiling.md) | Explicit shelf profiles **and** threshold-based inferred interest clusters; human inspectability required |
| [0017](../adr/0017-rrf-fusion-deterministic-ranker-surface-reranker.md) | Weighted RRF union, deterministic V1 ranker, surface-specific reranker |
| [0018](../adr/0018-offline-swappable-text-embeddings.md) | Offline swappable encoder (Qwen3-Embedding-0.6B, dim 512, normalized); exact batched retrieval |
| [0019](../adr/0019-cold-start-taste-seeds-as-domain-state.md) | Taste seeds are their own domain state, never ratings or shelf saves |

ADR-0006's Status section was amended to record the partial supersession.
Its Decision and Consequences remain live and binding.

#### Changed files (R0)

- `apps/api/tests/test_artifact_paths.py`,
  `apps/api/tests/test_covers.py` — repo-root sentinel switched from
  `APP_SPECIFICATION.md` to structural workspace markers; tests renamed
  from `test_repo_root_actually_contains_the_app_specification` to
  `test_repo_root_index_points_at_the_real_repo_root`. Only code change in
  this phase.
- `docs/adr/0013`…`0019` — new.
- `docs/adr/0006-recommender-provider-boundary.md` — Status amended.
- `docs/implementation/plan.md` — header (two phase sequences, spec
  relocation), §3 retitled, this §3R added, §7 rewritten.
- `README.md` — new "Specifications" section pointing at the relocated
  `APP_SPECIFICATION.md`, `RECOMMENDER_SPECIFICATION.md` and the
  precedence rules; funnel described as in progress rather than deferred.
- `data/README.md` — relocated-spec pointer.

#### Commands run (R0)

```bash
# Baseline, before any edit — the two failures below are caused by the
# root-document relocation, nothing else:
make test        # 2 failed, 125 passed (apps/api unit)
make lint        # clean
make typecheck   # clean

# After the sentinel fix:
cd apps/api && uv run pytest tests/test_artifact_paths.py tests/test_covers.py
                 # 10 passed
make test        # see §5i
make lint        # see §5i
make typecheck   # see §5i
```

No migration, API-client or e2e command was run: R0 changes no schema, no
OpenAPI surface and no frontend behavior.

#### R0 acceptance

- [x] Architecture contradictions removed or documented.
- [x] Existing tests pass (and the two that were failing on arrival now do).
- [x] No recommendation behavior changed — no file under
  `packages/recommender/src` or
  `apps/api/src/book_app/modules/recommendations/` was touched.

### Phase R1 — Interaction instrumentation, attribution and impression correctness — **done, this pass**

Goal: make the raw behavioral record trustworthy *before* building models
that depend on it. No recommendation algorithm changed; what changed is
what gets written down.

#### R1 checklist

- [x] Fix non-idempotent recommendation-impression writes (R0 drift #4 —
  a live defect, not a missing feature).
- [x] Shared typed optional `InteractionAttribution` + closed
  `InteractionSurface` set; six `interaction_events` columns finally
  written.
- [x] `book_opened` event type and a dedicated write endpoint;
  `GET /books/{id}` stays side-effect free.
- [x] Attribution propagated into rating / Not-Interested / shelf-save
  writes.
- [x] `shelf_books.source_surface` populated from a known save origin.
- [x] `search_queries` table + explicit POST write path; suggestions write
  nothing.
- [x] Search-query → book-open attribution.
- [x] Frontend browsing session (`sessionStorage`, ~30 min idle rotation,
  never the auth `sid`).
- [x] One reusable frontend attribution type, threaded surface → grid →
  card → action, and into the detail view a card opened.
- [x] Retention/cleanup policy documented (below) with no background-job
  stack added.
- [x] Tests landed with the phase; full gates green; live smoke test and
  real-browser E2E run.

#### What the app can now answer

The R1 acceptance question — *"what was shown, what did the reader
intentionally open, and which recommendation or search caused the
open/save/rating when known?"* — verified against the real dev database
(§5j), not just in tests:

| Event | surface | session | request id | search query |
|---|---|---|---|---|
| `book_opened` (from Home card) | `home` | yes | yes | — |
| `book_opened` (from a search result) | `search` | yes | — | yes |
| `rating_set` (rated after seeing it on Home) | `home` | yes | yes | — |
| `shelf_book_added` (saved from search) | `search` | yes | — | yes |
| `search_submitted` (null `book_id`) | `search` | yes | — | yes |

#### Design decisions worth recording

- **`InteractionSurface` is a closed enum, not free text**, even though the
  column is `TEXT`. This data trains models; a typo'd surface is a
  silently-wrong row that no database constraint would catch. Unknown
  values are rejected at the API edge with a 422 (tested).
- **Attribution rides on `set` operations, not `DELETE`s.** Rating removal
  and Not-Interested removal are corrections whose origin surface carries
  little preference signal, and `DELETE`-with-body is poorly supported
  across proxies and clients. Documented rather than silently skipped.
- **A shelf *removal* is never stamped with save attribution.** The
  surface a reader happened to be on while un-shelving says nothing about
  why the book was saved; stamping it would misattribute the original
  save. Explicitly tested.
- **`search_queries` has no `result_count`.** At submit time the caller
  hasn't seen results, and adding a second round trip to backfill a number
  nothing consumes isn't justified. It's an additive nullable column
  whenever a consumer appears.
- **`book_opened` fires on the card click, not on detail-route mount.** A
  click is unambiguously intentional and is the moment full attribution is
  still in hand; mounting also fires on refreshes, remounts and back
  navigation. Consequence: direct-URL/bookmark visits are *not* recorded
  as opens in R1 — see risk #83.
- **Attribution reaches the detail page via router location state.** It
  expires exactly the way attribution should — bound to that history
  entry, surviving back/forward to the same page, gone on unrelated
  navigation — so nothing has to remember to clear it, which is how stale
  attribution normally happens.
- **The submitted-search id travels through a module store, not the
  router.** Recording a search is a network round trip and navigation must
  not wait for it, so the search bar fires the write and navigates in the
  same tick; the results page picks the id up reactively if it arrives
  first. Deliberately not persisted: a reload or a shared `?q=` link is
  not a submitted search, and attributing one to an earlier sitting's
  search would be a fabricated causal link.

#### Recommendation/event data retention (documented, not automated)

rec-spec §4.5 asks for retention *considerations*, explicitly without a
background-job stack. Current position:

- `recommendation_requests` / `recommendation_results` /
  `recommendation_impressions` are a short-lived cache bounded by
  `expires_at` (30 min, ADR-0007), but nothing deletes expired rows today.
  They accumulate at roughly one request row + 60 result rows + one
  impression row per delivered book, per feed request.
- `interaction_events` and `search_queries` are **permanent** by design —
  they are the training record (ADR-0015), not a cache, and must not be
  pruned on the same schedule.
- The established pattern for this class of maintenance is an explicit CLI
  run on demand (`make cleanup-sessions`, Phase 3), not a scheduler. A
  `cleanup-recommendations` CLI following that precedent is the intended
  shape; it is **not built** — see risk #84.
- Privacy: search text and open history are personal data. They are never
  logged, never returned in diagnostics, and are removed with the user via
  `ON DELETE CASCADE` on `user_id`.

#### Changed files (R1)

Backend:

- `modules/interactions/attribution.py` — **new**: `InteractionAttribution`
  + `InteractionSurface` + `NO_ATTRIBUTION`.
- `modules/interactions/event_types.py` — `BOOK_OPENED`,
  `SEARCH_SUBMITTED`.
- `modules/interactions/repository.py` — `append_event` writes all six
  attribution columns.
- `modules/interactions/service.py` — attribution on `set_rating` /
  `set_not_interested`; new `record_book_opened`.
- `modules/books/api.py`, `modules/books/schemas.py` — `POST
  /books/{id}/opened`; optional attribution on rating / not-interested /
  shelf-sync bodies.
- `modules/shelves/service.py`, `api.py`, `schemas.py` — attribution
  through both save paths; `source_surface` finally populated.
- `modules/search/models.py` — **new**: `SearchQuery`.
- `modules/search/service.py`, `api.py`, `schemas.py` —
  `record_submitted_search`, `POST /search/queries`.
- `modules/recommendations/repository.py` — `create_impressions` is now
  `ON CONFLICT DO NOTHING`.
- `migrations/env.py` — register the new models module.
- `migrations/versions/4c90a8d2fc36_search_queries.py` — **new**, the only
  schema change in R1.

Frontend:

- `api/browsingSession.ts`, `api/attribution.ts`, `api/submittedSearch.ts`
  — **new**.
- `api/books.ts` — `recordBookOpened`; attribution on rating /
  not-interested / shelf sync.
- `hooks/useBookState.ts` — mutations accept attribution.
- `components/BookCard.tsx`, `BookMasonryGrid.tsx`,
  `ShelfSelectorPopover.tsx`, `BookDetailContent.tsx` — attribution
  threading; `book_opened` fired on card click.
- `routing/modalNavigation.ts` — attribution carried in location state;
  `useOpenAttribution`.
- `routes/Home.tsx`, `Search.tsx`, `ShelfDiscover.tsx`, `ShelfBooks.tsx`,
  `Rated.tsx`, `shell/SearchBar.tsx` — each surface supplies its own
  attribution.
- `api/generated/schema.d.ts`, `openapi.json` — regenerated (24 paths).

Tests:

- `tests/integration/test_interaction_attribution.py` — **new**, 24 tests.
- `tests/integration/test_recommendations.py` — 2 new idempotency tests.
- `apps/web/src/api/browsingSession.test.ts` (6),
  `api/submittedSearch.test.tsx` (6),
  `components/BookCardAttribution.test.tsx` (4),
  `shell/SearchBarInstrumentation.test.tsx` (4) — **new**.
- `components/ShelfSelectorPopover.test.tsx` — two assertions updated for
  the new `syncBookShelves` arity.

### Phase R2 — Rich user context, profile version and cold-start taste seeds — **done**

Goal: make the request context preserve the *structure* of a reader's
preferences, and give derived state a sound cache key. No recommendation
behavior changed — the engine still receives the same candidates; it now
receives them alongside evidence it previously never saw.

#### R2 checklist

- [x] Per-shelf saved-book snapshots (`book_id`, `shelf_id`, `added_at`),
  with the flat `saved_book_ids` kept for eligibility.
- [x] Recent events preserve the attribution R1 records instead of
  dropping it at the context boundary.
- [x] Onboarding taste seeds in `UserContext`.
- [x] Deterministic `profile_version` over durable evidence; passive
  impressions and opens leave it unchanged.
- [x] `user_taste_seeds` state + raw add/remove events; seeds are never
  ratings or shelf memberships.
- [x] `GET` / `PUT /me/taste-seeds` endpoints; OpenAPI client regenerated.
- [x] Documented bounds and truncation order for every context component.
- [x] Tests landed with the phase; full gates green; live smoke test.

#### The distinction R2 exists for

From the live smoke test, one book saved to two shelves:

```text
saved_book_ids : [58203]                      <- collapsed, eligibility
saved_books    : [(58203, shelf 7440f0f8, 2026-08-13T13:07:10),
                  (58203, shelf c00776c3, 2026-08-13T13:07:10)]
```

Both are correct for their own question. Eligibility asks "is this saved
anywhere?"; shelf-scoped semantic profiling (rec-spec §12.1) asks "what is
on *this* shelf, and how recently?". Before R2 only the first was
answerable.

#### `profile_version` semantics, verified live

| Action | Version |
|---|---|
| baseline | `v1:62eeace4a5cff481` |
| home feed delivered (impressions written) | unchanged |
| `book_opened` | unchanged |
| rating set | **changed** → `v1:72e08c2366d3bfe6` |

Included as durable evidence: rating values, shelf memberships with
`added_at`, Not Interested, taste seeds with `selected_at`. Excluded:
impressions, opens, searches.

Rating *values* are included but rating *timestamps* are not —
`user_book_states.updated_at` fires on any change to the row, including a
Not-Interested transition, so folding it in would churn the version for
reasons unrelated to the rating. Shelf `added_at` and seed `selected_at`
*are* included, because unlike a rating timestamp they are evidence
generators weight (save recency). The consequence is deliberate: removing
a book from a shelf and re-adding it changes the version even though the
membership set is identical, because the recency evidence genuinely
changed.

The version is computed over the **truncated** context components, not the
full database state — it fingerprints what the engine will actually see,
which is what makes it sound as a cache key for derived state such as an
ALS fold-in factor (rec-spec §9.2).

#### Context bounds and truncation order

Every unbounded list is ordered most-recent-first and *then* capped, so a
cap drops the oldest evidence rather than an arbitrary slice. Ties are
broken by a stable secondary key (`id` for events, `book_id`/`shelf_id` for
memberships) — without that, rows written in one transaction share a
timestamp exactly and the "most recent N" would be a non-deterministic
pick, which would in turn make `profile_version` non-deterministic.

| Component | Cap | Order |
|---|---|---|
| `ratings` | 500 | most recently rated |
| `recent_interactions` | 50 | most recent, `id` tiebreak |
| `saved_books` | 1000 memberships | most recently added |
| `taste_seeds` | 100 | most recently selected |

Sets are never truncated. `saved_book_ids` and `not_interested_book_ids`
are eligibility inputs, and silently dropping ids from those would let
excluded books back into a feed — a correctness bug, not a performance
trade-off.

#### Design decisions worth recording

- **`profile_version` is required, not optional.** It was declared
  `str | None` since Phase 5 with no producer. A cache key that might be
  absent is not a cache key, so R2 made it non-optional and updated the two
  construction sites.
- **Taste seeds are their own table** (ADR-0019), not a flag on
  `user_book_states` — that table's mutual-exclusion check constraint
  protects a real domain rule, and a seed is orthogonal to all three of its
  states. An integration test asserts a seeded book has no rating, no shelf
  membership, no Not-Interested state, and does not appear in
  `/me/ratings`.
- **Seeding is full-replace**, mirroring `sync_book_shelves`: onboarding is
  a multi-select confirmed once, so the complete set is what the client
  knows, and it makes retries idempotent. Every book id is validated before
  anything is written, so one bad id cannot leave a half-applied selection.
- **No frontend work.** rec-spec sequences the onboarding UI into R8; R2's
  frontend obligation is the regenerated client types only. A thin
  `api/tasteSeeds.ts` wrapper was deliberately *not* added — it would be an
  unused abstraction until the UI that needs it exists.
- **`_timestamp` normalizes to UTC.** Caught while writing it: rendering
  whatever offset psycopg returned would fingerprint the same instant
  differently across processes with different session time zones, quietly
  defeating the cache. There is a test for it.

#### Changed files (R2)

- `packages/recommender/.../contracts/context.py` — `SavedBookSnapshot`,
  `TasteSeedSnapshot`, seven new optional fields on
  `RecentInteractionSnapshot`, `saved_books`/`taste_seeds` on
  `UserContext`, `profile_version` now required.
- `packages/recommender/tests/conftest.py`,
  `apps/api/tests/test_recommendation_eligibility.py` — the two
  `UserContext` construction sites.
- `modules/interactions/models.py` — **new** `UserTasteSeed`.
- `modules/interactions/attribution.py` — `TasteSeedSource`.
- `modules/interactions/event_types.py` — `TASTE_SEED_ADDED/REMOVED`.
- `modules/interactions/repository.py` — seed CRUD + context rows;
  `RecentEventRow` widened to carry attribution; new `MAX_CONTEXT_*` caps.
- `modules/interactions/service.py` — `sync_taste_seeds`,
  `list_taste_seeds`.
- `modules/interactions/api.py`, `schemas.py` — `GET`/`PUT
  /me/taste-seeds`.
- `modules/shelves/repository.py` — **new** `get_saved_book_rows`.
- `modules/recommendations/profile_version.py` — **new**, pure.
- `modules/recommendations/context_builder.py` — assembles all of it.
- `migrations/versions/beb1c8746ac1_user_taste_seeds.py` — **new**, the
  only schema change.
- `tests/integration/conftest.py` — truncate `user_taste_seeds` and
  `search_queries` explicitly rather than via implicit CASCADE.
- `apps/api/tests/test_profile_version.py` (16) and
  `tests/integration/test_recommendation_context.py` (21) — **new**.
- `apps/web/src/api/generated/schema.d.ts`, `openapi.json` — regenerated.

### Phase R3 — Artifact substrate, data validation and source-similarity export — **done**

Goal: build the artifact machinery the next four phases stand on, before
there is a large model to debug through it. No recommendation *behavior*
changed — the same popularity ranking is served, through an entirely
different path.

#### R3 checklist

- [x] Artifact loading moved out of application wiring into the recommender
  package's artifact layer (drift item 10, ADR-0014).
- [x] `ArtifactManifest` preserved, but schema version 2: metadata plus
  checksums, with the item mapping moved to a compact `mapping.npz`
  (drift item 15, measured — ADR-0020).
- [x] Catalog-version compatibility validation with three outcomes
  (OK / DEGRADED / REJECTED) and safe degradation at every one.
- [x] Reusable mapping validator: `work_id` durable, `book_id` runtime-local
  and re-resolved, unresolved items dropped **and reported**, no user
  identity in the artifact contract at all.
- [x] Compact numeric helpers (`.npy`/`.npz`, optional mmap, deterministic
  bytes, no pickle, safe paths).
- [x] Source-similarity export: 269,276 resolved Goodreads edges as CSR.
- [x] Every exported edge re-validated against active catalog items at
  build time, not assumed from the import.
- [x] Runtime source-similarity loader with rank and provenance preserved.
- [x] Item-metadata artifact: stable ids, title, author, broad genre; tag
  columns exist as a declared-empty contract for R5.
- [x] `make build-recommender-artifacts` plus one target per family.
- [x] Numerical dependency added; training-only stack kept out of the API
  runtime set and guarded by a test (ADR-0018).
- [x] Full gates green; live smoke test against the real 92,524-book catalog.

#### Drift items closed

**Item 10 — popularity parsing inline in `wiring.py`.** `wiring.py` no
longer contains the word `json`. It builds a `CatalogSnapshot`, calls
`load_popularity_artifact`, and logs the diagnostics; the format lives in
`book_recommender.artifacts.popularity`, beside the writer the builder uses,
so the two halves cannot drift.

**Item 11 — source-similarity edges were PostgreSQL-only.** Exported. The
build re-validated the import's invariant against real data rather than
trusting it: 269,276 edges in the database, 269,276 exported, 0 dropped as
out-of-catalog, 0 self-edges. The invariant holds — and now there is a
builder that would say so if it stopped holding.

**Item 12 — no numerical dependencies in the workspace.** NumPy is now a
runtime dependency of both `packages/recommender` (it loads matrices) and
`apps/api` (its builders write them). Nothing heavier was added: R3 needs
no training-only dependency, and adding R4/R5's would be spillover. Risk
#81's resolution unknown is separately resolved — see §6.

**Item 15 — `ArtifactManifest.item_mapping` unmeasured at scale.** Measured,
and it was worse than "probably fine":

| | schema v1 | schema v2 |
|---|---|---|
| `manifest.json`, 92,524 items | 8.9 MB | 4 KB |
| parse to objects | 0.22 s, ~55 MB | mapping is 504 KB of `.npz` |
| `model_versions.manifest` row | 1.56 MB | ~750 bytes |
| projected, five families/worker | ~1.1 s, ~275 MB | measured 1.8 s, 77 MB for three families *including all payloads* |

ADR-0014's "compact numerical arrays over object graphs" pointed the right
way and the measurement agreed. ADR-0020 records the format change.

#### The bug this phase was really about

The v1 loader served `manifest.item_mapping[i].book_id` directly. That is
correct until the catalog is re-imported, after which PostgreSQL's
autoincrement has handed those integers to different books and the artifact
serves confident nonsense — the failure ADR-0014 calls "invisible, produces
plausible-looking output". ADR-0014 already named `work_id` as the durable
identity; nothing was *using* it.

Loaders now re-resolve every item's `work_id` against the live catalog and
serve the `book_id` that is correct now. Verified the way this document has
verified regressions throughout: the integration test
`test_a_reimport_that_reassigns_book_ids_still_serves_the_right_books` was
run against a deliberately sabotaged resolver that returned the build-time
id, confirmed to fail, and the fix restored.

The consequence is more permissive, not less: a re-import no longer breaks
artifact correctness at all, only freshness. Books added since the build are
absent from candidates; books removed are dropped with a logged count.

#### Degradation, verified rather than asserted

The three outcomes and what each does:

| Condition | Outcome | Behavior |
|---|---|---|
| missing / corrupt / v1 manifest / bad checksum | raise | caller logs and degrades |
| >10% of items unresolved | REJECTED | not served, popularity floor |
| some items unresolved | DEGRADED | served without them, count logged |
| all resolved | OK | served |

The v1-manifest case was smoke-tested live before rebuilding anything: the
old 8.9 MB artifact was still on disk, and the app started clean, logged
`popularity_artifact_unavailable` with a pydantic error naming the missing
field, and served an empty ranking. No crash, no startup failure, and the
log says what to do about it.

#### Decisions worth recording

- **Checksum verification defaults on.** It costs 3 ms for a 2.6 MB
  artifact and catches the one failure a manifest cannot describe — a
  half-written or partially-copied directory.
- **Deterministic `.npz` is hand-rolled.** `np.savez` stamps zip members
  from the wall clock, so byte-identical rebuilds are impossible with it and
  a checksum can never prove reproducibility. `save_arrays` writes the
  container with fixed timestamps and sorted members; there is a test that
  two builds produce identical bytes, and integration tests that assert it
  end to end from PostgreSQL.
- **Strings are offsets + a UTF-8 blob**, not a NumPy unicode dtype. Fixed
  width would pad every title to the longest: ~185 MB to store ~6 MB of
  text, for 92k books. Also avoids object arrays, which need pickle.
- **`allow_pickle=False` everywhere, and non-array bundle members are
  rejected.** NumPy returns raw `bytes` for a zip member that is not
  `.npy`-formatted rather than complaining — it does not unpickle it, but it
  does not object either, so a pickle payload would flow onward as a 0-d
  bytes array. Now it fails at the loader.
- **Manifest filenames must be plain filenames.** `LocalArtifactStorage`
  only refuses escapes from the storage *root*, so
  `../popularity/latest/scores.npz` would stay inside the root while reading
  a sibling artifact. Found while writing the path-traversal test, which
  did not fail as expected — the test was right about the risk and wrong
  about the existing defence. The format now forbids separators.
- **Stale files are reported, not deleted.** Rebuilding popularity left the
  v1 `scores.json` behind. The loader reads only what the manifest declares,
  so it is inert; a builder that deletes unrecognized files in a directory
  it was merely pointed at is a worse failure than a stale one. The build
  prints a warning naming them.
- **The manifest is written last.** A crash mid-build leaves a directory
  with no manifest, which the loader treats as "no artifact" and degrades
  past — better than a manifest describing files that do not exist yet.
- **The item space is the whole active catalog**, not just books a family
  has data for. All families share one `model_item_index` space, so a book
  with no source neighbours still gets an index and an empty CSR row.
- **Each family writes its own `mapping.npz`.** Families order items
  differently — popularity's order *is* its ranking — so sharing one would
  force an indirection on every family to save ~500 KB.
- **Tag columns ship empty with `tags_version: null`.** The implementation
  plan's own instruction for this task. A *declared* absence: tags present
  without a version and a version without tags are both rejected, and the
  populated shape is tested now so R5 fills a contract known to work.
- **One startup database read is not an inference-time read.** The catalog
  identity table (92,524 rows, 0.14 s) is read once at provider
  construction, before any engine exists. ADR-0007 forbids an open
  transaction *during* inference; `wiring.py` already opened a session there
  for the mock pool.
- **The training dependency group lands with R4.** R3 has no training-only
  dependency to put in it, and creating an empty one proves nothing. What
  R3 owes the constraint is a *guard*, and there are now two — one per
  package — that fail if the encoder stack reaches a runtime dependency set.

#### Changed files (R3)

New in `packages/recommender/src/book_recommender/`:

- `config.py` — typed `ArtifactFamily` registry (rec-spec §26's first
  category; the tuning categories belong to R6/R7).
- `artifacts/numeric.py` — deterministic `.npz`, `.npy` + mmap, string
  columns, checksums, typed column accessors.
- `artifacts/mapping.py` — `ItemMapping`, `CatalogSnapshot`,
  `resolve_item_mapping`, `MappingResolution`/`MappingStatus`.
- `artifacts/loader.py` — `load_artifact_bundle`, `verify_artifact_files`.
- `artifacts/writer.py` — `write_artifact`, checksums computed from the
  files actually written.
- `artifacts/popularity.py`, `artifacts/source_similarity.py`,
  `artifacts/item_metadata.py` — one module per family.

Changed:

- `artifacts/manifest.py` — schema version 2; `ArtifactItemMapping` removed,
  `ArtifactFile` added, filename validation.
- `artifacts/__init__.py` — layered re-exports.
- `apps/api/.../recommendations/wiring.py` — selects and constructs only.
- `apps/api/.../recommendations/artifact_paths.py` — family constants moved
  to the recommender package; `build_artifact_storage`,
  `read_catalog_snapshot` added.
- `apps/api/.../recommendations/artifact_build.py` — **new**, shared build
  support (`ArtifactBuildReport`, `new_model_version`,
  `register_model_version`).
- `apps/api/.../books/repository.py` — `get_active_catalog_identities`.
- `apps/api/src/book_app/cli/build_popularity.py` — rewritten onto the
  substrate.
- `apps/api/src/book_app/cli/build_source_similarity.py` — **new**.
- `apps/api/src/book_app/cli/build_item_metadata.py` — **new**.
- `Makefile` — `build-source-similarity`, `build-item-metadata`,
  `build-recommender-artifacts`.
- `packages/recommender/pyproject.toml`, `apps/api/pyproject.toml` — NumPy.
- `docs/adr/0020-artifact-manifest-v2-work-id-resolution.md` — **new**.

Tests (+93):

- `packages/recommender/tests/test_artifact_numeric.py` (17) — **new**.
- `packages/recommender/tests/test_artifact_mapping.py` (13) — **new**.
- `packages/recommender/tests/test_artifact_families.py` (25) — **new**.
- `packages/recommender/tests/test_artifacts.py` — rewritten (21).
- `packages/recommender/tests/test_package_boundaries.py` — +1, no
  training-only runtime dependency.
- `apps/api/tests/test_dependency_boundaries.py` (2) — **new**.
- `tests/integration/test_build_source_similarity.py` (9) — **new**.
- `tests/integration/test_build_item_metadata.py` (7) — **new**.
- `tests/integration/test_recommendation_wiring.py` — +3 real-artifact
  tests, including the reimport regression.
- `tests/integration/test_build_popularity.py` — updated for the new format,
  +1 stale-file test.

No migration, no OpenAPI change, no frontend change: R3 touches no schema,
no route and nothing under `apps/web`.

### Phase R4 — Collaborative-filtering artifacts: ALS + item-item — **done**

Goal: build, evaluate, serialize and load both collaborative candidate
sources. No serving behavior changed — `wiring.py` still loads only the
popularity artifact, and `FuturePipelineRecommendationEngine` is still the
unused plug point. R6 is what consumes these.

#### R4 checklist

- [x] Shared interaction transform: schema validated rather than assumed,
  `work_id` resolved onto the live catalog, versioned confidence transform,
  counts reported by rating bucket **and** mapping status.
- [x] ALS trained offline over a five-config grid with a documented
  per-user random holdout; winner retrained on the full dataset.
- [x] Item factors, mapping and training configuration persisted; historical
  user factors deliberately **not**.
- [x] Live-user fold-in in plain NumPy against fixed item factors.
- [x] Item-item CF: cosine baseline and popularity-aware BM25 compared on
  held-out data; V1 default selected on metrics *plus* coverage/popularity.
- [x] Top-K neighbours persisted compactly; runtime generator seeds from
  current positive items with no retraining.
- [x] Machine- and human-readable evaluation reports with Recall@K, NDCG@K,
  Precision/MAP@K, catalog coverage, popularity concentration and config.
- [x] Training-only dependencies in a group the API runtime does not install
  — verified by pruning, not just declared (ADR-0021).
- [x] Full gates green; live training run against the real 775k-row dataset.

#### Drift item 13 closed — the last one

`interactions.parquet` has a consumer. Present and unread since Phase 2,
it is now the training input for both CF families. The drift ledger opened
in R0 with fifteen items is empty.

Schema validated against the real file rather than trusted: `user_id`
int32, `work_id` string, `rating` int8, `is_explicit` bool, 775,090 rows,
83,200 users, 92,526 works, no nulls. `rating == 0` occurs 474,910 times
and coincides exactly with `is_explicit == False`, which is what rec-spec
§7.2's implicit-positive rule depends on — so the transform now rejects a
row claiming to be an explicit 0 rather than silently mis-weighting it.

#### What the transform does with the real data

| Bucket | Rows | Treatment |
|---|---:|---|
| rating 0 (implicit) | 474,910 | weakest positive, confidence 1.0 |
| rating 6 (neutral) | 24,195 | **dropped** by default; swept as a variant |
| ratings 7-10 | 232,392 | positive, confidence 2.0 → 5.0 |
| ratings 1-5 | 43,593 | **dropped** — omitted, not trained as negatives |
| unresolved `work_id` | 5 | **dropped and reported** (2 distinct works) |
| **used** | **707,297** | 76,369 users × 88,864 items |

The counts reconcile exactly: 707,297 + 5 + 43,593 + 24,195 = 775,090.
Exactly 2 of the parquet's 92,526 works are absent from the 92,524-book
catalog, which is the drop-and-report path running on real data rather than
on a fixture.

rec-spec §7.2's rules are enforced structurally, not by comment: historical
`user_id` is remapped to a dense training index and never leaves the
transform in a form joinable to a `users` row, no timestamps exist so
nothing weights or splits by recency, and ratings 1-5 are omitted rather
than fed to ALS as negative confidence.

#### Model selection, and the criterion that changed a decision

Both sweeps evaluate on a per-user random holdout (rec-spec §23.1 — random
because the data has no timestamps and a temporal split would be fiction):
20% of each reader with ≥5 positives, capped at 20 items, 15,747 readers
evaluated.

ALS, five configs, NDCG@50:

| config | recall@10 | ndcg@10 | recall@50 | ndcg@50 |
|---|---:|---:|---:|---:|
| f64-r0.05 | 0.0548 | 0.0421 | **0.1180** | 0.0600 |
| f96-r0.05 | 0.0564 | 0.0449 | 0.1174 | 0.0621 |
| **f128-r0.05** | **0.0587** | **0.0468** | 0.1179 | **0.0633** |
| f96-r0.01 | 0.0565 | 0.0450 | 0.1172 | 0.0621 |
| f96-r0.10 | 0.0563 | 0.0449 | 0.1171 | 0.0620 |

Factor count helps; regularization is nearly inert across 0.01-0.10.

Item-CF, two variants — where the criterion mattered:

| variant | ndcg@10 | recall@50 | ndcg@50 | coverage | Gini |
|---|---:|---:|---:|---:|---:|
| cosine-k100 | **0.0215** | 0.0347 | 0.0241 | 0.399 | 0.577 |
| **bm25-k100** | 0.0208 | **0.0420** | **0.0258** | **0.547** | **0.374** |

The first implementation selected on NDCG@10 and shipped cosine on a 3%
edge. That is the wrong stage to measure: these are **candidate
generators** feeding weighted RRF (ADR-0017), not the final ranker, so what
matters is getting relevant items into a deep pool in a sensible rank
order. Selection moved to `SELECTION_K = 50`, which ships BM25 — 21% better
at candidate depth, 37% more catalog coverage, far less popularity
concentration, and what rec-spec §10's "plus coverage/popularity behavior"
points at. ALS picks f128 under either criterion, so the rule was not
reverse-engineered from a preferred answer. ADR-0021 records it.

#### A bug the tests found in this phase's own code

The BM25 implementation multiplied each item's column by its IDF — and
`train_item_neighbors` L2-normalizes each item vector before comparing.
Normalization cancels a scalar multiple exactly, so the IDF term was
arithmetic with no effect that read like popularity correction. Caught by a
test asserting BM25 would down-weight a ubiquitous item, which failed with
the two maxima equal to seven decimal places.

Removed, with the reasoning recorded where the next reader will need it.
What "BM25" means here is the two terms that survive normalization: `k1`
saturation and `b` user-length normalization — a reader with 500 books
provides weaker per-book evidence than one with 5. That is a genuine
popularity correction, expressed on the user side, and it is what produces
the coverage and Gini improvements above. The replacement test constructs
two items with identical co-occurrence counts reached through prolific
versus focused readers, and asserts cosine ties them while BM25 separates
them.

#### Decisions worth recording

- **Historical user factors are never persisted.** rec-spec §9.1 calls them
  optional; they are excluded outright, because 83,200 Book-Crossing user
  vectors describe people who are not application users and nothing may
  join them. A test asserts the artifact directory contains exactly
  `manifest.json`, `mapping.npz`, `item_factors.npy` and that the manifest
  text contains no occurrence of "user".
- **The winner is retrained on the full dataset.** The holdout exists to
  rank configurations; shipping a model that never saw 20% of the evidence
  would waste it.
- **Fold-in is plain NumPy in the recommender package.** The standard
  implicit-ALS solve, with `YᵀY` precomputed once at load because it does
  not depend on the user. This is what keeps `implicit` out of the API
  runtime while still serving what it trained: 6 ms for a fold-in plus a
  92k-item scoring pass.
- **A cold user gets `None`, not a zero vector.** Scoring against zeros
  would rank the catalog by nothing while looking like it worked, so the
  caller is told to fall back.
- **Exclusions are applied before top-K selection**, not by over-fetching
  and filtering after, so a heavily-excluded reader still gets a full page.
- **Item-CF aggregation is additive across seeds**, deliberately: a book
  reachable from several of a reader's books *should* outrank one reachable
  from a single book. rec-spec §7.1's warning about "uncontrolled
  double-counting" applies to the seed weights the caller supplies, which is
  where R6 will cap it.
- **Both families share the catalog's item order.** The training matrix
  spans the whole catalog rather than only interacted items, so column *i*
  is `model_item_index` *i* in every artifact. An integration test loads
  both families and asserts they agree book-for-book.
- **Nothing was wired into the serving path.** rec-spec sequences candidate
  generators into R6 and the pipeline engine into R8. `wiring.py` contains
  no reference to either loader, and loading 81 MB of artifacts that nothing
  consumes would cost memory per worker for no benefit.

#### Changed files (R4)

New:

- `packages/recommender/.../artifacts/als.py` — `AlsArtifact`, fold-in,
  scoring, exclusion-aware top-K.
- `packages/recommender/.../artifacts/item_cf.py` — `ItemCfNeighbors`,
  seed-based candidate aggregation.
- `apps/api/.../recommendations/interaction_transform.py` — the shared
  transform (pure pandas/NumPy).
- `apps/api/.../recommendations/cf_evaluation.py` — holdout + metrics +
  report writer (pure NumPy).
- `apps/api/.../recommendations/cf_training.py` — **the only module that
  imports `implicit` or `scipy`**.
- `apps/api/src/book_app/cli/build_als.py`, `build_item_cf.py`.
- `docs/adr/0021-training-dependency-isolation-and-cf-model-selection.md`.

Changed:

- `packages/recommender/.../config.py` — `HistoricalInteractionTransform`,
  `AlsConfig`/`ItemCfConfig` + sweeps, `HoldoutConfig`, `SELECTION_K`,
  `ALS`/`ITEM_CF` families.
- `packages/recommender/.../artifacts/__init__.py` — new exports.
- `apps/api/pyproject.toml` — `training` dependency group; mypy overrides so
  the default gate typechecks without it installed.
- `Makefile` — `setup-training`, `build-als`, `build-item-cf`;
  `build-recommender-artifacts` now covers all five families.

Tests (+99):

- `packages/recommender/tests/test_als_artifact.py` (18) — **new**.
- `packages/recommender/tests/test_item_cf_artifact.py` (14) — **new**.
- `apps/api/tests/test_interaction_transform.py` (17) — **new**.
- `apps/api/tests/test_cf_evaluation.py` (23) — **new**.
- `apps/api/tests/test_cf_training.py` (16) — **new**, skipped as a module
  without the training group.
- `tests/integration/test_build_cf_artifacts.py` (11) — **new**, likewise.

83 of the 99 run in the default environment. The 16 that need `implicit`
and `scipy` are the trainers themselves; everything they produce — fold-in,
neighbour retrieval, exclusions, determinism of the *artifact* — is covered
without the group, so the default gate still fails if R4's runtime
behaviour breaks.

No migration, no OpenAPI change, no frontend change.

### Phase R5 — Content embeddings, multi-interest profiling and human inspection — **done, this pass**

Goal: build the semantic item space and the user-interest profiler. No
serving behavior changed — `wiring.py` still loads only popularity, and
`FuturePipelineRecommendationEngine` is still the unused plug point. R6
consumes what this phase produced.

#### R5 checklist

- [x] Deterministic versioned book-text builder: title, primary author,
  broad genres, cleaned shelf tags, description last.
- [x] Tested shelf-tag cleaning that strips bookkeeping/status/personal
  tags; capped per book; rules versioned.
- [x] Default encoder `Qwen/Qwen3-Embedding-0.6B`, dimension 512,
  normalized, swappable, with encoder/revision/dimension/prompt/template/
  tag versions all recorded in the manifest.
- [x] Embedding build is offline; the API never loads the model — enforced
  by a behavioural test, not just a grep.
- [x] Compact exact-search-friendly artifact + semantic retrieval primitive
  (batched dot products, efficient exclusion filtering, no vector DB).
- [x] Explicit shelf profiles (weighted normalized per-shelf vectors).
- [x] Pure `InterestProfiler`: threshold agglomerative cosine clustering,
  no fixed K, with rec-spec §12.2's full fallback ladder.
- [x] Centroid default, medoid computed, strategy configurable.
- [x] Human-inspectable summaries with deterministic non-LLM labels.
- [x] `make inspect-recommender-profile USERNAME=<name>` (+ `--json`),
  calling the same profiling code as serving.
- [x] Item-metadata tag columns filled — the contract R3 wrote empty.
- [x] Full gates green; live build over the real 92,524-book catalog.

#### The decision that shaped the phase

rec-spec §12.2's clustering runs at **serving** time — a reader's interests
are inferred when their batch is built. The obvious implementation imports
scikit-learn's `AgglomerativeClustering`, and scikit-learn is a
training-only dependency that ADR-0021 prunes out of the API environment.

So it is ~40 lines of average-linkage clustering in pure NumPy over a cosine
similarity matrix, bounded to ~100 items by rec-spec §12.2. That is the same
reasoning applied for the third time: **every runtime counterpart of a
training library is plain NumPy** — ALS fold-in without `implicit`,
neighbour lookup without `scipy`, interest clustering without
`scikit-learn`. ADR-0022 records it.

#### Tag cleaning, against real data

The catalog has 173,787 distinct tags over 1,699,225 links, and the top of
that list mixes subject matter with filing systems: `fiction` (51,384
books) sits beside `to-read`, `books-i-have`, `kindle-books`,
`shelfari-wishlist` and `read-in-2011`. Embedding the second group would
cluster books by how people file them.

Matching is on **whole tokens, never substrings** — `own` must reject
`own-to-read` without touching `downtown`; `read` must not take
`spreadsheets` with it. On the live catalog:

| Rejected because | Links |
|---|---:|
| bookkeeping token (`owned`, `kindle`, `favorites`, …) | 222,755 |
| reading-log year (`read-in-2011`, `2012-reads`) | 33,051 |
| bookkeeping phrase (`to-read`, `series`, …) | 27,954 |
| challenge list (`1001-books-to-read-before-you-die`) | 25,002 |
| too short / numeric | 24,199 |
| **total rejected** | **332,962 (19.6%)** |

What survives is recognisably thematic. A real example from the build:

```text
#1 'A Field Guide to American Houses'
   architecture, reference, non-fiction, history, art, design, home,
   real-estate, historic-preservation
#2 'The Three Sisters'
   plays, classics, drama, russian, russian-literature
#3 'A Celtic Childhood'
   ireland, memoir, autobiography, celtic-irish
```

#### Encoder cost, measured before committing to it

Not a model limit — Qwen3-Embedding-0.6B accepts 32,768 tokens — but a cost
decision. Median book text is ~722 characters (~180 tokens) and the 90th
percentile ~1,519; 512 tokens covers the corpus.

| max_seq | batch | books/s | full catalog |
|---:|---:|---:|---:|
| 512 | 8 | 17.1 | 90 min |
| **512** | **16** | **17.6** | **88 min** |
| 512 | 32 | 15.0 | 103 min |
| 512 | 64 | 11.0 | 140 min |
| 256 | 64 | 18.6 | 83 min |

512/16 shipped: the 256-token variant is barely faster and truncates the
90th-percentile description. The model download is a one-time ~1.2 GB;
`--limit` exists for development.

#### Two corrections this phase made to its own earlier work

**The R4 dependency-boundary test was too blunt.** It asserted that *no*
file under `apps/api/src` imports a text encoder, which R5's legitimate
offline `content_encoding.py` broke. Rather than weaken it, it was split in
two and made stronger: a source scan that allows exactly two named offline
modules, plus a behavioural test that imports `book_app.main` in a
subprocess and asserts no transformer module lands in `sys.modules`.

Both halves were sabotage-verified. The scan fires when a non-designated
module imports the stack. The behavioural test's *reach* was checked rather
than assumed, and the docstring corrected: it covers the import graph
reachable from `book_app.main`, so adding an encoder import to a CLI does
**not** fail it — which is what the source scan is for. When R6 wires
semantic generators into serving, `semantic_profile` enters that graph and
the behavioural test starts covering it too.

**An R3 validation rule was wrong.** The item-metadata loader rejected an
artifact that declared a `tags_version` but contained no tags, on the
theory that it indicated a build bug. Real data disproved it: a version
means "these rules produced whatever is here", and *no usable tags* is a
legitimate outcome — 501 of 92,524 books end up with none once bookkeeping
shelves are stripped, and a small catalog can easily have none at all. The
check was removed with the reasoning recorded inline; the opposite
direction (tags with no version — unknown cleaning rules) still rejects.

#### Decisions worth recording

- **Description last in the template**, so encoder truncation removes
  description tail rather than title or author.
- **Absent fields are omitted**, not emitted as dangling labels — ~2,300
  catalog books have no author, and `Author:` followed by nothing is noise
  the encoder has to interpret.
- **rec-spec §11.2's "do not embed" list is honoured literally**: no
  ratings, popularity counts, ISBNs, page counts or ids. There is a test
  asserting none of them reach the text, because embedding "4.27 average
  rating" would let the encoder cluster by how well books sold.
- **The loader refuses an artifact that is not normalized** — and checks a
  deterministic sample of rows rather than trusting the manifest flag.
  Retrieval treats the dot product as cosine, so unnormalized vectors would
  rank by magnitude (longer descriptions first) and look plausible.
- **The resolved encoder commit hash is recorded** when the hub supplies
  one (`97b0c614…`), because loading by tag records only the tag and will
  silently mean a different model later.
- **The fallback ladder is implemented literally and the branch is
  recorded.** "This reader has one interest" and "this reader had too little
  evidence to cluster" look identical from outside and mean opposite
  things, so `ProfileStrategy` names which happened.
- **A term used by only one member of a multi-book interest cannot label
  it** — it describes that book, not the interest. Ties break
  alphabetically so a label cannot silently rename itself between runs.
- **Summaries never contain vectors** (rec-spec §13), which is also what
  keeps diagnostics from becoming the data dump CLAUDE.md warns about.
- **One book with several signals counts once**, at its strongest weight —
  rec-spec §7.1's "avoid uncontrolled double-counting". A saved *and*
  10/10-rated book must not dominate a cluster by appearing twice.

#### Changed files (R5)

New in `packages/recommender/src/book_recommender/`:

- `content/tags.py`, `content/text_builder.py` — versioned, pure.
- `artifacts/content.py` — embedding artifact + exact batched retrieval.
- `profiling/clustering.py` — pure-NumPy average-linkage clustering.
- `profiling/interests.py` — evidence ranking, fallback ladder, shelf
  profiles.
- `profiling/summaries.py` — rec-spec §13's inspectable structures.

New in `apps/api`:

- `modules/recommendations/content_source.py` — catalog → encoder text
  (no torch, so it is integration-tested normally).
- `modules/recommendations/content_encoding.py` — the encoder wrapper, one
  of only two modules allowed to import the training stack.
- `modules/recommendations/semantic_profile.py` — signal policy → evidence.
- `cli/build_content_embeddings.py`, `cli/inspect_profile.py`.

Changed:

- `config.py` — `CONTENT` family, `EncoderConfig`, `InterestProfileConfig`,
  `SignalWeights`.
- `cli/build_item_metadata.py` — fills the tag columns.
- `artifacts/item_metadata.py` — the corrected validation rule.
- `tests/test_dependency_boundaries.py` — split and hardened.
- `pyproject.toml` — `sentence-transformers` in the `training` group.
- `Makefile` — `build-content`, `inspect-recommender-profile`.
- `docs/adr/0022-…md` — new.

Tests (+112): 47 content text/tags, 29 interest profiling, 18 content
artifact, 10 semantic profile, 8 content source (integration).

No migration, no OpenAPI change, no frontend change.

### Phases R6-R9 — not started

Scope, tasks and per-phase acceptance criteria live in
`RECOMMENDER_IMPLEMENTATION_PLAN.md` and are not duplicated here. Each phase
appends its own record to this section as it lands, in the same shape as
R0-R5 above: checklist, drift found, decisions/ADRs, changed files,
commands run with real results, and unresolved risks appended to §6.

Standing constraints for every recommender phase (from `CLAUDE.md` and
rec-spec §2, restated because they are the ones easiest to violate
accidentally while adding models):

- no FastAPI/ORM imports in `packages/recommender`;
- no PostgreSQL access during inference, and no open transaction while it
  runs;
- `work_id` is the durable identity — PostgreSQL `book_id` is not;
- engine order is authoritative and nothing downstream re-sorts it;
- popularity stays a working fallback at every step;
- missing/corrupt artifacts degrade, never fail startup;
- tunables stay centralized and typed, not scattered as literals;
- tests land with the phase, not after it.

## 4. Acceptance checklist

Mirrors spec §19, grouped the same way. Checked items are true today; this
section is updated at the end of every phase — nothing below is marked done
on the basis of intent, only of a passing command.

### Functional

- [x] Username/password registration and persistent login state (register/login/refresh/logout/me/change-password all live and integration-tested against real PostgreSQL — spec §9.1)
- [x] Logout/login preserves shelves/history (all state keyed by durable `user_id` in Postgres — shelves/ratings/events now exist and are integration-tested independently of any one session; not re-verified as one single logout-then-log-back-in-then-check-shelves test, but the two halves — session durability from Phase 3, per-user state persistence from this phase — are each already proven separately)
- [x] Parquet catalog import (`make import-data`; full 92,526-row catalog imported and verified — see Phase 2)
- [x] Local covers (`LocalFileStorage` + safe path resolution, spec §7.3, now actually serving requests via `GET /api/v1/covers/{object_key}`, spec §20/ADR-0011 — **correcting this plan's own Phase 4/6-era note**, which read spec §9's silence on a cover route as meaning none was needed; Phase 7 needed to actually render an image for the first time and found spec §20's "do not construct cover paths in frontend" requires exactly this route to exist)
- [x] Home feed through provider (`GET /recommendations/home`, spec §9.5 — mock and popularity providers both live-tested; now rendered end to end, masonry grid + infinite scroll + skeleton/retry/empty states, spec §12.4)
- [x] Title/author search (`GET /search/books`, spec §9.6's seven-tier ranking, ADR-0012 — rendered end to end: debounced suggestions in the top bar, full masonry results at `/search?q=...` with state badges)
- [x] Book detail (`GET /books/{id}` — spec §12.7's fields (minus a dedicated "series" display, see risk #48) now rendered end to end, including the similar-books grid, `GET /recommendations/books/{id}/similar`, as a route-backed modal on desktop and a full page on direct navigation)
- [x] Half-star ratings (`PUT/DELETE /books/{id}/rating`, spec §9.2 half-step conversion; `RatingStars` now renders and calls it with optimistic update + rollback, spec §12.7/§12.11)
- [x] Mutual exclusivity with Not Interested (service logic + DB `CheckConstraint`, spec §5.2)
- [x] State removal (`DELETE` rating/not-interested, idempotent, spec §5.3)
- [x] Full shelf management (create/rename/describe/delete, spec §5.4/§9.3 — rendered end to end: create + collage overview, rename/edit-description/delete on the shelf detail header)
- [x] Multi-shelf books (a book may belong to zero/one/many shelves; `PUT /books/{id}/shelves` atomic sync)
- [x] Not Interested may remain shelved (explicit integration test — spec §5.3/§12.7)
- [x] Shelf feed allows books from other shelves (`GET /recommendations/shelves/{id}`, spec §5.5 — `shelf_exclusions` only excludes *this* shelf's books, not every shelf; integration-tested)
- [x] Rated page (`GET /me/ratings` — all 5 sorts, rating-range/genre filters, cursor pagination — now rendered end to end with sort toggles and range/genre filter controls)
- [x] Similar books (`GET /recommendations/books/{id}/similar`, spec §5.5 — excludes source/rated/Not-Interested, saved books remain eligible; rendered on the detail page via the same `BookMasonryGrid` Home uses, single page rather than infinite-scrolled, risk #54)
- [x] Cursor pages without duplicates (recommendation batches: `PK(request_id, position)` plus a defensive disjoint-pages integration test per surface, spec §9.9/ADR-0007)
- [x] Fallback provider (spec §10.10's chain, contract-tested in `packages/recommender` and integration-tested at the apps/api boundary via a dependency-override 503 test)

### Architecture

- [x] Modular monolith skeleton (`apps/api/src/book_app/{core,shared,modules,cli}` — `modules/{books,users,auth,shelves,interactions,recommendations}` all have real content now; only `modules/search` remains empty)
- [x] No frontend DB access (frontend has no DB driver/credentials; talks HTTP only)
- [x] No recommender logic in routes (`modules/recommendations/service.py` orchestrates eligibility + the typed provider boundary; every ranking/scoring decision lives in `packages/recommender` or the `build-popularity` CLI, never in a route or service)
- [x] Recommender package independent of FastAPI/ORM (`packages/recommender` now has real contracts/engines/providers/artifacts — still zero FastAPI/SQLAlchemy dependencies, verified by the same repo-hygiene test, now exercising real content instead of an empty skeleton)
- [x] Service-owned transactions (`recommendations/service.py` explicitly ends its read transaction before calling the provider and commits again afterward — spec §11's hard ordering constraint, ADR-0007 — in addition to the pattern already established by every other service)
- [x] Append-only events (unchanged this phase — recommendation *impressions* are their own dedicated table, spec §8.10, not `interaction_events`)
- [x] Environment config (typed `Settings` covering every §11 category — `recommendation_provider`/`artifact_storage_*` now actually consumed, not just declared)
- [x] Storage abstractions (`ObjectStorage`/`LocalFileStorage` for covers unchanged; `packages/recommender`'s own `LocalArtifactStorage` for model artifacts, spec §10.13 — S3 for both still deferred, see §6)
- [x] Explicit ID mappings (`work_id -> books.id` unchanged; the `book_id`/`work_id`/`model_item_index` triple for model artifacts is now real, spec §7.5 — `ArtifactManifest.item_mapping`)

### Quality

- [x] Empty-db migrations (`tests/integration/test_migrations.py`: fresh database, `upgrade head`, plus an explicit `downgrade base` → `upgrade head` round trip; re-verified after adding the Phase 5 migration, including a live re-run against the dev database)
- [x] Critical tests for what exists (everything through Phase 8 already
  covered, plus this phase's own: security headers, general rate limiting
  and request-size cap, the `get_request_settings` regression test, `make
  seed-demo` idempotency/gating — 241 apps/api-unit-plus-integration tests
  combined (94% coverage on `book_app`, spec §13.6's 75% floor), 38
  recommender, 69 frontend, and the new E2E critical-flow test itself)
- [x] E2E flow (`apps/web/e2e/critical-flow.spec.ts`, spec §13.5's exact
  13 steps, real Chromium via Playwright — run 4 consecutive times clean
  after fixing two real optimistic-update race conditions it caught live,
  see Phase 9 above)
- [x] Lint/type/build success for everything created this pass, including
  `tests/integration`, `packages/recommender`, and — new this phase —
  `apps/web/e2e` and `playwright.config.ts` (covered by the new
  `tsconfig.e2e.json`, not previously type-checked at all since it didn't
  exist) (see §5h command log)
- [x] No secrets committed (`.env` gitignored, only `.env.example` with fake values tracked)
- [x] No stack traces exposed (shared exception handler returns the §9.8 envelope only)
- [x] Keyboard accessibility (auth forms, nav, avatar menu, `RatingStars`'
  native radio inputs, the shelf selector's native checkboxes, and Radix
  `Dialog`/`AlertDialog`/`Popover`/`Toast` throughout, each providing
  focus trap and Escape for free, spec §12.12 — **and now a real automated
  audit**: two `@axe-core/playwright` scans (Home, the book-detail dialog)
  run as part of the E2E test, gating on critical/serious violations. One
  real, moderate, non-blocking finding surfaced and is tracked, not yet
  fixed: Home has no `<h1>` (risk #67))
- [x] Setup docs (this plan + root `README.md`)
- [x] AWS mapping documented (ADR-0009, `README.md`)
- [ ] Usable `docker compose up` flow (both Dockerfiles now multi-stage
  and production-hardened, `docker-compose.yml` pins `target: dev` so
  Compose doesn't default to the production stage locally — still **not
  runtime-verified**, Docker remains unavailable in this environment,
  risk #1/#65)

## 5. Phase 1 validation commands and results

Run from the repo root unless noted. Exact output is in the final report
message for this session; this table is the reusable reference for future
runs.

```bash
# Backend
cd apps/api
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run mypy .
uv run pytest --cov=book_app --cov-report=term-missing

# Recommender package
cd packages/recommender
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run mypy .
uv run pytest

# Frontend
cd apps/web
npm install
npm run lint
npm run typecheck
npm run test
npm run build

# Local Postgres (no Docker available — project-local cluster instead)
make db-start
make dev-api          # boots FastAPI against the local cluster
curl -sf http://localhost:8000/api/v1/health/live
curl -sf http://localhost:8000/api/v1/health/ready
make db-stop

# Config sanity (no docker CLI available to run `docker compose config`)
python3 -c "import yaml,sys; yaml.safe_load(open('docker-compose.yml'))"
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

## 5a. Phase 2 validation commands and results

```bash
# Migrations, against a genuinely empty database
make db-start
cd apps/api
uv run alembic upgrade head
uv run alembic downgrade base    # must leave zero tables/types besides alembic_version
uv run alembic upgrade head      # must succeed cleanly again

# Lint/types (now includes the import adapter, repository, CLI, storage, models)
uv run ruff format --check . && uv run ruff check .
uv run mypy .

# Unit tests (fast, no DB) + integration tests (real Postgres, own throwaway
# `book_app_test` database — see tests/integration/conftest.py)
uv run pytest --cov=book_app --cov-report=term-missing        # unit only: ~35% (expected — see §6)
uv run pytest tests ../../tests/integration --cov=book_app --cov-report=term-missing  # combined: 91%

# tests/integration/ lint (not covered by apps/api's own mypy — see §6)
cd ../..
uv run --project apps/api ruff format --check tests
uv run --project apps/api ruff check tests

# The actual import, dry-run then real, against the full 92,526-row catalog
cd apps/api
uv run python -m book_app.cli.import_catalog --dry-run
uv run python -m book_app.cli.import_catalog
# or: make import-data-dry-run / make import-data / make migrate / make test-integration
```

Future phases append their own validation block here instead of replacing
this one (spec §18: "run tests after each phase").

## 5b. Phase 3 validation commands and results

```bash
# Migrations (adds account_status/users/auth_sessions on top of Phase 2's schema)
make db-start
cd apps/api
uv run alembic upgrade head
uv run alembic downgrade base && uv run alembic upgrade head   # full round trip again

# Lint/types (now includes users/auth modules, security, rate limiting)
uv run ruff format --check . && uv run ruff check .
uv run mypy .

# Unit tests (69) + integration tests (28) + combined coverage
uv run pytest -q                                                          # unit only
uv run pytest tests ../../tests/integration --cov=book_app --cov-report=term-missing
cd ../.. && uv run --project apps/api ruff format --check tests && uv run --project apps/api ruff check tests

# Live smoke test against real Postgres (what actually found the bugs in §6)
cd apps/api
uv run uvicorn book_app.main:app --host 127.0.0.1 --port 8010 &
curl -sc /tmp/c -X POST http://127.0.0.1:8010/api/v1/auth/register -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"correct horse battery staple","password_confirmation":"correct horse battery staple"}'
curl -sc /tmp/c -b /tmp/c -X POST http://127.0.0.1:8010/api/v1/auth/login -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"correct horse battery staple"}'
curl -s -b /tmp/c http://127.0.0.1:8010/api/v1/auth/me
```

## 5c. Phase 4 validation commands and results

```bash
# Migrations (adds interaction_events/shelves/user_book_states/shelf_books)
make db-start
cd apps/api
uv run alembic upgrade head
uv run alembic check                             # only the pre-existing trigram-index false positive
uv run alembic downgrade base && uv run alembic upgrade head   # full round trip again

# Migrating base->head->base->head against the dev DB wipes its catalog rows
# (books/authors/genres tables get dropped and recreated) — re-import after:
uv run python -m book_app.cli.import_catalog     # back to 92,524 books

# Lint/types (now includes books/shelves/interactions modules, shared/pagination)
uv run ruff format --check . && uv run ruff check .
uv run mypy .

# Unit tests (102) + integration tests (73) + combined coverage
uv run pytest -q                                                          # unit only
uv run pytest tests ../../tests/integration --cov=book_app --cov-report=term-missing   # 94%
cd ../.. && uv run --project apps/api ruff format --check tests && uv run --project apps/api ruff check tests

# Live smoke test against the real dev database (92,524 real books) — full
# detail -> rate -> not-interested -> shelf-create -> shelf-add -> shelf-sync
# -> /me/ratings flow, plus 401/403/404 authorization paths
cd apps/api
uv run uvicorn book_app.main:app --host 127.0.0.1 --port 8000 &
curl -sc /tmp/c -X POST http://127.0.0.1:8000/api/v1/auth/register -H "Content-Type: application/json" \
  -d '{"username":"demo4","password":"correct horse battery staple","password_confirmation":"correct horse battery staple"}'
curl -sc /tmp/c -b /tmp/c -X POST http://127.0.0.1:8000/api/v1/auth/login -H "Content-Type: application/json" \
  -d '{"username":"demo4","password":"correct horse battery staple"}'
CSRF=$(grep csrf_token /tmp/c | awk '{print $NF}')
curl -s -b /tmp/c http://127.0.0.1:8000/api/v1/books/1
curl -s -b /tmp/c -X PUT http://127.0.0.1:8000/api/v1/books/1/rating -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" -d '{"rating": 4.5}'
curl -s -b /tmp/c http://127.0.0.1:8000/api/v1/me/ratings
```

Result: all green — see the acceptance checklist above for the exact counts
and coverage this run produced.

## 5d. Phase 5 validation commands and results

```bash
# Migrations (adds model_versions/recommendation_requests/results/impressions)
make db-start
cd apps/api
uv run alembic upgrade head
uv run alembic check                             # only the pre-existing trigram-index false positive
uv run alembic downgrade base && uv run alembic upgrade head   # full round trip again
uv run python -m book_app.cli.import_catalog     # re-import; the round trip wipes the dev DB's catalog

# Lint/types — apps/api, packages/recommender, and tests/ each have their
# own config; tests/ must be checked via the exact make-lint invocation
# (repo root, no explicit --config) — apps/api's own 100-char config does
# NOT apply there, only its 88-char built-in default does (see risk #35).
uv run ruff format --check . && uv run ruff check . && uv run mypy .
cd ../../packages/recommender
uv run ruff format --check . && uv run ruff check . && uv run mypy .
cd ../..
uv run --project apps/api ruff format --check tests
uv run --project apps/api ruff check tests

# Unit tests (109 apps/api + 38 recommender) + integration (100) + combined coverage
cd apps/api
uv run pytest -q                                                          # unit only
uv run pytest tests ../../tests/integration --cov=book_app --cov-report=term-missing   # 95%
cd ../../packages/recommender && uv run pytest -q                          # 38 passed

# Build the popularity artifact against the real dev database, then
# live-smoke-test both provider configurations
cd ../../apps/api
make build-popularity    # from repo root; ranks all 92,524 active books
uv run uvicorn book_app.main:app --host 127.0.0.1 --port 8000 &
curl -sc /tmp/c5 -X POST http://127.0.0.1:8000/api/v1/auth/register -H "Content-Type: application/json" \
  -d '{"username":"demo5","password":"correct horse battery staple","password_confirmation":"correct horse battery staple"}'
curl -sc /tmp/c5 -b /tmp/c5 -X POST http://127.0.0.1:8000/api/v1/auth/login -H "Content-Type: application/json" \
  -d '{"username":"demo5","password":"correct horse battery staple"}'
curl -s -b /tmp/c5 "http://127.0.0.1:8000/api/v1/recommendations/home?limit=5"
curl -s -b /tmp/c5 "http://127.0.0.1:8000/api/v1/recommendations/books/1/similar?limit=5"
# repeat against a second instance started with RECOMMENDATION_PROVIDER=popularity
```

Result: all green — see the acceptance checklist above for the exact counts
and coverage this run produced. Live smoke test confirmed correct behavior
under both `mock` and `popularity` provider configurations, including that
the popularity-provider response's `model_version` matched the artifact
`build-popularity` had just produced and its top-ranked books were
plausible (classics with large, consistently-high rating support).

## 5e. Phase 6 validation commands and results

```bash
# Generated API client (backend must be import-able, no live DB required)
cd apps/api
uv run python -m book_app.cli.export_openapi     # writes apps/web/openapi.json
cd ../../apps/web
npm run generate-api-client                      # writes src/api/generated/schema.d.ts
# or: make generate-api-client, from the repo root

# Frontend lint/types/tests/build
npm run lint
npx tsc -b --force
npm run test          # 15 passed (7 files)
npm run build          # tsc -b && vite build — succeeds, ~368 KB JS / 15 KB CSS pre-gzip

# Backend unaffected this phase — re-verified anyway
cd ../../apps/api
uv run ruff format --check . && uv run ruff check . && uv run mypy .
uv run pytest -q
cd ../../packages/recommender && uv run ruff format --check . && uv run ruff check . && uv run mypy . && uv run pytest -q

# Live smoke test — no interactive browser tool available in this
# environment (see risk #44), so this drives the real HTTP contract
# apps/web/src/api/client.ts is written against, with a cookie jar standing
# in for the browser's cookie store
make db-start
cd apps/api && uv run uvicorn book_app.main:app --port 8000 &     # real Postgres :5434
cd ../apps/web && npm run dev &                                  # :5173, CORS-allowed origin
curl -sf http://localhost:5173/ >/dev/null                        # index.html serves
curl -sf http://localhost:8000/api/v1/health/ready                # {"status":"ok","database":"ok"}

curl -sc /tmp/c6 -X POST http://localhost:8000/api/v1/auth/register \
  -H "Origin: http://localhost:5173" -H "Content-Type: application/json" \
  -d '{"username":"smoketest_kubo","password":"correct horse battery staple","password_confirmation":"correct horse battery staple"}'
# 201, no Set-Cookie — register alone does not start a session (AuthProvider's
# register() is a pure pass-through, confirmed against real backend behavior)

curl -sc /tmp/c6 -X POST http://localhost:8000/api/v1/auth/login \
  -H "Origin: http://localhost:5173" -H "Content-Type: application/json" \
  -d '{"username":"smoketest_kubo","password":"correct horse battery staple"}'
# 200, Set-Cookie: access_token (HttpOnly, 900s), refresh_token (HttpOnly,
# path=/api/v1/auth, 2592000s), csrf_token (readable, 2592000s)

curl -s -b /tmp/c6 http://localhost:8000/api/v1/auth/me            # 200, user
curl -si -b /tmp/c6 -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Origin: http://localhost:5173"                                # 403 (no X-CSRF-Token)
CSRF=$(grep csrf_token /tmp/c6 | awk '{print $NF}')
curl -si -b /tmp/c6 -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Origin: http://localhost:5173" -H "X-CSRF-Token: $CSRF"       # 204, clears all 3 cookies
curl -si -b /tmp/c6 http://localhost:8000/api/v1/auth/me            # 401
```

Result: all green. Frontend: 15/15 tests, lint clean, typecheck clean,
production build succeeds. Backend: unchanged and re-verified green (247
tests, same as Phase 5). Live smoke test confirmed the full
register → login → me → logout → me cycle behaves exactly as
`apps/web/src/api/client.ts` and `api/auth.ts` assume, including CSRF
enforcement and cookie flags; backend access logs stayed structured JSON
throughout, no stack traces or secrets. **Not verified**: actual DOM
rendering, click-through navigation, or visual appearance — no interactive
browser tool is available in this environment (risk #44). Both dev servers
were left running after this pass so the user can drive the real UI in a
browser directly.

## 5f. Phase 7 validation commands and results

```bash
# Backend: new covers route + its live-smoke-test-only path-resolution bug
cd apps/api
uv run ruff format --check . && uv run ruff check . && uv run mypy .
uv run pytest tests/test_covers.py -v                 # 7 passed
uv run pytest tests ../../tests/integration --cov=book_app --cov-report=term-missing -q   # 218 passed, 94%
cd ../../packages/recommender && uv run ruff format --check . && uv run ruff check . && uv run mypy . && uv run pytest -q   # 38 passed, unaffected

# Frontend: new deps, all new components/hooks/routes
cd ../../apps/web
npm install @radix-ui/react-dialog @radix-ui/react-alert-dialog @radix-ui/react-popover --legacy-peer-deps
ls node_modules/@testing-library/       # verify --legacy-peer-deps didn't repeat Phase 6's regression
npx tsc -b --force
npm run lint
npm run test        # 37 passed (12 files, was 15/7 after Phase 6)
npm run build

# Regenerate the API client against the updated backend schema (new /covers path)
cd ../api && uv run python -m book_app.cli.export_openapi
cd ../web && npm run generate-api-client

# Live smoke test — real dev database, exact `make dev-api` launch convention
# (this is what caught the cover-path bug: identical fixture-based unit
# tests above passed cleanly first, since tmp_path is always absolute)
cd ../api && uv run uvicorn book_app.main:app --port 8000 &     # cwd = apps/api, matching make dev-api
cd ../web && npm run dev &

curl -sc /tmp/c7 -X POST http://localhost:8000/api/v1/auth/register -H "Content-Type: application/json" \
  -d '{"username":"phase7smoke","password":"correct horse battery staple","password_confirmation":"correct horse battery staple"}'
curl -sc /tmp/c7 -b /tmp/c7 -X POST http://localhost:8000/api/v1/auth/login -H "Content-Type: application/json" \
  -d '{"username":"phase7smoke","password":"correct horse battery staple"}'
CSRF=$(grep csrf_token /tmp/c7 | awk '{print $NF}')

curl -s -b /tmp/c7 "http://localhost:8000/api/v1/recommendations/home?limit=3"     # real books, real cover_object_keys
curl -so /tmp/cover.jpg -w "%{http_code} %{content_type}\n" \
  http://localhost:8000/api/v1/covers/<a cover_object_key from the response above>  # first attempt: 404 (the bug)
                                                                                     # after the fix: 200 image/jpeg
curl -s -b /tmp/c7 -X PUT http://localhost:8000/api/v1/books/1/rating -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" -d '{"rating": 4.5}'
curl -s -b /tmp/c7 http://localhost:8000/api/v1/books/1                            # user_state.rating reflects it
SHELF_ID=$(curl -s -b /tmp/c7 -X POST http://localhost:8000/api/v1/shelves -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" -d '{"name":"Phase 7 Smoke Shelf"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
curl -s -b /tmp/c7 -X PUT "http://localhost:8000/api/v1/books/2/shelves" -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" -d "{\"shelf_ids\": [\"$SHELF_ID\"]}"
curl -s -b /tmp/c7 "http://localhost:8000/api/v1/recommendations/books/1/similar?limit=3"
```

Result: all green after the covers-path fix. Frontend: 37/37 tests, lint
clean, typecheck clean, production build succeeds (~403 KB JS / 20 KB CSS
pre-gzip). Backend: 218/218 tests (94% coverage, up from 211 — the 7 new
`core/covers.py` tests), recommender unaffected at 38/38. Live smoke test
walked the full register → login → home feed (real books/covers) → rate →
detail reflects it → create shelf → sync a book onto it → similar books →
cover-bytes-for-a-real-key cycle against the real 92,524-book dev database,
**catching the cover path-resolution bug** in the process — the exact kind
of gap unit tests with always-absolute `tmp_path` fixtures structurally
cannot catch, and precisely why CLAUDE.md requires live validation, not
just green test suites. Server logs stayed clean (structured JSON, no
stack traces) throughout. As in Phase 6, no interactive browser tool is
available in this environment (risk #44) — both dev servers were left
running afterward for manual verification.

## 5g. Phase 8 validation commands and results

```bash
# Backend: new search module
cd apps/api
uv run ruff format --check . && uv run ruff check . && uv run mypy .
uv run pytest tests/test_search.py -v                                     # 2 passed
uv run pytest ../../tests/integration/test_search.py -v                    # 10 passed
uv run pytest tests ../../tests/integration --cov=book_app --cov-report=term-missing -q   # 230 passed, 95%
cd ../../packages/recommender && uv run ruff format --check . && uv run ruff check . && uv run mypy . && uv run pytest -q   # 38 passed, unaffected

# tests/integration/ lint via the exact repo-root invocation `make lint` uses
cd ../..
uv run --project apps/api ruff format tests && uv run --project apps/api ruff check tests

# Frontend: shelves/rated/search pages, generalized BookCard, new module
cd apps/web
npx tsc -b --force
npm run lint
npm run test        # 58 passed (17 files, was 37/12 after Phase 7)
npm run build

# Regenerate the API client against the updated backend schema (new /search path)
cd ../api && uv run python -m book_app.cli.export_openapi
cd ../web && npm run generate-api-client

# Live smoke test — real dev database, exact `make dev-api` launch convention
cd ../api && uv run uvicorn book_app.main:app --port 8000 &
cd ../web && npm run dev &

curl -sc /tmp/c8 -X POST http://localhost:8000/api/v1/auth/register -H "Content-Type: application/json" \
  -d '{"username":"phase8smoke","password":"correct horse battery staple","password_confirmation":"correct horse battery staple"}'
curl -sc /tmp/c8 -b /tmp/c8 -X POST http://localhost:8000/api/v1/auth/login -H "Content-Type: application/json" \
  -d '{"username":"phase8smoke","password":"correct horse battery staple"}'
CSRF=$(grep csrf_token /tmp/c8 | awk '{print $NF}')

curl -s -b /tmp/c8 "http://localhost:8000/api/v1/search/books?q=Dune&limit=3"              # exact match ranks first
curl -s -b /tmp/c8 "http://localhost:8000/api/v1/search/books?q=Frank%20Herbert&limit=3"    # title-tier outranks author-tier

SHELF_ID=$(curl -s -b /tmp/c8 -X POST http://localhost:8000/api/v1/shelves -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" -d '{"name":"Phase 8 Smoke Shelf"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
curl -s -b /tmp/c8 -X PATCH "http://localhost:8000/api/v1/shelves/$SHELF_ID" -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" -d '{"name":"Renamed Shelf"}'
curl -s -b /tmp/c8 -X PUT "http://localhost:8000/api/v1/shelves/$SHELF_ID/books/58203" -H "X-CSRF-Token: $CSRF"
curl -s -b /tmp/c8 "http://localhost:8000/api/v1/shelves/$SHELF_ID/books"
curl -s -b /tmp/c8 "http://localhost:8000/api/v1/recommendations/shelves/$SHELF_ID?limit=2"
curl -s -b /tmp/c8 -X PUT http://localhost:8000/api/v1/books/1/rating -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" -d '{"rating": 5.0}'
curl -s -b /tmp/c8 "http://localhost:8000/api/v1/me/ratings?sort=highest&limit=3"
curl -s -b /tmp/c8 -X DELETE "http://localhost:8000/api/v1/shelves/$SHELF_ID" -H "X-CSRF-Token: $CSRF"
```

Result: all green. Frontend: 58/58 tests, lint clean, typecheck clean,
production build succeeds (~423 KB JS / 22 KB CSS pre-gzip). Backend:
230/230 tests (95% coverage, up from 218/94% — the 12 new search tests),
recommender unaffected at 38/38. Live smoke test confirmed the full search
-ranking behavior against real data (exact-title-beats-popular-sequel,
title-tier-beats-author-tier — both exactly as ADR-0012 designed, not
just "returns something") and the complete shelf lifecycle
(create→rename→add-book→list→discover→delete) plus rating sort. Server
logs stayed clean throughout. As in Phases 6-7, no interactive browser
tool is available in this environment (risk #44) — both dev servers were
left running afterward for manual verification.

## 5h. Phase 9 validation commands and results

```bash
# Backend: security headers, general rate limit/request-size, seed-demo,
# the get_request_settings fix
cd apps/api
uv run ruff format --check . && uv run ruff check . && uv run mypy .
uv run pytest tests ../../tests/integration --cov=book_app --cov-report=term-missing -q   # 241 passed, 94%

cd ../../packages/recommender && uv run ruff format --check . && uv run ruff check . && uv run mypy . && uv run pytest -q   # 38 passed, unaffected

# tests/integration/ lint via the exact repo-root invocation `make lint` uses
cd ../..
uv run --project apps/api ruff format --check tests && uv run --project apps/api ruff check tests

# Frontend: error boundaries, toasts, session-expiry, Playwright + e2e/
cd apps/web
npx tsc -b --force        # now also covers playwright.config.ts + e2e/ via tsconfig.e2e.json
npm run lint
npm run test               # 69 passed (20 files, was 58/17 after Phase 8)
npm run build

# Playwright's Chromium was already present from an earlier install this
# phase (npx playwright install --with-deps chromium); re-verified current:
npx playwright install chromium

# The E2E critical-flow test itself — requires the API already running
# (make dev-api) against a migrated, catalog-populated Postgres
# (make db-start && make migrate && make import-data, already done in
# earlier phases in this environment's persistent dev database)
make e2e                   # == cd apps/web && npx playwright test
# 1 passed — register, login, browse, open, rate, verify Rated, create
# shelf, save to multiple shelves, open shelf Discover, reject another
# book, logout, login, verify persistence, 2 axe scans. Run 4 consecutive
# times (3x directly + 1x via `make e2e`) with no flakes after fixing the
# two useBookState.ts race conditions documented in Phase 9 above — both
# were caught by early, flaky-looking failures on the *first* two runs,
# not by design.
```

Result: all green. Backend: 241/241 combined (94% coverage — spec §13.6's
75% floor), recommender unaffected at 38/38. Frontend: 69/69 tests
(12 more than Phase 8's 58 — toast store, toast viewport, error
fallbacks), lint clean, typecheck clean (now genuinely covering the new
`e2e/` directory, not silently skipping it), production build succeeds.
E2E: the full spec §13.5 critical flow passes end to end against a real
Chromium browser, a real FastAPI process, and real PostgreSQL — the first
time in this project any surface has been driven by actual browser
automation rather than jsdom or curl. Two real bugs were found and fixed
along the way (both documented in Phase 9 above and in `useBookState.ts`
itself): `useSyncShelvesMutation`'s stale-response clobber, and
`optimisticallyPatch`'s unnecessary `await` opening a controlled
-component flicker/race window. Neither was a test artifact — both are
realistic sequences (quickly checking two shelf checkboxes; any fast
click) a real user can trigger, and both are now fixed in the app itself,
not routed around in the test.

Not verified this phase: the production Docker images were not actually
built or run (Docker still unavailable in this environment, risk #1/#65).
CI's new `e2e` job (fresh Postgres, sample-data import, Playwright against
a real backend) was authored and is believed correct by inspection and by
running the equivalent steps manually in this environment, but GitHub
Actions itself was not invoked from here to confirm it goes green — that
will only be known once this branch's CI actually runs.

## 5i. Recommender Phase R0 validation commands and results

```bash
# Baseline, run BEFORE any edit, to establish what was already broken.
make test
# apps/api: 2 failed, 125 passed
#   FAILED tests/test_artifact_paths.py::test_repo_root_actually_contains_the_app_specification
#   FAILED tests/test_covers.py::test_repo_root_actually_contains_the_app_specification
# Both caused solely by APP_SPECIFICATION.md being relocated out of the
# repository root — the sentinel file, not the path logic, was what moved.
# `make test` stops at the first failing suite, so packages/recommender and
# apps/web were not reached on this run.

make lint        # clean: apps/api, packages/recommender, tests/, apps/web
make typecheck   # clean: 115 + 26 source files, apps/web tsc -b --force

# The fix (the only code change in R0), verified in isolation first:
cd apps/api && uv run pytest tests/test_artifact_paths.py tests/test_covers.py -q
# 10 passed

# Full re-run after all R0 edits:
make test
# apps/api        127 passed
# packages/recommender  38 passed
# apps/web        73 passed (21 files)
make lint        # clean: apps/api, packages/recommender, tests/, apps/web
make typecheck   # clean: 115 + 26 source files, apps/web tsc -b --force
```

Result after R0: `make test` green across all three suites — 127 apps/api
unit (the same 125 as the baseline plus the 2 that were failing on arrival),
38 recommender, 73 frontend. `make lint` and `make typecheck` clean.
Integration tests and e2e were **not** run this phase — R0 changes no
schema, no query, no route, no OpenAPI surface and no frontend code, so
neither suite has anything new to exercise; both remain as last verified in
§5h. No migration was created and `make generate-api-client` was not run,
for the same reason.

## 5j. Recommender Phase R1 validation commands and results

```bash
# Migration: the only schema change this phase. Autogenerated, then
# hand-edited to strip the three phantom index drops (see the migration's
# own docstring), then round-tripped against the real dev database.
cd apps/api && uv run alembic upgrade head
                 uv run alembic downgrade -1
                 uv run alembic upgrade head
# Confirmed the hand-written search indexes survived the round trip:
psql -c "select indexname from pg_indexes where tablename='books'"
#   ix_books_description_fts, ix_books_primary_author_name_trgm,
#   ix_books_title_trgm all still present.

make generate-api-client        # 24 paths exported (was 20)

make test
# apps/api        127 passed
# packages/recommender  38 passed  (untouched this phase)
# apps/web         93 passed (25 files) — was 73/21
make lint                       # clean, all four targets
make typecheck                  # clean: 118 + 26 source files, apps/web
uv run --project apps/api pytest tests/integration -q
#                140 passed     — was 114
```

**Proving the impression regression test actually catches the bug.** Before
trusting it, `create_impressions` was temporarily reverted to its pre-R1
`add_all` form and the test re-run:

```text
FAILED tests/integration/test_recommendations.py::
       test_refetching_the_same_cursor_page_is_idempotent
```

The fix was then restored and the suite re-run green. A regression test
that has never been seen to fail is an assumption, not a test.

**Live smoke test** against the real dev database (92,524 books), driving
the exact HTTP contract the frontend is written against:

```text
GET  /recommendations/home?limit=3            -> 200, request_id + ranks
GET  .../home?limit=3&cursor=<same cursor> x3 -> 200, 200, 200
       (pre-R1 this was 200, 500, 500)
POST /books/{id}/opened      (home attribution)     -> 204
POST /search/queries         ("dune")               -> 201 + id
GET  /search/books?q=dun     (suggestions)          -> 200
PUT  /books/{id}/rating      (home attribution)     -> 200
PUT  /books/{id}/shelves     (search attribution)   -> 200
POST /books/{id}/opened      (search attribution)   -> 204
```

Then verified in PostgreSQL directly, which is the assertion that matters:

- 5 events written with the right provenance — `book_opened` (home,
  session, request, rank 0), `search_submitted` (null `book_id`, carries
  `search_query_id`), `rating_set` (home, session, request, rank),
  `shelf_book_added` (search, session, `search_query_id`), `book_opened`
  (search, `search_query_id`);
- exactly **one** `search_queries` row — the suggestions `GET` recorded
  nothing, which is rec-spec §4.4's load-bearing rule;
- `shelf_books.source_surface = 'search'`, the first non-null value that
  column has ever held;
- `recommendation_impressions`: exactly 1 row per book after 3 refetches
  of the same cursor page.

Server logs stayed clean throughout: status codes `{200: 10, 201: 3,
204: 2}`, no error-level entries, no tracebacks.

**E2E** (`make e2e`, real Chromium, real API, real PostgreSQL): the spec
§13.5 critical flow passed, run 3 consecutive times with no flakes — worth
running here specifically because R1 adds a fire-and-forget POST to every
card click, and Phase 9 found two genuine races in exactly this code path.
Both axe scans still gate clean; the one moderate `page-has-heading-one`
finding is unchanged and pre-existing (risk #67).

Afterwards, the events the *real browser* produced were inspected: all 8
`book_opened` rows carry a surface and session, 7 of them a recommendation
request id, and 7 `shelf_book_added` rows carry full attribution —
confirming the chain works end to end in a browser, not only in jsdom.

## 5k. Recommender Phase R2 validation commands and results

```bash
# Migration: the only schema change this phase, hand-edited after
# autogenerate to strip the same three phantom index drops.
cd apps/api && uv run alembic upgrade head
                 uv run alembic downgrade -1
                 uv run alembic upgrade head
# Confirmed all 3 hand-written search indexes survived: count = 3.

make generate-api-client        # +2 paths, +4 schema types (TasteSeed*)

make test
# apps/api        143 passed   (was 127 — +16 profile-version unit tests)
# packages/recommender  38 passed
# apps/web         93 passed   (unchanged — no frontend work this phase)
make lint                       # clean, all four targets
make typecheck                  # clean: 119 + 26 source files, apps/web
uv run --project apps/api pytest tests/integration -q
#                161 passed    (was 140 — +21 context/taste-seed tests)
```

**Live smoke test** against the real dev database (92,524 books), seeding
two genuinely-real books (Dune, Hyperion) and saving one to two shelves:

```text
PUT /me/taste-seeds  [Dune, Hyperion]  -> 200, both returned with covers
GET /me/ratings                        -> 0 items   (seeds are not ratings)
PUT /books/{dune}/shelves [A, B]       -> 200
```

Then the built context was inspected directly through `context_builder` —
the same code path the recommendation service uses:

```text
saved_book_ids : [58203]                       collapsed, eligibility
saved_books    : [(58203, shelf 7440f0f8, ...),
                  (58203, shelf c00776c3, ...)]  per-shelf, with added_at
taste_seeds    : [(14305, onboarding), (58203, onboarding)]
ratings        : ()                            seeds imply no rating
recent events  : shelf_book_added/search x2, taste_seed_added x2
stable across sessions: True
```

And `profile_version` invalidation, exercised through real HTTP calls:

| Action | Version |
|---|---|
| baseline | `v1:62eeace4a5cff481` |
| `GET /recommendations/home` (impressions written) | unchanged |
| `POST /books/{id}/opened` | unchanged |
| `PUT /books/{id}/rating` | **changed** → `v1:72e08c2366d3bfe6` |

That table is the phase's central claim, verified end to end rather than
only in unit tests. Server logs clean throughout: `{200: 9, 201: 3,
204: 1}`, no error-level entries, no tracebacks.

E2E was **not** re-run this phase: R2 changes no route the critical flow
exercises and no frontend code at all (the onboarding UI is R8 scope), so
it has nothing new to cover. Last verified green in §5j.

## 5l. Recommender Phase R3 validation commands and results

```bash
# Dependency resolution — risk #81's open unknown, probed BEFORE committing
# anything to a manifest, resolution-only (metadata, no wheel downloads):
uv pip compile --python-version 3.12 <probe: numpy scipy scikit-learn \
                                            implicit sentence-transformers>
# Resolved in 1.2s on darwin/arm64, uv 0.10.4. See §6 risk #81 for versions.

# What R3 actually added (NumPy only) — the lock already carried it via
# pandas/pyarrow, so nothing new entered the resolution:
uv sync --all-packages          # Resolved 60 packages in 1.30s

make test
# apps/api             145 passed   (was 143 — +2 dependency-boundary)
# packages/recommender 111 passed   (was  38 — +73 artifact substrate)
# apps/web              93 passed   (unchanged — no frontend work)
make lint                        # clean, all four targets
make typecheck                   # clean: 125 + 37 source files, apps/web
uv run --project apps/api pytest tests/integration -q
#                      181 passed  (was 161 — +20 builder/wiring tests)

# tests/integration/ formatting via the exact repo-root invocation make lint
# uses (88-char default, not apps/api's 100 — risk #35):
uv run --project apps/api ruff format tests
```

No migration (no schema change), no `make generate-api-client` (no OpenAPI
change), no e2e (no route and no frontend code touched — last green §5j).

**Regression verified against unfixed code**, per the working method used
since Phase 3. The phase's central claim is that artifacts resolve through
`work_id`, not the stored `book_id`:

```bash
# Sabotage: make resolve_item_mapping return the build-time book_id.
uv run --project apps/api pytest tests/integration/test_recommendation_wiring.py
# 1 failed, 6 passed
#   test_a_reimport_that_reassigns_book_ids_still_serves_the_right_books
# Fix restored:
# 7 passed
```

**Live smoke test** against the real dev database (92,524 active books).

First, degradation, *before* rebuilding anything — the pre-R3 8.9 MB v1
artifact was still on disk:

```text
warning  popularity_artifact_unavailable
         error="unreadable manifest at 'popularity/latest': 2 validation
         errors for ArtifactManifest — preprocessing_version Field required;
         files.0 Input should be an object"
provider built in 0.40s -> InProcessProvider, ranking size 0
```

No crash, no startup failure, and the log names the fix. Then the rebuild:

```bash
make build-recommender-artifacts        # 2.9s wall, all three families
```

```text
popularity:        92524 items
source_similarity: 92524 items
    edges_exported 269276   edges_in_database 269276
    dropped_out_of_catalog 0   dropped_self_edges 0
    books_with_neighbors 54552   sources goodreads
item_metadata:     92524 items
    distinct_genres 10   items_without_genre 3098   items_without_author 2322
    tags_version: unset (R5)
```

rec-spec §14 asks the build to re-validate the import's resolution invariant
rather than assume it. It holds exactly: every one of the 269,276 edges
resolves to an active catalog book.

Artifacts on disk and the rows they registered — asserted on persisted
state, not on exit codes:

```text
data/artifacts/popularity/latest/         manifest 4K  mapping 680K  scores 320K
data/artifacts/source_similarity/latest/  manifest 4K  mapping 504K  graph  912K
data/artifacts/item_metadata/latest/      manifest 4K  mapping 504K  items  2.1M

model_name        | model_version    | status  | manifest_bytes
------------------+------------------+---------+----------------
item_metadata     | 20260813T114431Z | ACTIVE  |            755
source_similarity | 20260813T114430Z | ACTIVE  |            793
popularity        | 20260813T114630Z | ACTIVE  |            711
popularity        | 20260805T093634Z | RETIRED |        1555987   <- v1
```

Loading all three through the real loaders against the real catalog:

```text
catalog snapshot   0.14s   92524 works
popularity         0.28s   ok  resolved=92524  unresolved=0  reassigned=0
source_similarity  0.46s   ok  resolved=92524
item_metadata      1.07s   ok  resolved=92524
all three loaded:  77 MB resident, 89 MB peak
checksum verify (item_metadata, 2.6 MB): 0.003s
neighbours(#1) in 37us, joined against item metadata:
  #11339 rank=4 goodreads 'Home: A Short History of an Idea' — Witold Rybczynski
  #59534 rank=5 goodreads 'Love Bites (Argeneau #2)' — Lynsay Sands
  #42290 rank=7 goodreads 'Not So Big House' — Sarah Susanka
  seed #1 'A Field Guide to American Houses' — Virginia McAlester [non-fiction]
```

(The romance novel among the architecture books is Goodreads' own noise, not
an export bug — rec-spec §14 says export what the source says and keep the
generator semantically pure. Worth knowing before R6 weights this source.)

Finally the whole chain through real HTTP, `RECOMMENDATION_PROVIDER=popularity`:

```text
POST /auth/register -> 201
POST /auth/login    -> 200
GET  /recommendations/home?limit=10 -> 200

startup log: popularity_artifact_loaded status=ok item_count=92524
             resolved_count=92524 unresolved_count=0 reassigned_count=0
             model_version=20260813T114630Z

rank 0 #3123  'Toda Mafalda'                          POPULAR_WITH_READERS
rank 1 #43447 "It's a Magical World: A Calvin and…"   POPULAR_WITH_READERS
rank 2 #24343 "There's Treasure Everywhere: A Calvin…" POPULAR_WITH_READERS
```

Identical to the builder's own top-of-ranking preview, which is the point:
PostgreSQL → builder → `mapping.npz`/`scores.npz` → recommender-package
loader → `wiring.py` (which no longer knows either format) → engine → HTTP,
with order preserved end to end. Persisted rows for that request:

```text
model_name | model_version    | surface | results | impressions
-----------+------------------+---------+---------+------------
popularity | 20260813T114630Z | home    |     600 |          10

position | book_id | reason_code            <- matches the served order
       0 |    3123 | POPULAR_WITH_READERS
       1 |   43447 | POPULAR_WITH_READERS
```

`model_version` on the persisted request matches the ACTIVE `model_versions`
row, so the batch is attributable to the exact artifact that produced it.
Server logs clean: `{200: 3, 201: 1}` plus the 422/401 from two deliberately
malformed probe requests, no error-level entries, no tracebacks.

## 5m. Recommender Phase R4 validation commands and results

```bash
# The training dependency group, and the proof that it is actually separate:
make setup-training          # + implicit 0.7.3, scipy 1.18.0, threadpoolctl,
                             #   tqdm — 4.4s, wheels, no source builds
uv sync --all-packages       # prunes all four back out again
python -c "import implicit"  # ImportError -> the API env is genuinely clean
uv run --group training ...  # rehydrates in 15ms for the builders

# Default environment (training group NOT installed) — the normal gate:
make test
# apps/api             185 passed, 1 skipped   (was 145)
#     the skip is test_cf_training.py's 16 tests, skipped as one module by
#     importorskip because implicit/scipy are absent — which is the point
# packages/recommender  143 passed             (was 111 — +32 ALS/item-CF)
# apps/web               93 passed             (unchanged — no frontend work)
make lint                    # clean, all four targets
make typecheck               # clean: 133 + 41 source files, apps/web
#   typechecks WITHOUT the training group installed, by design — mypy
#   overrides treat implicit/scipy as untyped (ADR-0021)
uv run --project apps/api pytest tests/integration -q
#                      181 passed, 1 skipped   (was 181 + 0)

# With the training group, the skipped suites actually run:
uv run --project apps/api --group training pytest -q          # 201 passed
uv run --project apps/api --group training pytest tests/integration -q
#                      192 passed
```

**The real training runs**, against the full 775,090-row dataset and the
92,524-book catalog:

```bash
make build-als        # 5-config sweep + full retrain — ~4 min
make build-item-cf    # 2-variant sweep + full rebuild — 31s
```

```text
als: 92524 items          item_cf: 92524 items
  rows_total  775090        edges              7,606,357
  rows_used   707297        items_with_neighbors  87,355
  dropped: unresolved 5, ratings 1-5 43,593, rating 6 24,195
  users 83,200 -> 76,369 used, 15,747 evaluated
  selected f128-r0.05-i20   selected bm25-k100
  ndcg@50 0.0633            ndcg@50 0.0258, coverage 0.547, gini 0.374
```

Counts reconcile exactly: 707,297 + 5 + 43,593 + 24,195 = 775,090.

**Both models load and serve sensibly**, verified against the real catalog
by folding in a reader whose only evidence is *Dune*:

```text
als      0.67s   92,524 items x 128 factors     status=ok
item_cf  0.88s   92,524 items, 7,606,357 edges  bm25, k=100
fold-in + scoring all 92k items: 6ms

ALS candidates                        item-CF candidates
  0.073 The Silence of the Lambs        0.189 Children of Dune
  0.069 Children of Dune                0.132 Dune Messiah
  0.068 Dune Messiah                    0.119 TekVengeance (TekWar #4)
  0.064 Ender's Game                    0.117 The Watch
  0.059 Timeline                        0.114 Midnight at the Well of Souls
  0.057 The Hobbit                      0.114 Already Dead
  0.055 God Emperor of Dune             0.105 Soldat (German soldier memoir)
```

Both surface the Dune sequels from a single Dune seed. ALS stays inside
recognisable science fiction and fantasy; item-CF is sharper at the top and
noisier below it — which is the accuracy-versus-coverage split the metrics
already predicted, visible in actual titles.

**No serving behavior changed.** `wiring.py` contains zero references to
either loader (`grep -c` = 0); the popularity artifact is still the only one
loaded at startup, and `FuturePipelineRecommendationEngine` is still the
unused plug point. Candidate generators are R6, pipeline integration is R8.

```text
data/artifacts/  (88 MB total, was 6.7 MB)
  als/latest/          item_factors.npy 45M  mapping.npz 564K  manifest 4K
  item_cf/latest/      neighbors.npz    36M  mapping.npz 564K  manifest 4K
  evaluation/          als-*.json/.txt, item_cf-*.json/.txt

model_versions: all five families ACTIVE, manifests 711-832 bytes each
```

E2E was **not** re-run: R4 changes no route, no schema and no frontend code.
Last verified green in §5j.

## 6. Risks and assumptions

Recorded per CLAUDE.md: "For a genuinely unspecified detail, choose a
conservative, reversible default and document it."

1. **Docker is not installed in this environment.** `docker-compose.yml` and
   both Dockerfiles are written to spec but have not been executed. Mitigation:
   validated Docker Compose YAML by parsing it (`yaml.safe_load`), and
   validated the actual application by running it natively against a
   project-local PostgreSQL cluster instead. Risk: a Docker-specific problem
   (build context, base image availability, volume mount syntax) would not be
   caught until Docker is available. Reversible — no application code depends
   on Docker being present.
2. **One `books.parquet` row has an empty-string `work_id`.** Decision:
   Phase 2's import adapter will reject and report this row rather than
   upsert a book with an empty key. Documented in `data/README.md`.
3. **Home-directory git quirk.** `$HOME` is an unrelated, empty, zero-commit
   git repository (pre-existing, not created by this project). This project's
   own `.git` lives at `/Users/jakubhajko/Projects/bookshelf/.git`, matching
   the pattern already used by this user's other local projects. Nothing
   about the outer repo was modified.
4. **JWT implementation.** Spec §3.2 asks for "a focused JWT implementation,"
   not a specific library. Decision: use a small, well-vetted library
   (`pyjwt`) narrowly — only access-token encode/verify, no OAuth/OIDC
   surface — rather than hand-rolling token signing or pulling in a full auth
   framework. This is a Phase 3 decision recorded here now so it isn't
   revisited implicitly later; not implemented yet.
5. **Structured logging library.** Spec requires structured JSON stdout logs
   but doesn't name a library. Decision: `structlog`, configured to emit JSON
   in all environments (not just production) for consistency. Reversible —
   isolated to `core/logging.py`.
6. **Health endpoint path.** Spec §9.7 lists `/health/live` and
   `/health/ready` as a subsection of "§9 API contract," whose stated base is
   `/api/v1`. Decision: mount both under `/api/v1/health/...` per that literal
   reading. Risk: AWS ALB target-group health checks conventionally prefer an
   unversioned, stable path. Reversible — adding a bare `/health/*` alias
   later is a few lines whenever real ALB wiring happens (not before, per
   "no unused abstractions").
7. **Cover/artifact storage paths.** Local storage backend defaults point at
   `data/processed/covers` and a new empty `data/artifacts/` (created this
   pass, gitignored, mounted read-only in Compose for the future popularity
   provider artifact). Both are environment-configurable, never hardcoded in
   application code, per spec §14/CLAUDE.md.
8. **Coverage floor.** Spec §13.6 sets a 75% backend/recommender coverage
   floor. Phase 1 has almost no business logic (config validation + health
   checks), so the floor is not a meaningful gate yet; it starts being
   enforced in CI from Phase 2 onward once there's real logic to cover. Not
   enforced as a hard CI failure this phase to avoid a false sense of
   coverage from trivial code.
9. **Makefile targets for unimplemented phases** print which phase adds them
   and exit 0 instead of failing, so `make test`/CI scripts calling several
   targets in sequence don't break on a target that legitimately doesn't
   exist yet. This is itself removed target-by-target as each phase lands.
10. **pgvector not installed.** Spec marks it optional. Not required until a
    phase that actually does vector search (later than Phase 4). Documented
    so it isn't a surprise when that phase starts.
11. **Node v26 / npm 11 are very recent versions.** `apps/web/package.json`
    engines field is set to a conservative lower bound rather than pinned to
    exactly what's installed, so the project doesn't artificially break on
    slightly older-but-still-current toolchains.
12. **A second real data-quality issue**, found only by running the import
    against the *full* dataset (the 301-row sample didn't happen to contain
    it): row 41150 (`work_id='2440582'`) has a title that is empty/whitespace
    after stripping — not caught by a null check, only by validating the
    stripped string is non-empty. The adapter already rejects on this (same
    code path as the empty-`work_id` row); documented here because it wasn't
    known until Phase 2 actually ran end-to-end, unlike the `work_id` issue
    which Phase 0's inspection already found. Both rejected rows are reported
    by `import_catalog`'s `--report`, not silently dropped.
13. **`similar_books` resolves against two different ID spaces**, not one —
    real data showed source references matching both this dataset's
    `work_id` and `book_id` conventions (verified: 1,071 vs 8,029 matches in
    a 3,000-row sample), with ~66% matching neither (pointing outside the
    92,526-row catalog). The repository tries both spaces per reference and
    drops what resolves to neither, rather than assuming one convention and
    silently under-resolving. See `import_adapter.py`'s module docstring.
14. **A book can credit the same author (or, rarely, shelf tag) twice** —
    229 and 36 books respectively out of 92,526 have this in the real data.
    `book_authors`/`book_genres`/`book_catalog_shelf_tags` all have a
    composite `(book_id, *_id)` primary key (spec §8.4 doesn't state one
    explicitly), so a naive pass would hit a unique-constraint violation on
    import. Fixed by keeping only the first (lowest-position, most
    prominent) listing per pair — found by running the importer against real
    data, not anticipated in advance.
15. **pandas nullable-dtype columns use `pd.NA`, not float `NaN`.**
    `ratings_count`/`text_reviews_count`/`num_pages`/`publication_year` are
    pandas `Int32` and `is_ebook` is nullable `boolean` — both represent
    missing values with `pd.NA`, which `isinstance(x, float) and
    math.isnan(x)` doesn't catch (`int(pd.NA)` raises `TypeError`). Fixed
    with `pd.isna()` for the scalar cleaners; the array-typed columns
    (authors, genres, `similar_books`, ...) never use `pd.NA` in this
    dataset, so `_clean_list` intentionally does *not* use the same check
    (`pd.isna()` on a multi-element array returns an array, not a bool, and
    would crash a naive `bool()` call on it).
16. **`metadata_quality` is adapter-computed, not sourced.** Spec §8.3
    declares the column but no source column exists for it. Decision: an
    equal-weight fraction of five completeness signals (has description,
    cover, primary author, genre, publication year), documented in
    `compute_metadata_quality()`'s docstring. Reversible — nothing downstream
    depends on the exact formula, only that higher means more complete.
17. **`tests/integration/` has no dedicated `mypy` gate.** It sits at the
    repo root, outside `apps/api`'s package tree, so `apps/api`'s `mypy .`
    doesn't see it and it has no `pyproject.toml`/`mypy_path` of its own.
    `ruff format`/`ruff check` **do** run against it (via `uv run --project
    apps/api ruff ... tests`, wired into `make lint` and CI) since ruff
    doesn't need a package context the way mypy's import resolution does.
    Adding a proper mypy configuration for this directory is a small,
    reversible follow-up if it starts to matter, not required now.
18. **Coverage floor, revisited.** Phase 1 noted the 75% floor (spec §13.6)
    wasn't meaningful yet. It's real now: 91% combined (`apps/api`'s unit
    suite + `tests/integration` together, see §5a) — but the fast `make
    test` suite alone reports ~35%, because the catalog import logic is
    exercised by the Postgres-dependent integration tests, not the unit
    tests. Read coverage from the combined run, not `make test` alone, when
    judging this floor from Phase 2 onward.
19. **`data/sample/covers/` ships placeholder files, not real cover images.**
    Caught before the first commit, when reviewing `git status` ahead of
    pushing to GitHub: the sample fixture generator originally copied real
    files from `data/processed/covers/` — copyrighted book covers scraped
    from Goodreads/Open Library. Fine to keep locally (gitignored), not fine
    to commit and redistribute via a git repo. Fixed in
    `scripts/data_import/build_sample_fixture.py` to write tiny placeholder
    text files under the real filenames instead — `test_local_covers.py`
    only checks file existence and safe path resolution, never image bytes,
    so this is equally good as a fixture. See `data/README.md`.
20. **`csrf_secret_key` (provisioned in Phase 1's `Settings`) was removed,
    not implemented.** Phase 1 anticipated an HMAC-derived CSRF design.
    Actually building CSRF in Phase 3 showed spec §8.2's `csrf_token_hash`
    *column* only makes sense for a random-token-hashed-at-rest design (an
    HMAC token is recomputed, never stored) — so the field was dead weight.
    Removed from `Settings`, `.env.example`, and the production-safety
    validator rather than implemented-to-match-the-field. A real example of
    "genuinely unspecified detail" resolving itself once actually built.
21. **`InvalidHashError` isn't an `Argon2Error` subclass** — it derives
    directly from `ValueError`. Assumed otherwise from `VerifyMismatchError`'s
    MRO without checking `InvalidHashError`'s separately; a unit test
    (`test_verify_password_rejects_garbage_hash_without_raising`) caught the
    gap before it could turn a corrupt stored hash into an unhandled 500 on
    login. `verify_password` now catches both explicitly.
22. **`get_current_user` originally didn't check session validity, only the
    JWT and account status** — meaning a logged-out user's still-cryptographically-valid
    access token would keep working on every authenticated GET route
    (`/auth/me`, and everything Phase 4+ adds) for up to its ~15-minute
    natural lifetime. Found by live-smoke-testing the actual logout flow
    with curl, not by unit testing (the bug was in what the dependency
    *didn't* check, which a test written against the original design
    wouldn't have caught either). Fixed by extracting a shared
    `get_current_session` dependency that both `get_current_user` and
    `require_csrf` depend on — revocation is now immediate, verified by
    `test_replayed_access_token_is_rejected_immediately_after_logout`.
23. **HTTP 422's status constant was renamed** (`HTTP_422_UNPROCESSABLE_ENTITY`
    → `HTTP_422_UNPROCESSABLE_CONTENT`) in the Starlette version this
    environment resolved — a `DeprecationWarning` surfaced by running the
    unit suite, fixed across all four usages (`core/exceptions.py` plus
    three auth/users exception classes). Same numeric status code (422),
    just the current constant name.
24. **Password rules are validated in `service.py`, not via Pydantic field
    constraints**, deliberately — see `service.py`'s and `schemas.py`'s
    module docstrings. A Pydantic `ValidationError`'s `.errors()` includes
    the raw submitted value for the failing field, and my shared error
    handler (`core/exceptions.py`) puts `.errors()` straight into the
    response's `details`. For a password field, that would echo the
    password back to the client on a length-validation failure — a direct
    violation of spec §6.3 ("never log or return"). Usernames don't have
    this problem (they aren't secret), so only password fields skip Pydantic
    constraints.
25. **Session revocation cascade on password change wasn't built.** Spec
    §6's Phase 3 bullet list is "cookies/refresh; CSRF; logout; session
    cleanup" — it doesn't ask for change-password to revoke a user's *other*
    active sessions, and I didn't add it unasked. Worth reconsidering later
    as a real hardening improvement (if a password was changed because it
    leaked, other sessions started with the leaked password should
    arguably die too) — flagged here rather than silently decided either way.
26. **Rate limiting is scoped to login (per IP+username) and register (per
    IP) only** — not refresh/logout/change-password, which all require an
    already-valid session and so have a much smaller brute-force surface.
    General, non-auth-specific API rate limiting is explicitly Phase 9
    scope (spec §18).
27. **`/me/ratings`'s `recent` sort had a real cursor bug, caught before any
    test ran.** Its keyset cursor stores `rated_at` as `.isoformat()` (JSON
    has no datetime type); the query side originally compared that string
    directly against the `updated_at` TIMESTAMPTZ column, relying on
    implicit driver-level coercion instead of parsing it back explicitly.
    Fixed with `datetime.fromisoformat(key_value)` before the comparison —
    then, since the bug would only ever surface on a *second* page of
    `recent`-sorted results, added a dedicated pagination test
    (`test_sort_recent_pagination_round_trips_the_datetime_cursor`) so a
    future refactor can't silently reintroduce it; the existing single-page
    `recent`-sort test would not have caught either the original bug or a
    regression.
28. **A hand-written raw-SQL query in `shelves/repository.get_shelf_summary`
    would have self-joined `books` to itself.** `select(Book.cover_object_key).join(Book, ...)`
    infers its FROM clause from the columns clause — since only a `Book`
    column was selected, SQLAlchemy would have joined `books` against
    itself instead of against `shelf_books`. Caught by inspection before
    running anything (by comparing against the working two-column form in
    `list_shelves_with_collage`), fixed with an explicit
    `.select_from(ShelfBook)`.
29. **Two integration tests initially called a URL that doesn't exist**:
    `PUT /books/{book_id}/shelves/{shelf_id}` instead of the real route,
    `PUT /shelves/{shelf_id}/books/{book_id}` (spec §9.3) — a copy-paste
    mix-up with the unrelated bulk-sync route, `PUT /books/{book_id}/shelves`.
    Both silently 404'd rather than testing what they claimed to; caught
    immediately because the very next assertion failed, not because the
    404 itself looked wrong. Serves as a reminder that a passing-looking
    integration test can still be exercising nothing — the assertions after
    the request are what actually prove it worked.
30. **The `insert_book` test fixture originally had no way to set
    `cover_object_key`**, so the integration test named
    `test_shelf_list_includes_collage_cover_data` never actually put a
    cover key into the database and only asserted on `book_count` — the one
    field the test's own name doesn't mention. Caught while adding a
    second, cap-related collage test and noticing the fixture couldn't
    support it either. Fixed the fixture and both tests now assert on
    `cover_object_keys` content, not just count.
31. **The `book_app_test` database round trip (downgrade base -> upgrade
    head) drops and recreates `books`/`authors`/etc., which wiped the *dev*
    database's imported catalog** the same way it does the disposable test
    database. Expected in hindsight (a migration doesn't know which
    database it's pointed at) but worth naming: after the Phase 4 migration
    round-trip check, `make import-data` had to be re-run against the dev
    database to restore its 92,524 books before live smoke-testing could
    proceed. Future phases touching the dev DB's migration history should
    expect the same and budget the ~90 seconds to re-import.
32. **Ruff's B008 rule doesn't treat `fastapi.Query(...)` as pre-exempted**
    the way it treats `fastapi.Depends(...)` (this repo's own
    `extend-immutable-calls` config only lists `Depends`) — but it also only
    flags a `Query(...)` default when one of *its own* arguments isn't a
    literal constant (e.g. `Query(default=RatingsSort.RECENT)`, an enum
    attribute access, trips it; `Query(default=None)` doesn't). The fix
    ruff's own message suggests — "read the default from a module-level
    singleton variable" — means hoisting the *entire* `Query(...)` call
    itself to module level (`_SORT_QUERY_PARAM = Query(...)`), not just the
    enum value passed into it; the latter still gets flagged, since the
    call itself is still evaluated inline.
33. **`session_exclusions` (spec §10.6) has no concrete server-side source
    this phase.** The persisted-batch design (ADR-0007) already guarantees
    spec §5.5's "books already returned in the current feed session" *within*
    one batch — unique book_ids, fixed positions — so the only remaining
    gap is repeat exposure *across* separate top-level requests in one
    browsing session, and nothing in the spec describes a session-tracking
    mechanism for that (the ~30-day auth session is far too long-lived to
    mean "current feed session"). Resolved conservatively: `GET
    /recommendations/*` accepts an optional `exclude` query param
    (comma-separated book ids, capped at 500, malformed entries silently
    skipped) that the frontend can populate from its own in-memory
    "already rendered" list. A real solution if the spec's intent turns out
    to be something more specific later.
34. **The recommendation provider is built lazily, on first request, not
    eagerly in `create_app()`.** Spec §10.13 says "load once at startup",
    but `main.py`'s own docstring establishes a stronger, pre-existing
    constraint: tests must be able to construct the app without a live
    database, since most of them have nothing to do with recommendations.
    The mock engine's candidate pool needs a real query (spec §10.11: it
    has no DB access of its own), which would violate that if run eagerly
    — every integration test defaults to `recommendation_provider=mock`.
    Resolved by caching the built provider on `app.state` on first access
    via the dependency function instead (`modules/recommendations/
    dependencies.py`) — "once, cached for the process's life," just
    triggered a beat later than literal process start.
35. **Ruff formats/lints `tests/` differently depending on invocation
    directory, and this was already true before this phase — Phase 5 just
    had the first lines long enough to land in the gap.** `apps/api/pyproject.toml`
    declares `line-length = 100` and marks `src`/`tests` as first-party
    import roots; the repo root has no `[tool.ruff]` section at all. Running
    `ruff format <file>` from *within* `apps/api` (even targeting a file
    under the repo-root `tests/` via a relative path) picks up apps/api's
    config and its 100-char width. Running the exact command `make lint`
    itself uses — `uv run --project apps/api ruff format --check tests`
    from the *repo root*, no `cd` first — gets ruff's bare 88-char default
    instead (`--project` only selects which venv runs the `ruff`
    executable, not which config it discovers) and treats `book_app.*`/
    `book_recommender.*` as ordinary third-party imports rather than a
    separate first-party group. Both are internally consistent, self
    -contained runs; they just disagree with each other, and only the
    repo-root/no-`cd` form is what CI actually enforces. Whichever way a
    `tests/` file was last formatted, verify it against that exact
    unprefixed invocation before considering it clean — this has now
    surfaced identically in both Phase 4 and Phase 5.
36. **`_clean_all_tables` (integration test fixture) didn't truncate the
    four new Phase 5 tables**, `model_versions` chief among them — it has
    no foreign key to `users`/`books`/`shelves` at all, so `TRUNCATE ...
    CASCADE` on those tables never reaches it regardless. Three new tests
    failed with stale `model_versions` rows leaking across test functions
    within the same session before this was caught (the exact same class
    of gap as Phase 4's own equivalent miss for its four tables — the
    fixture needs an explicit update every phase that adds tables with no
    inbound FK from an already-listed one).
37. **A popularity-formula test's own premise was wrong, not the formula.**
    `test_high_support_high_rating_book_outranks_low_support_perfect_book`
    initially inserted only the two books being compared; with just two
    rows, the "catalog-wide mean" the Bayesian shrinkage pulls toward *is*
    the average of those same two books, which defeats the entire premise
    (shrinking a 5.0-rated book toward a mean that's mostly its own 5.0
    barely shrinks it at all). Fixed by adding twenty realistic "anchor"
    books so the mean actually resembles a catalog-wide one — a reminder
    that a small, hand-crafted integration-test universe can silently
    contaminate exactly the statistic a test is trying to hold fixed.
38. **`model_versions.status`'s enum values (`READY`/`ACTIVE`/`RETIRED`)
    have no spec-given list**, unlike `catalog_status`/`account_status`
    which spec §8.3/§8.1 spell out explicitly. Chosen as the minimal
    lifecycle this phase's own code actually exercises — `build-popularity`
    writes `ACTIVE` directly (no separate activation step/endpoint exists),
    and retires whichever version was previously active for the same
    `model_name`. `READY` is provisioned for a future build/validate/activate
    split but nothing produces it yet.
39. **`engines/` is a fifth `packages/recommender` subdirectory beyond
    spec §10.1's literal four** (`contracts/ providers/ artifacts/
    exceptions.py`). The engine *protocol* lives in `contracts/`, exactly
    as specified; engine *implementations* (mock/popularity/future-pipeline)
    needed a home the spec doesn't name, and grouping them as a sibling to
    `providers/` (which is where they're consumed) reads more clearly than
    folding them into `providers/` itself. Purely additive — nothing
    required moved.
40. **`bx_explicit` is counted a second time inside the popularity
    formula's `support` sum**, on top of `bx_ratings` — verified first,
    against the real dev database, that `bx_explicit <= bx_ratings` holds
    for every active row (so it's a genuine subset, not an independent
    count), then chose to count it again anyway as a deliberate weight:
    explicit engagement is a stronger signal than the raw Book-Crossing
    rating count, which likely mixes in weaker implicit signals. A design
    choice, not a double-counting bug — flagged here so it reads as one on
    a future re-read of the formula.
41. **`npm install --legacy-peer-deps` silently skipped installing
    `@testing-library/react`'s own peer dependency, `@testing-library/dom`**
    — npm 7+'s `--legacy-peer-deps` flag disables automatic peer-dependency
    resolution entirely, not just conflict resolution for the one package it
    was invoked for. Broke the pre-existing `Home.test.tsx` (TypeScript
    errors: `screen`/`waitFor` "not exported", since
    `@testing-library/react`'s types re-export from `@testing-library/dom`).
    A clean `rm -rf node_modules && npm install --legacy-peer-deps`
    reproduced the same gap, confirming it was the flag's real behavior, not
    corruption. Fixed by adding `@testing-library/dom` as an explicit direct
    devDependency. Worth remembering for any future `--legacy-peer-deps`
    install in this repo: verify the full dependency tree afterward, don't
    assume only the targeted conflict was affected.
42. **`openapi-typescript@7.13.0` declares a peer dependency on
    `typescript@^5.x`**; this repo runs `~6.0.2`. Installed anyway via
    `--legacy-peer-deps`, reasoned as a peer-range declaration lag rather
    than a real incompatibility — the tool only parses OpenAPI JSON and
    emits `.d.ts` text, it doesn't hook into TypeScript's compiler
    internals. Confirmed safe in practice: `npx tsc -b --force` on the
    generated output is clean. Reversible if a future `openapi-typescript`
    release actually needs TS6-specific behavior it doesn't have yet.
43. **`Account` was built as a real page this phase, not a `ComingSoon`
    placeholder**, unlike every other Phase 7/8 route. `AvatarMenu`'s
    "Account" and "Change password" items need somewhere real to navigate,
    and `changePassword` already existed as a working endpoint since Phase
    3 — building a placeholder here and a real page later would mean
    throwing away and rewriting the menu's wiring for no reason. Scoped
    narrowly: username display + one change-password form, nothing from
    Phase 7/8's own feature list.
44. **No interactive browser tool is available in this environment** — only
    `WebFetch` (a read-only AI-summarizer), no browser automation. Per
    CLAUDE.md's instruction to state this plainly rather than claim
    success: the actual rendered DOM, click-through navigation
    (register→login→shell→logout), CSS appearance, and responsive/mobile
    layout were **not** verified visually or interactively this phase.
    Mitigated as far as possible without one: a clean production build
    (`vite build`), 15 passing component/integration tests using React
    Testing Library + jsdom (which does exercise real render output and
    simulated user events, just not a real browser engine or real CSS
    layout), and an HTTP-level smoke test of the full auth cycle against
    the live backend (§5e) proving the network contract the UI depends on
    is correct. Both dev servers were left running after this pass
    specifically so the user can do their own click-through if they want
    to close this gap. Genuine residual risk: any bug that only manifests
    in real browser rendering/layout/CSS (not covered by jsdom) would not
    have been caught.
45. **`apps/web/src/api/health.ts` (Phase 1's health-check API wrapper) was
    deleted, not kept**, once `Home.tsx` stopped being a health-check smoke
    page and became a real route rendering `ComingSoon`. Confirmed
    unreferenced anywhere else via grep before deleting, rather than left
    behind as dead code.
46. **No backend route served cover image bytes before this phase**, even
    though `LocalFileStorage` (Phase 2) and every relevant response schema
    (`cover_object_key`) existed already — nothing before Phase 7 rendered
    an `<img>` tag, so the gap was invisible until now. Spec §20 ("do not
    construct cover paths in frontend") plus the Docker Compose "covers
    read-only" mount into the API service (spec §16, present since Phase 1
    but never acted on) both point at the same missing piece. Resolved by
    adding `GET /api/v1/covers/{object_key}` (`core/covers.py`) — see
    ADR-0011 for the full reasoning, including why it's deliberately the
    one unauthenticated route in the app.
47. **`cover_storage_local_path`'s bare relative default resolved against
    the wrong directory** — a real bug, caught only by live-smoke-testing
    against a dev server launched the documented way (`make dev-api`'s own
    `cd apps/api &&`), not by the fixture-based unit tests in
    `tests/test_covers.py` (`tmp_path` is always absolute, so those never
    exercised the relative-path branch at all). Fixed with
    `resolve_cover_storage_root()` in `core/covers.py`, anchoring at the
    repo root via `Path(__file__).resolve().parents[5]` — the exact pattern
    Phase 5's `modules/recommendations/artifact_paths.py` already
    established for `artifact_storage_local_path` (same root cause,
    documented in that file's own module docstring), and which Phase 2's
    `import_catalog.py` and Phase 6's `export_openapi.py` each already use
    independently for their own default paths. Deliberately **not**
    refactored into one shared utility — four small, self-contained copies
    of a two-line pattern is the established convention here already, and
    consolidating it would be a bigger, riskier change than this bugfix
    called for (CLAUDE.md: "three similar lines is better than a premature
    abstraction"). Worth revisiting *only* if a fifth call site appears.
48. **No book in the dataset has any usable "series" data to display
    separately.** Investigated before building anything, having initially
    planned to derive a series annotation by diffing `title` against
    `title_without_series` (the schema provides both): queried the live
    dev database directly and found `title <> title_without_series` for
    **zero** of 92,524 rows — `title_without_series` is populated but
    always identical to `title`, so it carries no information at all.
    `series_data.source_series_ids` is real for 29,948 books (~32%) but is
    genuinely opaque per `import_adapter.py`'s own docstring ("series gives
    only opaque source series IDs, never names") — e.g.
    `{"source_series_ids": ["179504", "1105605"]}`, unusable for display.
    The good news: the raw `title` field already embeds series info in
    human-readable form when present (e.g. "Stone of Farewell (Memory,
    Sorrow, and Thorn, #2)"), a Goodreads convention confirmed directly
    against real rows — so showing `title` as-is (which `BookDetailContent`
    already does) satisfies spec §12.7's "series" bullet honestly, without
    inventing a label for data that doesn't exist. Caught before writing
    any dead string-parsing code, not after.
49. **Card's Save/Saved button and the shelf-selector button are two
    controls over one action, and spec §12.6 doesn't fully specify how
    they relate** — it separately says "top-right Save/Saved" and
    "remember last-used shelf during session" (the latter written as a
    property of the shelf selector). Resolved as a Pinterest-informed
    reading (ADR-0008's own naming: "Pinterest-inspired frontend"),
    matching how Pinterest's own Save button behaves: unsaved + a
    last-used shelf exists this session → "Save" instantly adds to it, no
    picker; unsaved + no last-used shelf yet → opens the picker (nothing
    to quick-save *to*); already saved → clicking "Saved" opens the picker
    to review/edit rather than instantly unsaving everywhere. "Session" is
    read as `sessionStorage` (`hooks/useLastUsedShelf.ts`) — cleared on tab
    close, which is a closer literal match than plain in-memory state (lost
    on every unmount) or `localStorage` (would outlive the session
    entirely).
50. **Home's shelf-lens row navigates to `/shelves/:id/discover` instead of
    rendering shelf-scoped recommendations inline.** Spec §12.4 lists the
    row as "For You + user shelves" under Home's own bullet list (Phase 7
    scope), but that route's actual content — tabs, collage overview — is
    explicitly Phase 8 scope (spec §18). Building shelf-scoped results
    inline on Home now would mean either duplicating Phase 8's eventual UI
    or building throwaway code; navigating to the (still-placeholder) route
    keeps the lens row real and functional without jumping ahead of the
    phase boundary. The route itself already exists and already resolves
    correctly (Phase 6) — only its content is still `ComingSoon`.
51. **Masonry uses round-robin column distribution, not CSS `columns` or a
    shortest-column-fill algorithm.** Spec §12.4 explicitly requires
    "stable rendered order," which native CSS multi-column layout can't
    guarantee under infinite scroll — appending items rebalances the
    *entire* column set, potentially moving already-rendered items to
    different columns. A shortest-column-fill algorithm (used by e.g.
    Pinterest's real masonry) avoids that but needs real image height
    measurement to decide placement, which needs either `ResizeObserver`
    wiring per card or waiting for image load events. Round-robin
    (`item index % columnCount`) makes every item's column assignment a
    pure function of its own index, so appending items at the end can
    never change where earlier items sit, and needs no height measurement
    at all — a deliberate simplicity-for-a-small-visual-cost trade,
    reversible later if true shortest-column balancing turns out to matter
    more than this phase judged.
52. **Grid column-count breakpoints are concrete pixel values picked from
    spec §12.5's given ranges**, not exact numbers the spec states: "wide
    desktop 7-8" → 8 at ≥1536px, "desktop 5-6" → 6 at ≥1024px, "tablet 3-4"
    → 4 at ≥768px, "mobile 2" → 2 at ≥480px, "narrow 1-2" → 1 below that.
    Pixel breakpoints match Tailwind's default `md`/`lg`/`2xl` so the grid
    agrees with every other responsive class already in the app
    (`hooks/useGridTier.ts`).

    Column count is **not** the lever for cover size — that's the tier's
    `gutterShare`, a percentage of the row width given over to gutters,
    split across the N-1 gaps. The Phase 10 visual pass wanted covers at
    ~80% for a more open feed, and briefly did it by raising the column
    counts above the spec's ranges; that shrank covers but also changed how
    many books were on screen, which was not the intent. Doing it through
    the gutter keeps the spec's counts intact and separates the two
    concerns: **columns decide how many books are visible, `gutterShare`
    decides how large they are.** A percentage gutter (rather than a larger
    fixed px gap) is what makes the size uniform — a card is always
    `(100 - gutterShare) / N` percent of the row, at every viewport width,
    where a fixed gap is a large share of a narrow column and a negligible
    share of a wide one.

    `gutterShare` is per tier rather than global, and has to be: column
    counts are integers, so no single global value can express "every
    tier's covers grow 8%" at the same time as "wide desktop drops to 7
    columns". Wide desktop therefore carries 29.1 while every other tier
    carries 19 — that gap is entirely the cost of its column change, not a
    deliberate density difference, and the two tiers' *cover sizes* stay in
    step. Current values put wide-desktop covers at ~176px with ~84px
    gutters on a 1900px viewport.

    Grids that don't span the viewport pass `maxColumns` to cap the count
    (the detail dialog's "Similar books" strip), since the hook measures
    `window`, not its container.
53. **"New user" guidance banner heuristic is "has zero shelves," not a
    dedicated new-account check** — spec §12.4 asks for a "subtle guidance
    message" for new users without defining "new." Fetching `/me/ratings`
    just to check for a truly new account would add a request Home doesn't
    otherwise need; shelf count is already being fetched for the lens row
    (spec §12.4's own other bullet), so reusing it is free. Also
    dismissible and `localStorage`-persisted once dismissed — "no forced
    onboarding" (spec §12.4) means it must never block the feed or return
    uninvited once closed.
54. **The detail page's similar-books section fetches a single page (no
    infinite scroll)**, unlike Home's feed. Spec §12.5's masonry/infinite-
    scroll requirements read as being about the primary feed surfaces
    (Home, Search, Shelf feeds), not necessarily an in-modal secondary
    section; a detail view already has a lot happening on screen, and a
    fixed `limit=12` similar-books grid is enough to prove the surface
    works end to end without adding a second `IntersectionObserver`
    inside what may itself be a scrolling `Dialog`. Reversible if it turns
    out to matter — the same `BookMasonryGrid` component would work with
    `useInfiniteQuery` in place of `useQuery` with no changes to the
    component itself.
55. **Home's infinite query never sends the `exclude` param the backend
    already supports** (spec §5.5 "already returned in the current feed
    session," `recommendations/api.py::_parse_exclude`, added Phase 5).
    Not needed for *continuous* scrolling in one visit — the persisted
    batch (ADR-0007) already guarantees no duplicates across pages of the
    *same* `useInfiniteQuery` cache entry — only for a genuinely *new*
    top-level request within one session (e.g. the cache entry got garbage
    collected after 5 minutes of inactivity, TanStack Query's default
    `gcTime`). Tracking every book_id ever rendered across cache
    lifetimes would need its own session-scoped store for a narrow edge
    case; left unbuilt this phase, flagged here rather than silently
    decided.
56. **jsdom implements neither `IntersectionObserver` nor a working
    `localStorage`/`sessionStorage`, found by running the new tests, not
    anticipated in advance.** `IntersectionObserver` is simply absent
    (`typeof window.IntersectionObserver === 'undefined'` on a fresh jsdom
    Window, verified directly) — `Home`'s infinite-scroll effect threw the
    moment it mounted in any test until stubbed. `localStorage` is a
    stranger bug: Node 26 added its own native, experimental
    `globalThis.localStorage`, which throws ("...not available because
    --localstorage-file was not provided") the instant anything touches
    it, and it shadows jsdom's own per-window implementation (verified
    working in isolation via a standalone `jsdom.JSDOM()` construction) —
    an environment/tooling interaction specific to this Node version, not
    a jsdom bug per se. Both stubbed with small deterministic
    implementations in `src/test/setup.ts` (`IntersectionObserver`'s
    `observe` is a no-op — the actual "sentinel became visible" trigger is
    Playwright's job in Phase 9, not simulated here) so tests don't depend
    on either jsdom's feature coverage or the Node version running them.
57. **Scroll restoration is hand-rolled (`sessionStorage`, keyed by a
    caller-supplied id), not React Router's built-in `<ScrollRestoration>`**
    — that component only exists for the data-router API
    (`createBrowserRouter`/`RouterProvider`), and this app uses declarative
    `<BrowserRouter>` specifically because the book-detail modal-route
    pattern (spec §12.7) needs the background page to stay mounted
    underneath the `Dialog`, which is simpler to express declaratively.
    Only matters for a genuine unmount/remount of Home (e.g. navigating to
    Shelves and back via the rail) — opening a book as a modal never
    unmounts Home at all, so that path already preserves scroll position
    for free.
58. **Rename/edit-description/delete live on the shelf detail page, not
    the shelf overview grid** (spec §12.8 lists both "Create, rename, edit
    description, and delete" and separately "Overview uses board-like
    cover collages" without saying which surface owns which action).
    Resolved as: the overview is for browsing/navigating between shelves,
    the detail page is where a visitor is already focused on *one* shelf —
    the more standard split, and it keeps the collage grid uncluttered.
    Reversible if per-card quick-actions turn out to matter more than this
    phase judged.
59. **Shelf Discover's cards default their quick-Save to the shelf being
    discovered for, overriding the session's last-used shelf** (spec
    §12.8: "defaults Save to current shelf") — implemented as a new
    `defaultShelfId` prop threaded `BookMasonryGrid` → `BookCard`, checked
    ahead of `useLastUsedShelf`'s value in the quick-Save handler.
    Deliberately *also* updates the session's last-used shelf when used,
    since it genuinely was the most recently saved-to shelf — consistent
    with Phase 7's own "remember last-used shelf during session" reading,
    not a special case carved out from it.
60. **Search tier 2 ("exact title/author combination", spec §9.6) is read
    as the query exactly matching "title author" or "author title"
    concatenated, case-insensitively** — covering both natural typing
    orders (e.g. "dune frank herbert" or "frank herbert dune"). Spec gives
    no further detail; this is a conservative, documented, reversible
    reading, not a guess left silent. See ADR-0012.
61. **Search's popularity tiebreak (tier 7) uses the dataset's own
    `ratings_count` column, not `packages/recommender`'s Bayesian-shrunk
    popularity artifact** (`build-popularity`'s output). Deliberate, not
    an oversight: reusing the recommender's artifact would mean a live
    search request depends on whether `make build-popularity` has ever
    been run, and reading a file one module owns from a route in a
    different one inverts the module boundary ADR-0002 sets up.
    `ratings_count` is always present from import, with zero coupling to
    the recommendation pipeline. See ADR-0012 — flagged here too so a
    future reader doesn't mistake this for a bug (two different
    "popularity" numbers existing in the same app is a legitimate
    surprise on a cold read).
62. **The Rated page's genre filter is a plain text input, not a
    dropdown** — no endpoint lists the catalog's genre taxonomy (Phase 2
    imported 10 genres total, but nothing exposes them as an API
    resource), and building one wasn't asked for by any phase's own spec
    §18 scope. The backend already does exact match after the same
    `normalize_for_uniqueness` folding used everywhere else, so a
    correctly-typed genre name works identically to a dropdown selection
    would — the gap is discoverability, not correctness.
63. **`useSeedRatingsIntoBookState` only patches `rating` (merge, not
    replace) — `shelf_ids` can be stale on the Rated page specifically**
    until the visitor opens a book's detail or interacts with its shelf
    selector directly. `RatedBookItem` (spec §9.4) has no `shelf_ids`
    field to seed from (a plain ratings listing doesn't join shelves), so
    a book that's both rated *and* shelved would show "Save" (not
    "Saved") on its Rated-page card until corrected. Same class of
    limitation Home already has by design (spec §5.5 guarantees Home
    never needs shelf state up front) — genuinely worse here since a
    rated-and-shelved book is a realistic, not edge-case, combination.
    Not fixed this phase: would mean extending `RatedBookItem` (an
    already-shipped, tested Phase 4 schema) for a Phase 8 frontend
    nicety spec's own Rated section doesn't ask for ("Grid of rated books
    with user rating" — no mention of shelf controls at all).
64. **Search's suggestion dropdown is a Radix `Popover` around plain
    tabbable buttons, not a full ARIA 1.2 combobox** (`aria-activedescendant`,
    arrow-key roving focus through the list). Keyboard-operable — Tab
    reaches every suggestion, Enter/Space activates it, Escape closes the
    popover — just without the "arrow keys move a virtual selection"
    affordance real combobox widgets have. Same trade-off, same
    reasoning, as Phase 7's shelf-selector (native checkboxes over a
    hand-rolled listbox): a simpler, natively-correct pattern over a
    harder-to-get-right one, for a widget spec §12.10 itself scopes down
    ("no technical mode control in version one").
65. **Docker, revisited.** Risk #1 (Phase 1) is still true — Docker remains
    uninstalled in this environment, so `docker compose up` has never
    actually been run. What changed this phase: both Dockerfiles are now
    genuinely multi-stage and production-shaped (non-root user, `--no-dev`
    sync, no `--reload`, nginx serving a real build), not just present.
    `docker-compose.yml` pins `target: dev` explicitly on both services —
    without that pin, Compose defaults to the *last* stage in each
    Dockerfile, which is now `production` (it wasn't, before this phase
    added a production stage at all), and local dev would silently lose
    its bind mount and reload. Caught by re-reading the compose file after
    writing the new stages, not by running it. Still fully reversible and
    still isolated — nothing outside these two files and `docker-compose.yml`
    depends on Docker being present (ADR-0009).
66. **Browser automation capability, revisited.** Risk #44 (Phase 6) said
    no interactive browser tool was available in this environment, so
    click-through, real rendering, and layout were never verified, only
    inferred from jsdom tests and HTTP-level smoke tests. That changed
    this phase: `npx playwright install --with-deps chromium` succeeded,
    downloading a real Chrome for Testing binary, and the new E2E test
    drives it through all 13 of spec §13.5's steps successfully. This
    resolves the gap **for exactly what the E2E test covers** — register,
    login, Home's grid, the book-detail dialog, rating, the shelf
    selector, Not Interested, the avatar menu, logout — across a real
    layout engine, real CSS, real pointer events. It does **not**
    retroactively verify claims Phases 6-8 made about surfaces the E2E
    flow doesn't touch (Search's suggestion dropdown, the Account page,
    mobile-width `BottomNav` layout, dark/light theming if any) — those
    remain jsdom-verified only, same as before.
67. **First automated accessibility audit, and its one finding.** Every
    prior phase built on accessible primitives (native radios/checkboxes,
    Radix `Dialog`/`AlertDialog`/`Popover`/`DropdownMenu`/`Toast`, real
    `<label>`s) but nothing had actually run an automated checker against
    them until this phase's two `@axe-core/playwright` scans
    (`e2e/critical-flow.spec.ts`). Only "critical"/"serious" impact
    violations fail the test; "moderate"/"minor" are logged to the test
    output but don't block. That threshold is deliberate, not laziness: as
    the *first* automated a11y gate this project has ever had, a
    zero-tolerance bar on day one risks the check getting disabled the
    first time it's inconvenient rather than fixing what it finds. It
    already found one real, moderate issue this way: Home has no `<h1>`
    (axe rule `page-has-heading-one`) — every other page in the app does
    (`ShelvesPage`'s "Your shelves", `RatedPage`'s "Rated books", etc.),
    Home alone was never given one. Logged, not fixed this phase — small,
    scoped, reversible, and better tracked here than silently patched
    without the acceptance checklist reflecting that it was ever missing.
68. **Two real concurrency bugs in `useBookState.ts`, found by the E2E
    test rather than designed for.** Full detail in the Phase 9 section
    above and in the code itself; summarized here because both are the
    kind of thing worth being able to find from the risk log alone.
    (a) `useSyncShelvesMutation`'s `onSuccess` overwrote the shared cache
    with its own mutation's server response, which — once two shelf
    -checkbox clicks overlap in flight, exactly what checking two boxes in
    the popover does — could land *after* a later click's optimistic
    update and silently revert it. Fixed by deleting the `onSuccess`
    write; a full-replace sync's optimistic value already is the correct
    end state. (b) `optimisticallyPatch`'s opening `await
    queryClient.cancelQueries(...)` was guarding a query
    (`queryFn: skipToken`) that never has anything in flight to cancel —
    pure dead weight whose only effect was delaying the optimistic write
    past the native control's own instant DOM state change, opening a
    flicker/lost-click window on React's next controlled re-render. Fixed
    by making the function synchronous. Neither bug is E2E-specific or a
    test artifact — both are realistic for any user clicking normally, and
    neither was reachable by any jsdom test, which never fires two
    overlapping mutations against the same book.
69. **The `hasPointerCapture`/`setPointerCapture`/`releasePointerCapture`
    jsdom gap.** Found while first writing `ToastViewport.test.tsx`, not
    anticipated: jsdom implements none of the Pointer Capture API at all
    (`Element.prototype.hasPointerCapture` is `undefined` on a fresh
    jsdom `Window`, verified directly), and Radix `Toast`'s swipe-to
    -dismiss gesture handling calls these unconditionally the moment a
    pointer event fires on a toast — throwing the instant a test clicks
    anything inside one. `Dialog`/`AlertDialog`/`Popover` never hit this
    (no swipe gesture), which is why it took until this phase's new
    `Toast` component to surface. Three no-op stubs in `test/setup.ts`
    are enough — nothing asserts on actual pointer-capture state, only
    that interacting with a toast doesn't throw.
70. **A stray `npm install` briefly landed at the repo root instead of
    `apps/web/`, caught and cleaned up before it touched anything real.**
    This environment's documented cwd-reset quirk (a persisted `cd`
    doesn't reliably carry across *separate* Bash tool calls) struck
    between preparing a command and running it, so `npm install
    @radix-ui/react-toast react-error-boundary` ran from the repo root.
    Created a stray root-level `package.json`/`package-lock.json`/
    `node_modules/`; `apps/web/package.json` itself was untouched
    (confirmed by grep before doing anything else). Cleaned up by removing
    the three stray root items, re-running the install with an explicit
    `cd /path/to/apps/web && npm install ...` inside one single Bash
    command, and verifying both the target packages and everything
    installed in earlier phases were intact in `apps/web/node_modules`
    afterward. Full frontend suite re-run clean afterward. No repo files
    were lost — purely an accidental creation-and-cleanup of untracked,
    session-local files — but it's the reason every install command this
    phase (and the Playwright one specifically) uses an explicit `cd` in
    the same command rather than relying on a prior `cd`.
71. **General rate limit and body-size numbers are deliberately generous,
    not tuned.** 600 requests/60s per IP, 1MB request body cap
    (`.env.example`, `core/config.py`). This is spec §14's *coarse
    backstop* "distinct from the auth-specific boundary" that's existed
    since Phase 3 (10 attempts/5min on login/register specifically) — the
    general limit exists to catch a runaway client or script, not to
    throttle normal use, so it's set loose enough that no legitimate
    browsing/rating/searching session should ever plausibly hit it. Real
    tuning (if ever needed) is an operational decision for actual traffic
    patterns, not something to guess at in version one.
72. **`make seed-demo`'s account is `demo_reader`, not `demo`.** `demo` is
    already in `username_rules.RESERVED_USERNAMES` (alongside `admin`,
    `api`, `auth`, etc. — Phase 3), so it was never an available choice;
    `demo_reader` reads clearly as "the demo account" without colliding
    with the reserved list or implying it's a system/admin account the
    other reserved names are protecting against impersonation of.
73. **The new CI `e2e` job was authored and validated by running its
    equivalent steps manually in this environment (migrate → import the
    sample fixture → boot the API → run Playwright, all against a fresh
    -enough local setup), not by actually watching GitHub Actions run it.**
    No push happened from this environment this phase. The job reuses
    patterns already proven to work in the existing `backend` job
    (the same Postgres service image, the same health-check-poll boot
    pattern) and `npx playwright install --with-deps chromium` is
    Playwright's own documented fresh-runner install path, but a
    CI-specific problem (runner resource limits, a timing difference
    under load, an apt package Playwright's `--with-deps` doesn't cover
    on the runner's exact image) would only be caught once this branch's
    CI actually executes.
74. **The E2E test hardcodes no book title, author, or id** — every
    "which book" decision is either "whatever Home/Discover's first card
    currently is" (captured at runtime) or a book created by the test
    itself (the two shelves). This is deliberate: it's the only way the
    same test file can pass unmodified against both this environment's
    persistent 92,524-row dev catalog and CI's 301-row
    `data/sample/books.parquet` fixture, whose actual contents,
    popularity ordering, and even which single row is deliberately invalid
    (risk in `tests/integration/test_import_catalog.py`) are completely
    different datasets. The tradeoff: the test proves the *mechanism*
    (rate a book, it appears on Rated; shelve a book, it appears on that
    shelf) rather than any specific book's specific data being correct.
75. **The Rated page offers three of spec §12.9's five sorts.** Spec lists
    recent, highest, lowest, title, author; the UI now exposes only the
    first three, with recent still the default. Alphabetical sorts are a
    filing operation rather than a browsing one, and in a cover-led grid
    they gave the row four controls' worth of weight for something nobody
    reached for. `RatingsSort` and `GET /me/ratings` are untouched — both
    values still validate and still work — so this is a UI trim, not a
    capability removal, and re-adding either is one line in
    `routes/Rated.tsx`'s `SORT_OPTIONS`.
76. **A card's own rating is rendered as stars in the card body, not as a
    badge over the cover.** Spec §12.6 says "state badges appear where
    relevant" without saying where; the numeral badge was absolutely
    positioned against the *card*, which put it at the bottom of the whole
    card — on top of the title and author, not the cover (visible in any
    two-line title). Rather than re-anchor it to the cover, the rating
    moved into the flow between cover and title as five accent stars with
    half steps, where it's legible at a glance instead of being a number
    to read. "Not interested" stays an overlay, now correctly anchored to
    the cover. Spec §12.6's required "title, maximum two lines; primary
    author, one muted line" below the cover is unchanged — the stars sit
    above them, not in their place.
77. **The wordmark sits at the top of the left rail, inside its `<nav>`.**
    Spec §12.2 says the rail has *exactly* Home, Shelves, Rated. The logo
    links home, as a wordmark is expected to, and adds no destination that
    list doesn't already contain — Home is one of the three. It was first
    placed *outside* the `<nav>` to keep the enumerated navigation
    literally three entries, but that left it the one piece of the page
    belonging to no landmark, which the axe scan flagged (`region`,
    moderate — caught by the E2E run, not by reading it); inside the
    landmark, at the cost of Home being reachable under two names, is the
    better trade. The rail widened from 80px to 112px to fit it legibly, which is what
    now sets its width; `AppShell`'s content offset follows it. The
    The artwork is `apps/web/public/logo.png`, derived from the supplied
    2000×2000 PNG: cropped to its own bounds (the original was mostly empty
    padding, so used as-is it rendered a postage stamp) and with its baked
    near-black backdrop keyed to alpha, so it composites on any surface
    instead of showing a faintly mismatched dark rectangle against
    `--color-sidebar`. Keying classified each pixel as one of the two ink
    colours and recovered coverage from that ink's strongest channel — a
    plain luminance key would have left the blue spines ~82% opaque and
    shifted their colour. The artwork's blue is #4c6fd7, which is exactly
    `--color-accent`.

### Recommender Phase R0

78. **Twelve documents still reference `APP_SPECIFICATION.md` by its old
    root path.** Ten are ADRs (0001-0010), which are deliberately left
    alone: an ADR is a record of what was decided and against what, at a
    point in time, and rewriting paths inside them would edit history to
    match the present. The two documents that are *read as current
    instructions* — `README.md` and this plan — now point at
    `archive_of_structural_prompts/app_building_prompts/`. The residual
    risk is a future reader following an ADR's path and finding nothing;
    mitigated by both entry-point documents naming the new location. If it
    proves annoying in practice, a one-line pointer file at the old path
    is the cheap fix, not a mass rewrite.
79. **Non-idempotent recommendation-impression writes are a live defect in
    shipped code, not merely a missing feature.** `create_impressions`
    inserts unconditionally into a table with `UNIQUE(request_id, book_id)`,
    so a client re-fetching a persisted cursor page can trigger a 500. R0
    deliberately did not fix it — R0's acceptance criterion is that no
    recommendation behavior changes — but it means impression data is
    untrustworthy *and* a real user-facing failure exists until R1's first
    task lands. This is the strongest argument for R1 being next and not
    being skipped or reordered.
80. ~~**`ArtifactManifest.item_mapping` may not scale to five artifact
    families.**~~ **Closed in R3 — measured, and it did not scale.** 8.9 MB
    of JSON, 0.22 s of parse time and ~55 MB of resident objects per family
    per worker, plus a 1.56 MB `model_versions.manifest` row. Replaced by a
    504 KB `mapping.npz`; three families now load in 1.8 s / 77 MB
    *including every payload*. ADR-0020, §3R "Drift items closed".
81. ~~**The heavy offline ML dependencies have never been resolved.**~~
    **Closed in R4 for the CF stack.** `implicit 0.7.3` and `scipy 1.18.0`
    install from wheels in 4.4s on darwin/arm64 and train correctly — no
    source builds, no OpenMP problems. They live in a `training` dependency
    group that `uv sync --all-packages` provably prunes back out (ADR-0021).
    **The transformer stack remains unexercised**: resolution is known to
    work (see below) but `torch`/`sentence-transformers` have never been
    downloaded or run here, and an embedding build over 92,524 books has
    never been timed. R5 carries that, and it is a much larger download than
    anything R4 needed. Original R3 probe, still current: Probed in R3 before committing
    anything, resolution-only (`uv pip compile`, no wheel downloads): the
    full stack resolves cleanly in 1.2 s on darwin/arm64 with uv 0.10.4 —
    `numpy 2.5.2`, `scipy 1.18.0`, `scikit-learn 1.9.0`, `implicit 0.7.3`,
    `sentence-transformers 5.7.0`, pulling `torch 2.13.0` and
    `transformers 5.15.0`. Only NumPy was actually added (R3 needs nothing
    heavier, and it was already in the lock via pandas/pyarrow).
    **What remains unknown is cost, not feasibility:** wheel download and
    install size for the torch stack, and how long an embedding build over
    92,524 books takes on this hardware. R4/R5 carry that. The lock file
    must not be hand-edited (CLAUDE.md), and the training-only group must
    be one the API runtime does not install (ADR-0018) — two tests now fail
    if the encoder stack reaches either runtime dependency set.

### Recommender Phase R1

82. **Attribution coverage is partial by design, and analysis must treat
    it that way.** A null `surface` means "origin genuinely unknown"
    (bookmark, direct link, a path R1 didn't instrument) — it is not a
    category and must never be modelled as one. Roughly: recommendation
    surfaces and search are attributed; anything reached outside the app's
    own navigation is not.
83. **Direct-URL and bookmark visits are not recorded as opens.**
    `book_opened` fires on the card click, not on detail-route mount, so a
    reader who pastes a book URL, refreshes, or returns via browser
    history generates no open event. This was the deliberate trade (see
    R1 decisions): mount-time firing would record refreshes and remounts
    as intent and inflate the signal. The consequence is an undercount
    skewed *toward* in-app navigation, which matters when open frequency
    is eventually used as evidence. Revisit if the undercount proves
    material — a mount-time fire guarded by a per-history-entry flag would
    close it.
84. **Nothing deletes expired recommendation batches.** `expires_at`
    bounds how long a batch is *usable* (ADR-0007), not how long its rows
    live, so `recommendation_requests`/`results`/`impressions` grow
    monotonically — about 60 result rows per feed request. Harmless at
    development volume, unbounded in principle. The policy is documented
    in §3R and the intended shape is an explicit CLI mirroring
    `make cleanup-sessions`; it is not built, and rec-spec §4.5 rules out
    adding a scheduler for it. `interaction_events`/`search_queries` are
    deliberately exempt — they are the permanent training record.
85. **`InteractionSurface` is a closed set, so adding a surface is a
    two-repo change.** New surfaces need the enum, a regenerated client,
    and the call site. That friction is the point (it's what keeps typo'd
    surfaces out of training data), but it will feel like overhead the
    first time someone adds a surface in a hurry and gets a 422.
86. **The submitted-search id can lose a race with a fast click.**
    `recordSubmittedSearch` fires without blocking navigation, so a reader
    who submits and clicks a result before the write returns produces an
    open with no `search_query_id`. Correct per ADR-0015 (better missing
    than invented) and rare in practice, but it means search→open
    attribution is a lower bound, not a complete census.
87. **Two `book_opened` events fire for one logical open in React Strict
    Mode**? No — checked, not the case: the call sits in a click handler,
    not an effect, so Strict Mode's double-invocation doesn't reach it.
    Noted explicitly because it's the obvious failure mode for this kind
    of instrumentation and the next reader will wonder.

### Recommender Phase R2

88. **`profile_version` becoming required is a breaking contract change for
    any out-of-tree `UserContext` producer.** There are none today — both
    construction sites are in this repository and both were updated — but a
    remote provider built against the old optional field would now fail
    validation. Noted because ADR-0006 deliberately keeps
    `RemoteProvider` as a live seam.
89. **The version churns on shelf re-saves.** Including `added_at` means
    remove-then-re-add produces a new version despite an identical
    membership set. Correct (the recency evidence changed) but it means a
    reader who reorganizes shelves invalidates their cached fold-in factor
    repeatedly. If that proves expensive once ALS exists, the fix is to
    bucket `added_at` to a coarser granularity — a change to
    `PROFILE_VERSION_ALGORITHM`, not to the schema.
90. **Context caps are unvalidated against real heavy users.**
    `MAX_CONTEXT_SAVED_BOOKS = 1000` and the other limits are reasoned
    guesses, not measurements; no account in this environment has enough
    shelf memberships to exercise truncation. R9's performance profiling is
    where these get real numbers, and `saved_books` is the one most likely
    to need raising, since per-shelf semantic profiling wants whole shelves.
91. **A taste seed can point at a book the reader later rates or rejects.**
    Nothing prevents it, deliberately — the states are orthogonal
    (ADR-0019). But it means generators must decide how to weigh a book
    that is both a seed and a 3/10 rating; rec-spec §7.1's signal policy
    covers the combination, and R6's generators are where it has to be
    implemented rather than assumed.
92. **Seeds have no dedicated eligibility rule.** A seeded book is not
    excluded from Home by spec §5.5, so a reader can be recommended a book
    they explicitly seeded. That may well be wrong from a product
    standpoint, but changing eligibility is a product decision outside R2's
    scope and would alter shipped behavior — flagged here rather than
    silently decided.

### Recommender Phase R3

93. **The 10% unresolved-items rejection threshold is a judgement, not a
    measurement.** `DEFAULT_MAX_UNRESOLVED_FRACTION` draws the line between
    "normal catalog attrition, drop and serve" and "these describe different
    worlds, do not serve". No real operational state has ever approached it
    — the live catalog resolves 92,524/92,524 — so the number is reasoned,
    not observed. It is a named constant with the reasoning attached, and it
    is the first thing to revisit if a legitimate rebuild ever trips it.
94. **Most of the 77 MB per worker is Python strings, not matrices.** The
    item-metadata table decodes 92,524 titles and authors into tuples at
    load (34 MB of the total, and the 1.07 s that makes it the slowest
    family to load). The numeric artifacts are cheap by comparison. If
    per-worker memory becomes the binding constraint on deployment density
    — ADR-0014 says it directly bounds worker count — decoding strings
    lazily is the lever. Deliberately not pre-optimized: R9 is where
    profiling decides, and three families is not yet five.
95. **Artifact freshness has no monitoring, only correctness.** A stale
    artifact now degrades safely and logs its counts, but nothing warns
    that `make import-data` has run since the last artifact build. Books
    added after a build are simply invisible to candidates, silently and
    indefinitely. The information needed is already recorded (the manifest
    and the `model_versions` row both carry `catalog_version`); nothing
    compares them outside the loader's own startup log.
96. **The source-similarity graph inherits Goodreads' noise verbatim, by
    design.** Spot-checking neighbours of a real architecture book returned
    two architecture books and a paranormal romance. rec-spec §14 requires
    this generator stay semantically pure — export what the source says,
    never quietly mix in same-author or same-genre heuristics — so the noise
    is not a bug to fix here. It is a reason to treat this source's
    precision as unmeasured when R6 assigns it an RRF weight, and R9's
    content/source evaluation (rec-spec §23.2) is where it gets a number.
97. **`interactions.parquet` is still read by nothing.** Drift item 13
    remains open, unchanged since R0: 775,090 historical rows present since
    Phase 2, deliberately never imported into PostgreSQL because historical
    integer users are not application users. R4 is its first consumer, and
    the mapping validator R3 built is what will drop and report the rows
    that do not resolve to catalog items.

### Recommender Phase R4

98. **ALS recommends a narrow slice of the catalog.** Catalog coverage is
    0.035-0.046 with a Gini of ~0.86, against item-CF's 0.547 and 0.374 on
    the same holdout. ALS is the more accurate generator and by far the more
    concentrated one, which is ordinary for ALS on sparse implicit data but
    matters directly for R6/R7: fusing it at a high RRF weight would import
    that concentration into the feed. The two families are complementary
    rather than interchangeable, and the surface reranker (ADR-0017) is
    where the balance has to be struck.
99. **Offline metrics are low in absolute terms.** Recall@10 ≈ 0.059 and
    NDCG@10 ≈ 0.047 for the shipped ALS. That is unremarkable for
    Book-Crossing — 707k positives over 92k items is extremely sparse, and
    61% of the evidence is implicit with no rating — but it means these
    numbers are useful as a *relative* comparison between configurations and
    should not be read as a prediction of live quality. Live behavior is
    driven by application evidence these models never saw.
100. **The historical model cannot know about the application's own
    catalog activity.** ALS item factors come entirely from Book-Crossing
    readers; a book that no historical reader touched has a factor driven
    only by regularization, and 3,660 catalog items (92,524 − 88,864) have
    no historical interaction at all. Those books are effectively invisible
    to both CF families and will depend on the content and source-similarity
    generators (R5, already-built R3) for any exposure.
101. **Top-K tie-breaking in the neighbour build is arbitrary, though
    deterministic.** `argpartition` selects among equal similarity scores
    without regard to index order, so which of several tied neighbours
    survives the top-K cut is unprincipled — it is stable across rebuilds
    (the determinism test passes and checksums match), but it is not the
    lowest-index or otherwise meaningful choice. Harmless at k=100 on real
    data where exact ties are rare; it surfaced while building a test
    fixture where 32 candidates tied exactly.
102. **Item-CF evaluation uses 3,000 of the 15,747 holdout readers.** The
    neighbour scan is per-seed rather than one matrix product, so scoring
    every holdout reader would dominate the build. The subset is a
    deterministic prefix, which is enough to separate two variants but makes
    item-CF's absolute metrics noisier than ALS's, and the two families'
    numbers are not directly comparable at equal confidence.
103. **The frontend test suite is timing-sensitive under load.** Running
    `make test` while a training sweep occupied the CPU produced two, then
    one, spurious vitest failures at 11-29s durations; the same suite passes
    in 5.7s unloaded, and no frontend file was touched this phase. Not
    introduced by R4, but R4 is the first phase whose builds are heavy
    enough to trigger it — worth knowing before someone debugs a "flaky"
    frontend regression that is really CPU starvation.

### Recommender Phase R5

104. **The tag rules are a hand-written blocklist, and blocklists leak.**
     `_STATUS_TOKENS` covers the bookkeeping vocabulary visible in the top
     of the live catalog's tag distribution, but 173,787 distinct tags have
     a long tail nobody has read. Some filing tags certainly survive, and a
     few thematic ones are certainly rejected — `library` blocks
     `library-book` but would also block a genuine tag about libraries.
     The rules are versioned and their rejections are reported by category
     in the build, so a change is reviewable; what does not exist is
     evidence about the tail.
105. **The clustering threshold is untuned against real embeddings.**
     `merge_threshold = 0.55` was reasoned from how normalized Qwen3
     vectors typically distribute, not measured on this catalog with real
     readers — no account here has enough varied evidence to exercise it
     properly. It is the single number that decides whether a reader has
     two interests or five, and R9's evaluation is where it should get a
     real value.
106. **The content artifact is 181 MB and dominates per-worker memory.**
     Larger than every other family combined. Loading all six families is
     what R9's profiling has to measure; `load_content_artifact(mmap=True)`
     exists for when it does, but nothing has yet decided whether paging
     from disk beats holding 181 MB resident per worker.
107. **Rebuilding embeddings takes ~88 minutes**, so this is the one
     artifact that cannot be casually regenerated, and any change to the
     text template, tag rules or encoder invalidates all of it. All three
     are versioned in the manifest so the invalidation is visible — but the
     practical consequence is that tag-rule changes are expensive, which
     argues for getting risk #104 right before the corpus grows.
108. **Embeddings drift out of date silently, in one direction.** ADR-0020's
     `work_id` resolution means a re-import does not corrupt the artifact —
     books added since the build simply have no vector. The profiler reports
     them (`unembedded_book_ids`) rather than hiding them, but nothing warns
     an operator that the count is growing. Same shape as risk #95, now with
     a much more expensive rebuild behind it.
109. **Interest labels depend on tag coverage.** 501 of 92,524 books have no
     cleaned tags and 3,098 have no genre, so an interest built entirely
     from such books falls back to `Interest around "<title>"`. Correct, and
     rec-spec §13's own suggested form — but it means label quality varies
     with catalog metadata quality rather than with how good the clustering
     was, which is worth knowing before reading a profile as a judgement on
     the model.

## 7. Next phase

**Recommender Phase R6 — the candidate-generator framework and the five
generators.** Scope and acceptance criteria are in
`RECOMMENDER_IMPLEMENTATION_PLAN.md`; ADR-0017 governs fusion and ranking,
ADR-0016 the semantic profiling R6 consumes.

R6 is the first phase since R2 that changes what a reader sees, and the
first that puts any of R3-R5's artifacts on the request path. Everything it
needs now exists and is tested in isolation:

| Generator | What R6 wires up |
|---|---|
| popularity | `load_popularity_artifact` — already serving |
| source similarity | `SourceSimilarityGraph.neighbor_book_ids` (R3) |
| ALS CF | `AlsArtifact.fold_in` + `top_candidates` (R4) |
| item-item CF | `ItemCfNeighbors.candidates_from_seeds` (R4) |
| semantic/content | `ContentEmbeddings.search` + `build_semantic_profile` (R5) |

Three things R6 should keep in view, all recorded above with evidence:

- **The generators are not interchangeable.** ALS is the most accurate and
  by far the most concentrated (coverage 0.046, Gini 0.86); item-CF covers
  far more catalog (0.547, Gini 0.374). Fusion weights that ignore this
  import ALS's concentration into the feed (risk #98).
- **Loading them all costs real memory** — the content artifact alone is
  181 MB (risk #106). R6 is where per-worker footprint stops being
  theoretical.
- **Every generator must respect the exclusion sets the application
  supplies**, which each artifact's retrieval path already implements and
  tests; application-owned eligibility stays outside the engine.

R6 has not been started. Do not begin it as part of an R5 pass.

**The drift-item ledger stayed closed.** R4 emptied it; R5 added no new
items — the two corrections it made (the R4 boundary test's bluntness and
an R3 validation rule that real data disproved) were both fixed in the same
pass rather than deferred.

### The application sequence is complete

Phase 9 was the last phase in spec §18's own list. The application is
functionally complete against `APP_SPECIFICATION.md`: every Functional and
Architecture bullet in spec §19 (§4 above) is checked, and every Quality
bullet is checked except one — `docker compose up` is authored and reasoned
through but not runtime-verified, because Docker has never been available
in this environment across any phase (risk #1/#65). That gap is
environmental, not architectural: nothing in the application depends on
Docker being present (ADR-0009), and closing it needs a Docker-capable
environment to run `make up` in, not more code.

**Correcting this section's own previous statement**, which read "Next
phase: None … anything beyond this point is new scope" and cited CLAUDE.md
as saying the modular recommendation funnel was out of scope. That was
accurate when written and is not now: root `CLAUDE.md` and
`RECOMMENDER_SPECIFICATION.md` put the funnel in scope, and ADR-0013
records the change and what it does *not* reopen. The application
specification's other prohibitions still stand in full — no microservices,
no Redis/Celery/Kafka/Kubernetes, no vector database, no recommendation
algorithms in routes, no database access from the recommender package.

The small standing items that were never phases and still aren't: the
`page-has-heading-one` finding (risk #67), a "list genres" endpoint
(risk #62), the error-path half of the shelf-sync race (risk #68), and
S3-backed storage per ADR-0009's documented-but-not-built AWS mapping.
Each remains independently addressable without reopening either phase
structure.
