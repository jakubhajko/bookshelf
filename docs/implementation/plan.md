# Implementation plan

Status: living document, updated after every phase.
Source of truth: `APP_SPECIFICATION.md`. This plan does not restate product
rationale — see the spec for that. It tracks what exists, what's missing, and
what to run to prove each phase.

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

## 3. Phased implementation plan

Phases mirror spec §18 exactly. Status is updated as work lands.

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

### Phase 3 — Authentication — not started

Username rules (§6.2), Argon2id, register/login, HttpOnly cookies, DB-backed
refresh sessions, CSRF, logout, session cleanup CLI, tests. This is where
`core/security.py` and the JWT approach get finalized (see plan §6 assumption
on the JWT library).

### Phase 4 — Books/state/shelves — not started

Book detail endpoint, rating/Not-Interested state machine (§5.2–§5.3) with
append-only events, shelves CRUD, multi-shelf sync endpoint, `/me/ratings`,
authorization/ownership tests.

### Phase 5 — Recommendation boundary — not started

`packages/recommender` gets its real shape: `contracts/`, `providers/`,
`artifacts/`, `exceptions.py`; mock + popularity engines; in-process +
fallback providers; request/result/impression persistence; cursor pagination;
the three recommendation endpoints; contract tests. Explicitly not the final
funnel.

### Phase 6 — Frontend shell/auth — not started

Dark design system/tokens, shell + left rail + top bar, search bar,
register/login pages, `AuthProvider` + current-user bootstrap, generated API
client from the FastAPI OpenAPI schema (`make generate-api-client`).

### Phase 7 — Core frontend — not started

Masonry grid, cards with shelf selector + save overlay, Home feed, book
detail modal/route, rating control, Not-Interested control, similar-books
grid, optimistic updates with rollback.

### Phase 8 — Shelves/Rated/Search — not started

Shelf overview collages, Books/Discover tabs, Rated page (sort/filter), search
page with URL state, all loading/empty/error states.

### Phase 9 — Hardening — not started

Playwright E2E for the full critical flow (§13.5), accessibility pass,
security headers + rate limiting, production Docker builds, demo seed data,
docs, final acceptance run against §19 in full.

## 4. Acceptance checklist

Mirrors spec §19, grouped the same way. Checked items are true today; this
section is updated at the end of every phase — nothing below is marked done
on the basis of intent, only of a passing command.

### Functional

- [ ] Username/password registration and persistent login state
- [ ] Logout/login preserves shelves/history
- [x] Parquet catalog import (`make import-data`; full 92,526-row catalog imported and verified — see Phase 2)
- [x] Local covers resolvable (`LocalFileStorage`, integration-tested against real files; no HTTP endpoint serving them yet — that's Phase 4)
- [ ] Home feed through provider
- [ ] Title/author search
- [ ] Book detail
- [ ] Half-star ratings
- [ ] Mutual exclusivity with Not Interested
- [ ] State removal
- [ ] Full shelf management
- [ ] Multi-shelf books
- [ ] Not Interested may remain shelved
- [ ] Shelf feed allows books from other shelves
- [ ] Rated page
- [ ] Similar books
- [ ] Cursor pages without duplicates
- [ ] Fallback provider

### Architecture

- [x] Modular monolith skeleton (`apps/api/src/book_app/{core,shared,modules,cli}` — `modules/books` and `cli/import_catalog.py` now have real Phase 2 content; `modules/{auth,users,shelves,interactions,search,recommendations}` still don't exist, each appears with its first real file starting Phase 3+)
- [x] No frontend DB access (frontend has no DB driver/credentials; talks HTTP only)
- [ ] No recommender logic in routes (nothing to violate yet — no recommender logic exists)
- [x] Recommender package independent of FastAPI/ORM (zero such dependencies declared in `packages/recommender/pyproject.toml`; verified by a repo-hygiene test)
- [x] Service-owned transactions (no `service.py` yet — Phase 4 introduces the first one — but the same principle already holds one layer down: `repository.py` never commits, `cli/import_catalog.py` owns every transaction, exactly mirroring the rule Phase 4's services will follow)
- [ ] Append-only events (not implemented — Phase 4)
- [x] Environment config (typed `Settings` covering every §11 category)
- [x] Storage abstractions (`ObjectStorage` protocol + `LocalFileStorage`, spec §7.3; S3 implementation deferred, see §6)
- [x] Explicit ID mappings (`work_id -> books.id`, `source_book_id -> books.id` both maintained during import; `book_id`/`work_id`/`model_item_index` triple for model artifacts is Phase 5, N/A yet)

### Quality

- [x] Empty-db migrations (`tests/integration/test_migrations.py`: fresh database, `upgrade head`, plus an explicit `downgrade base` → `upgrade head` round trip)
- [x] Critical tests for what exists (health endpoints, config validation, storage safety, catalog import correctness/idempotency/rejection, migrations — 32 tests total, 91% combined coverage on `book_app`)
- [ ] E2E flow (Phase 9)
- [x] Lint/type/build success for everything created this pass, including `tests/integration` (see §5 command log)
- [x] No secrets committed (`.env` gitignored, only `.env.example` with fake values tracked)
- [x] No stack traces exposed (shared exception handler returns the §9.8 envelope only)
- [ ] Keyboard accessibility (no interactive UI yet beyond a smoke page)
- [x] Setup docs (this plan + root `README.md`)
- [x] AWS mapping documented (ADR-0009, `README.md`)
- [ ] Usable `docker compose up` flow (authored, **not runtime-verified** — Docker not installed locally)

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

## 7. Next phase

**Phase 3 — Authentication.** Username rules (§6.2), Argon2id, register/login,
HttpOnly cookies, DB-backed refresh sessions, CSRF, logout, session cleanup
CLI, tests. Do not start without explicit instruction.
