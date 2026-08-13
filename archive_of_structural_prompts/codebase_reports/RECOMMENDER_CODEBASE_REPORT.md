# Bookshelf — Architectural Investigation for Recommender Design

> **Document type:** read-only codebase investigation report
> **Repository:** `bookshelf` (local-first, AWS-ready Pinterest-style book discovery app)
> **Branch / commit at time of writing:** `main` @ `0b49b93` ("Phase 9: Finishing touches"), with uncommitted frontend changes
> **Date:** 2026-08-11
> **Purpose:** give an engineer enough grounding to design a candidate-generation → ranking → re-ranking recommender pipeline without re-reading the full application codebase.
>
> **Verification standard:** every claim below was read out of the implementation (Python source, Alembic migrations, TSX, Parquet schemas, on-disk artifacts). Absences are stated explicitly rather than inferred. Assumptions and unverifiable items are flagged inline and collected in §13.G.
>
> **Legend:** ✅ implemented / present · 🟡 present but inert or placeholder · 🔴 built and unused (dead) · ❌ absent · ⚠️ risk or latent bug

---

## Table of contents

1. High-level architecture
2. User model and user profile
3. Book / item representation
4. Interaction data model
5. Recommendation surfaces
6. Current recommender abstraction / placeholder
7. Data available to a recommender request
8. Training data vs online application data
9. Session-based recommendation feasibility
10. Missing instrumentation
11. Recommender integration seams
12. Technical constraints
13. Final summary (A–G)

---

# 1. HIGH-LEVEL ARCHITECTURE

## Stack (verified)

| Layer | Technology | Evidence |
|---|---|---|
| Frontend | React 19.2, TypeScript, Vite, TanStack Query v5, react-router v8 (declarative `BrowserRouter`), Radix UI, Tailwind v4, `openapi-fetch` | `apps/web/package.json`, `apps/web/src/App.tsx` |
| API client | Generated from OpenAPI — types only, no runtime codegen | `apps/web/src/api/generated/schema.d.ts` (1565 lines), `make generate-api-client` |
| Backend | FastAPI + uvicorn, Python 3.12, sync (non-async) service/repository layers | `apps/api/src/book_app/main.py` |
| Database | PostgreSQL 17. `pg_trgm` enabled. **`vector` NOT enabled** | `infra/docker/postgres/init-extensions.sql` |
| ORM | SQLAlchemy 2.0 (`Mapped[...]` declarative), Alembic, 6 migrations, head `b61e97f578c1` | `apps/api/migrations/versions/` |
| Auth | Argon2id password hash; JWT access token in HttpOnly cookie (`sub`=user_id, `sid`=auth_session_id); SHA-256-hashed refresh token; double-submit CSRF | `apps/api/src/book_app/core/security.py`, `apps/api/src/book_app/modules/auth/dependencies.py` |
| Recommender pkg | `book_recommender` — separate uv workspace member, **zero FastAPI/SQLAlchemy imports**, enforced by a hygiene test | `packages/recommender/`, `packages/recommender/tests/test_package_boundaries.py` |
| Background jobs | **None.** No scheduler, no queue, no Redis/Celery | verified absent across repo |
| Server-side cache | **None**, except three things noted in §12 | — |

## Module layout (backend)

`apps/api/src/book_app/modules/` — each module is `api.py` / `service.py` / `repository.py` / `models.py` / `schemas.py`:

```
auth/  users/  books/  shelves/  interactions/  recommendations/  search/
```

Layering rule enforced consistently across every module read: routes parse, services own transactions and call `session.commit()`, repositories never commit.

CLI entrypoints (`apps/api/src/book_app/cli/`): `import_catalog`, `build_popularity`, `seed_demo`, `cleanup_sessions`, `export_openapi`. These are the only offline compute paths that exist.

## Important directories

```
apps/api/src/book_app/          FastAPI modular monolith
  core/                         config, database, security, covers, logging, middleware
  modules/                      auth users books shelves interactions recommendations search
  shared/                       pagination (cursors), storage, rate_limit, enums, text
  cli/                          import_catalog build_popularity seed_demo cleanup_sessions
apps/api/migrations/versions/   6 Alembic migrations
apps/web/src/                   React frontend (routes/ components/ hooks/ api/ shell/ auth/)
packages/recommender/src/book_recommender/
  contracts/  engines/  providers/  artifacts/  exceptions.py
data/raw/                       Goodreads dump + Book-Crossing (never read by the API)
data/processed/                 books.parquet, interactions.parquet, covers/
data/artifacts/                 model artifacts (popularity/latest/ currently)
data/notebooks/                 build_dataset.ipynb, inspect_goodreads.ipynb
docs/adr/                       12 ADRs (0006 = recommender boundary, 0007 = persisted batches)
docs/implementation/plan.md     phase log + risk register
tests/integration/              real-PostgreSQL integration tests
```

## Main flow — Home feed (traced, real symbols)

```
[React] HomePage (apps/web/src/routes/Home.tsx)
   └─ useInfiniteQuery → recommendationsApi.getHomeRecommendations({cursor})
        │
        ▼  GET /api/v1/recommendations/home?limit=20&cursor=…&exclude=…
[FastAPI] recommendations/api.py::get_home
   ├─ Depends(get_current_user)            ← auth cookie → JWT → auth_sessions row
   ├─ Depends(get_recommendation_provider) ← lazily built once, cached on app.state
   └─ service.get_home_recommendations(...)
        │
        ├─ context_builder.build_user_context(session, user_id)
        │     ├─ interactions_repository.get_rating_context_rows()   (≤500)
        │     ├─ interactions_repository.get_not_interested_book_ids()
        │     ├─ shelves_repository.get_all_shelved_book_ids()
        │     ├─ shelves_repository.list_shelves_with_collage()
        │     └─ interactions_repository.get_recent_events()          (≤50)
        │
        ├─ eligibility.home_exclusions(user_context)  → frozenset[book_id]
        ├─ books_repository.get_catalog_version(session)
        ├─ session.commit()   ◄── HARD RULE: read txn ends BEFORE inference
        │
        ├─ await provider.recommend(ProviderRequest(requested_count=60, …))
        │     FallbackProvider (5 s asyncio timeout, validity check)
        │       └─ InProcessProvider → asyncio.to_thread(engine.recommend)
        │             └─ MockRecommendationEngine  ← DEFAULT TODAY
        │                 (or PopularityRecommendationEngine as fallback)
        │
        ├─ books_repository.get_catalog_cards(candidate_ids)  ← defensive validation
        ├─ recommendations_repository.create_request / create_results / create_impressions
        └─ session.commit()
        │
        ▼  RecommendationPageResponse {request_id, surface, model_version, items[], next_cursor}
[React] BookMasonryGrid → BookCard
```

**Subsequent pages do not call the provider at all** — `_read_cursor_page` reads further positions out of the persisted `recommendation_results` batch (ADR-0007).

---

# 2. USER MODEL AND USER PROFILE

## A. Persistent explicit user state

### `users` — `apps/api/src/book_app/modules/users/models.py`

`id` (UUID PK), `username` (≤30), `normalized_username` (unique), `password_hash`, `account_status` (enum), `created_at`, `updated_at`.

**Absent:** no email, no display name, no avatar, no locale, no genre preferences, no settings table, no preferences column, no onboarding data. There is **no user preference/settings model anywhere in the codebase.**

### `shelves` — `apps/api/src/book_app/modules/shelves/models.py`

`id` (UUID), `user_id`, `name`, `normalized_name`, `description`, `created_at`, `updated_at`. Unique on `(user_id, normalized_name)`.

### `shelf_books` — `apps/api/src/book_app/modules/shelves/models.py`

PK `(shelf_id, book_id)`, **`added_at` TIMESTAMPTZ (populated)**, `source_surface` TEXT.

> ⚠️ **`source_surface` is dead.** The column exists, `repository.add_book()` accepts it, `service.add_book_to_shelf()` accepts it — but **no API route ever passes a value**. `sync_book_shelves` (the path the frontend actually uses, `shelves/service.py`) calls `add_book()` without it. Verified by grep: only definitions, zero call sites supplying a value. This column is always NULL.

### `user_book_states` — `apps/api/src/book_app/modules/interactions/models.py`

PK `(user_id, book_id)`. `rating_value` SMALLINT 1–10 nullable, `not_interested` BOOL, `created_at`, `updated_at`.

Two CHECK constraints: rating in 1–10; `NOT (rating_value IS NOT NULL AND not_interested)` — mutual exclusion is enforced in the database, not just in code.

**This is CURRENT STATE only** — upserted in place. `updated_at` is the only "when", and it is overwritten on every change.

Public 0.5–5.0 ↔ internal 1–10 conversion lives in `apps/api/src/book_app/modules/interactions/rating_scale.py` (`public_to_internal` / `internal_to_public`).

### `auth_sessions` — `apps/api/src/book_app/modules/auth/models.py`

`id` (UUID, **this is the `sid` JWT claim**), `user_id`, `refresh_token_hash`, `csrf_token_hash`, `created_at`, `expires_at`, `last_used_at`, `revoked_at`, `user_agent`, `client_metadata` JSONB.

Lifetime = `refresh_token_days` (default **30 days**). This is a *login/device* session, not a browsing session — important for §9.

## B. Persistent behavioral / implicit state

### `interaction_events` — `apps/api/src/book_app/modules/interactions/models.py` — append-only

Declared columns: `id`, `user_id`, `book_id`, `event_type`, `surface`, `shelf_id`, `session_id`, `recommendation_request_id`, `search_query_id`, `source_book_id`, `rank_position`, `payload` JSONB, `occurred_at`. Five indexes including `(user_id, occurred_at)` and `(book_id, occurred_at)`.

**The schema is far richer than what is actually written.** `interactions/repository.py::append_event` has this signature:

```python
def append_event(session, *, user_id, book_id, event_type, shelf_id=None, payload=None)
```

There is **no parameter** for `surface`, `session_id`, `recommendation_request_id`, `search_query_id`, `source_book_id`, or `rank_position`. Verified all 9 call sites (5 in `interactions/service.py`, 4 in `shelves/service.py`) — **those six columns are permanently NULL today.**

Only these 7 event types are ever written (`interactions/event_types.py`):

`rating_set` · `rating_changed` · `rating_removed` · `not_interested_set` · `not_interested_removed` · `shelf_book_added` · `shelf_book_removed`

All are *mutations*. **No view, click, open, or search event type exists.**

### `recommendation_requests` / `recommendation_results` / `recommendation_impressions` — `apps/api/src/book_app/modules/recommendations/models.py`

This is the most valuable behavioral asset in the system and is easy to miss.

- **`recommendation_requests`** — one row per *first-page* request: `id`, `user_id`, `surface`, `shelf_id`, `source_book_id`, `provider_name`, `model_name`, `model_version`, `catalog_version`, `fallback_used`, `context_summary` JSONB (`rated_count`/`shelf_count`/`not_interested_count`/`saved_book_count`), `generated_at`, `expires_at`.
- **`recommendation_results`** — the **full 60-candidate batch**, PK `(request_id, position)`: `book_id`, `score`, `candidate_sources` TEXT[], `reason_code`, `reason_context` JSONB, `diagnostics` JSONB.
- **`recommendation_impressions`** — **only the candidates actually delivered in a page**: `request_id`, `book_id`, `rank_position`, `page_cursor`, `shown_at`. Unique on `(request_id, book_id)`.

So a **generated-vs-delivered distinction already exists in the data.** "Impression" = delivered in a successful API response, not viewport visibility (ADR-0007, spec §8.10).

> ⚠️ **These tables are never deleted.** `expires_at` only gates *paging*; `cli/cleanup_sessions.py` touches `auth_sessions` only. Verified: no DELETE against recommendation tables anywhere. Good for training data, a table-growth concern for ops.

> ⚠️ **Latent bug worth knowing about before building on this.** `recommendations/service.py::_read_cursor_page` unconditionally inserts impressions, and `recommendation_impressions` has `UNIQUE (request_id, book_id)` with no `ON CONFLICT` handling. Re-requesting the *same cursor* (TanStack Query refetches **all** pages of an infinite query on `refetch()`) would raise `IntegrityError` → 500. There is no test covering it (`grep impression tests/integration/test_recommendations.py` → zero hits). Not runtime-confirmed (no live DB in the investigation session); the code path is unambiguous.

## C. Session-only / client-only state

| What | Where | Storage |
|---|---|---|
| Last-used shelf (quick-Save target) | `apps/web/src/hooks/useLastUsedShelf.ts` | `sessionStorage` `bookshelf:last-used-shelf-id` |
| Scroll position per page | `apps/web/src/hooks/useScrollRestoration.ts` | `sessionStorage` `bookshelf:scroll:<key>` |
| Recent searches (max 5, dedup) | `apps/web/src/hooks/useRecentSearches.ts` | `localStorage` `bookshelf:recent-searches` |
| Home guidance dismissed | `apps/web/src/routes/Home.tsx` | `localStorage` |
| Per-book user state mirror | `apps/web/src/hooks/useBookState.ts` | in-memory TanStack Query (`queryFn: skipToken`) |
| Currently viewed book | react-router URL (`/books/:bookId`) | not persisted, not reported |

**There is no client-side "books seen this session" list.** The API supports it (`?exclude=` → `recommendations/api.py::_parse_exclude`, cap 500 ids) and the TS client supports it (`apps/web/src/api/recommendations.ts`, `PageParams.exclude`) — but **every call site omits it.** Verified: `getHomeRecommendations({ cursor: pageParam })`, `getShelfRecommendations(shelfId, { cursor })`, `getSimilarRecommendations(bookId, { limit: 12 })`. The plumbing is built and unused end-to-end.

## Per-signal table

| Signal | Generated at | Stored in | Timestamp | Repeats preserved? | Efficiently queryable? |
|---|---|---|---|---|---|
| Rating set/changed/removed | `books/api.py` PUT/DELETE `/books/{id}/rating` | `user_book_states` (state) + `interaction_events` (history) | state: `updated_at` (overwritten). events: `occurred_at` | **Yes** in `interaction_events`, with `previous_rating` in `payload` | Yes — PK `(user_id, book_id)`; events indexed `(user_id, occurred_at)` |
| Not-interested set/removed | PUT/DELETE `/books/{id}/not-interested` | same | same | Yes, in events | Yes |
| Save to shelf | PUT `/books/{id}/shelves` (sync) or PUT `/shelves/{sid}/books/{bid}` | `shelf_books` + `interaction_events` | `added_at`; `occurred_at` | **Yes** in events (`shelf_book_added` carries `shelf_id`) | Yes |
| Unsave | same sync endpoint | row deleted from `shelf_books`; `shelf_book_removed` event kept | `occurred_at` | Yes | Yes |
| Recommendation impression | every rec API response | `recommendation_impressions` | `shown_at` | Yes | Yes — indexed on `request_id` |
| Recommendation candidate generated | every first-page rec request | `recommendation_results` | via parent `generated_at` | Yes | Yes |
| Book detail open / click | — | **nowhere** | — | — | — |
| Search query | — | **nowhere** (`search/service.py` writes nothing) | — | — | — |
| Dwell time / scroll depth | — | **nowhere** | — | — | — |
| Shelf visit | — | **nowhere** | — | — | — |
| Cover image load | `GET /covers/{key}` (unauthenticated) | **nowhere** | — | — | — |

## `UserRecommendationContext` — what could be populated today

Already materialized as `UserContext` in `packages/recommender/src/book_recommender/contracts/context.py`, built by `recommendations/context_builder.py::build_user_context`:

```python
UserContext(
  user_id: UUID,
  ratings: tuple[RatingSnapshot(book_id, rating_value 1-10, rated_at), ...],   # ≤500, newest first
  saved_book_ids: frozenset[int],                                              # all shelves, unbounded
  shelf_ids: tuple[UUID, ...],
  not_interested_book_ids: frozenset[int],                                     # unbounded
  recent_interactions: tuple[RecentInteractionSnapshot(event_type, book_id, occurred_at), ...],  # ≤50
  shelf_summaries: tuple[ShelfSummarySnapshot(shelf_id, name, book_count), ...],
  profile_version: str | None = None,                                          # NOTHING SETS THIS
)
```

Bounds are constants in `interactions/repository.py`: `MAX_CONTEXT_RATINGS = 500`, `MAX_CONTEXT_RECENT_INTERACTIONS = 50`.

**Available today but NOT in `UserContext`** (all readable with existing queries, zero schema change):

- `shelf_books.added_at` — *when* each book was saved (`saved_book_ids` is a bare frozenset)
- shelf → book_id mapping (only aggregate `book_count` is passed, not membership per shelf)
- shelf `description` (passed only for the *target* shelf on the shelf surface)
- `user_book_states.created_at` (first-touch, distinct from `updated_at`)
- `interaction_events.payload` (`previous_rating`, `previous_not_interested`) and `shelf_id` — `RecentInteractionSnapshot` drops both, keeping only `(event_type, book_id, occurred_at)`
- the entire impression history (`recommendation_impressions` — what this user was already shown, and at what rank)
- `users.created_at` (account age / cold-start tenure)
- `auth_sessions.id` — a stable session identifier is present in the JWT (`sid`) on every request and is simply never read by the recommendation path

**Not collected at all:** book opens, clicks, searches, dwell, scroll, any negative-implicit signal (shown-and-ignored is derivable from impressions ∖ actions, but there is no click to anchor it).

---

# 3. BOOK / ITEM REPRESENTATION

## Canonical ID

**`books.id`** — `BigInteger`, autoincrement, PostgreSQL-internal. This is the ID in every API path, response, and frontend component (`book_id`).

**`books.work_id`** — `TEXT UNIQUE NOT NULL`, the Goodreads work ID from the dataset. This is the **stable cross-system key** and the import upsert key (`books/repository.py::upsert_books_batch`, `on_conflict_do_update(index_elements=[Book.work_id])`).

`work_id` is exposed in **every** API card/detail schema (`RecommendationBookItem`, `SearchResultItem`, `ShelfBookItem`, `RatedBookItem`, `BookDetail`), even though the frontend never reads it.

## Other IDs on `books`

`source_book_id` (Goodreads *edition*-level id, TEXT), `isbn`, `isbn13`, `edition_isbns` TEXT[], `n_editions`. Per spec §5.1 / CLAUDE.md, **one row = one canonical work; there is no edition entity.**

## Full `books` schema — `apps/api/src/book_app/modules/books/models.py`

| Group | Fields |
|---|---|
| Identity | `id`, `work_id`, `source_book_id`, `isbn`, `isbn13`, `source_url` |
| Text | `title`, `title_without_series`, `description`, `description_source` |
| Author | `primary_author_name` (denormalized) + `book_authors` → `authors` |
| Taxonomy | `top_genre` + `book_genres` → `genres`; `book_catalog_shelf_tags` → `catalog_shelf_tags` |
| Series | `series_data` JSONB — **opaque source series IDs only, never names** |
| Popularity | `average_rating` NUMERIC(4,2), `ratings_count`, `text_reviews_count`, `bx_ratings`, `bx_explicit` |
| Publication | `num_pages`, `publication_year`, `publisher`, `language_code`, `format`, `is_ebook` |
| Cover | `cover_object_key`, `cover_source`; derived `has_cover` / `has_description` properties |
| Quality | `metadata_quality` FLOAT (adapter-computed completeness) |
| Lifecycle | `catalog_status` enum (ACTIVE/…), `source_metadata` JSONB (**always `{}`** — `_book_values()` hardcodes it), `created_at`, `updated_at` |

Indexes: `catalog_status`, `top_genre`, `publication_year`, `(ratings_count, average_rating)`, plus trigram/full-text GIN indexes from migration `43bc30e307a2`.

## Related tables

- `authors` (`source_author_id` unique, `name`, `normalized_name`), `book_authors` (`role`, `position`)
- `genres` / `book_genres` (`source_count`, `position`) — **only ~10 distinct genres** in the full import (per `docs/implementation/plan.md`; 246,378 links)
- `catalog_shelf_tags` / `book_catalog_shelf_tags` (`source_count`, `position`) — **173,787 tags, 1,699,225 links.** This is the high-cardinality content signal.
- **`book_source_similarities`** — `(book_id, similar_book_id, rank, source='goodreads')`, **269,276 edges**

> 🔴 **`book_source_similarities` is written at import and never read.** Verified by grep: the only non-test references are the model definition, `resolve_similarities`, and `replace_book_similarities_batch` (import-time writers). **No read query exists anywhere.** A precomputed item-item similarity graph is sitting in PostgreSQL, fully populated, completely unused — including by the "similar books" endpoint that would most obviously want it.

## Embeddings

**None.** No embedding column, no vector table, no `pgvector` extension enabled (the compose image `pgvector/pgvector:pg17` *supports* it; `init-extensions.sql` deliberately creates only `pg_trgm`). No numpy/scipy/sklearn/torch/faiss/implicit anywhere in either `pyproject.toml`.

## ID mapping: application ↔ offline data

**This is solved, and solved well.**

`ArtifactItemMapping` (`packages/recommender/src/book_recommender/artifacts/manifest.py`) is a required part of every artifact manifest:

```python
class ArtifactItemMapping(BaseModel):
    book_id: int           # PostgreSQL books.id
    work_id: str           # dataset stable id
    model_item_index: int  # row index in the model's own matrix
```

Verified on the live artifact at `data/artifacts/popularity/latest/manifest.json`: `item_count: 92524`, `catalog_version: "92524:2026-08-05T11:35:44…"`, 92,524 mapping entries, e.g. `{"book_id": 3123, "work_id": "107699", "model_item_index": 0}`.

The **offline training file is keyed by `work_id`**. Verified directly from Parquet:

```
data/processed/interactions.parquet — 775,090 rows
  user_id: int32   work_id: string   rating: int8   is_explicit: bool
```

`books.parquet` (92,526 rows) has both `work_id` and `book_id` (edition-level string).

### ID-mapping risks to flag

1. **`books.id` is not stable across a rebuilt database.** It is a plain autoincrement assigned in import order. A fresh `make import-data` into an empty database reassigns every `id`. Any artifact keyed on `book_id` alone silently corrupts on rebuild. **`work_id` is the only durable key** — this is precisely why the manifest carries all three. Any new artifact must follow the same discipline.
2. **`catalog_version`** (`books/repository.py::get_catalog_version`) is `f"{count}:{max(updated_at)}"` over ACTIVE books. It is stored on artifacts and on `recommendation_requests`, but **nothing currently compares them** — `_load_popularity_engine` never checks the manifest's `catalog_version` against the live one. The staleness-detection hook exists; the check does not.
3. **2 of 92,526 dataset rows fail import** (one `work_id == ""`, one blank title) → the catalog is 92,524 books. Training on the full 92,526-row `interactions.parquet` will produce 2 work_ids that resolve to nothing. Drop, don't crash.
4. **`interactions.parquet` has no timestamps** (schema verified: 4 columns only) and `rating == 0` means *implicit/shelved*, not negative (474,910 rows, 61.3%). CLAUDE.md forbids inventing timestamps or treating 0 as negative.
5. **Historical `user_id` (int32) must never be joined to application `users.id` (UUID).** Disjoint identity spaces by rule (spec §6.7). There is no cold-start bridge between a real user and the 83,200 historical users.
6. **`similar_books` in the source mixes ID spaces** — `books/repository.py::resolve_similarities` tries `work_id` first, then `source_book_id`, and drops the rest. ~2/3 of source edges point outside the catalog and were discarded at import.

---

# 4. INTERACTION DATA MODEL

| Signal | Exists? | Persistent? | Timestamp? | Location | Strength / semantics |
|---|---|---|---|---|---|
| **Rating** | ✅ | ✅ state + event | state `updated_at` (overwritten); event `occurred_at` | `user_book_states.rating_value`; `interaction_events` `rating_set`/`rating_changed`/`rating_removed` | Explicit, 1–10 internal. Means *read/known* — there is no separate read state. Clears not-interested atomically. |
| **Save to shelf** | ✅ | ✅ state + event | `shelf_books.added_at`; event `occurred_at` | `shelf_books`; `shelf_book_added` (carries `shelf_id`) | Strong positive. One book → many shelves. Independent of rating. |
| **Remove from shelf** | ✅ | membership deleted; **event kept** | event `occurred_at` | `shelf_book_removed` | Weak negative / correction. Only recoverable from the event log. |
| **Not interested** | ✅ | ✅ state + event | `updated_at`; `occurred_at` | `user_book_states.not_interested`; `not_interested_set`/`_removed` | Explicit negative. Mutually exclusive with rating (DB CHECK). **May remain shelved.** |
| **Recommendation impression** | ✅ | ✅ | `shown_at` | `recommendation_impressions` (`rank_position`, `page_cursor`) | Delivered-in-response, **not** viewport-verified. Joinable to `surface`/`model_version` via `request_id`. |
| **Candidate generated (not shown)** | ✅ | ✅ | parent `generated_at` | `recommendation_results` (`score`, `candidate_sources`, `reason_code`) | Full 60-item batch. Enables generated-∖-delivered analysis. |
| **Book click / detail open** | ❌ | — | — | — | **Not recorded.** `GET /books/{id}` writes nothing. |
| **Recommendation click** | ❌ | — | — | — | **Not recorded.** `request_id` is returned to the client and never sent back. No join exists between an impression and any subsequent action. |
| **Search query** | ❌ | — | — | — | **Not recorded.** `search/service.py::search_books` is pure read. No `search_queries` table (the FK-less `search_query_id` columns anticipate one). |
| **Shelf visit / lens switch** | ❌ | — | — | — | Client-side navigation only. |
| **Dwell time / scroll depth** | ❌ | — | — | — | Not recorded anywhere. |
| **Cover impression** | ❌ | — | — | — | `GET /covers/{key}` is unauthenticated and unlogged. |

## Current state vs event history — the precise answer

**The application maintains BOTH, but they are not equally complete.**

**CURRENT STATE** (`user_book_states`, `shelf_books`) — authoritative, indexed, what every read path uses.

**EVENT HISTORY** (`interaction_events`) — genuinely append-only and never updated/deleted. It **does** capture the full mutation sequence:

> "user saved book X at 14:32, removed it later, then saved it again"

is fully reconstructible: three `shelf_book_added`/`shelf_book_removed` rows with distinct `occurred_at` and `shelf_id`. Rating trajectories likewise, with `previous_rating` in `payload`.

**But the event log covers mutations only.** Every *browsing* action — opening a book, running a search, switching shelf lens, scrolling a feed — leaves no trace. So:

- **Preference history: complete.**
- **Behavior/attention history: essentially absent**, except for the delivery-side impression log.

The one asymmetry worth internalizing: you know precisely what was *shown* to a user (`recommendation_impressions`) and precisely what they *committed to* (`user_book_states`, `shelf_books`), but **nothing about what they looked at in between.**

---

# 5. RECOMMENDATION SURFACES

## 5.1 Home / "All" feed

| | |
|---|---|
| Frontend | `apps/web/src/routes/Home.tsx::HomePage`, grid via `BookMasonryGrid` |
| Endpoint | `GET /api/v1/recommendations/home` |
| Route fn | `recommendations/api.py::get_home` |
| Service | `service.get_home_recommendations(session, *, user_id, limit, cursor_str, exclude_ids, provider)` |
| Params | `limit` 1–60 (default 20), `cursor`, `exclude` (CSV, ≤500 — **never sent by the client**) |
| Response | `RecommendationPageResponse{request_id, surface, model_version, items[RecommendationBookItem], next_cursor}` |
| Item fields | `book_id, work_id, title, primary_author_name, cover_object_key, rank, score, reason_code, reason_text` |
| Pagination | Persisted batch (60) + opaque base64 cursor `{request_id, position}`, TTL 30 min |
| Exclusions | `eligibility.home_exclusions` = rated ∪ not-interested ∪ **saved-to-any-shelf** |
| Surface context | `HomeContext()` — **empty discriminator, no fields** |
| Effective logic today | `MockRecommendationEngine` — seeded shuffle of the first 2000 `books.id` |

## 5.2 Shelf feed ("lens")

| | |
|---|---|
| Frontend | `apps/web/src/routes/ShelfLens.tsx` (header) + `apps/web/src/routes/ShelfDiscover.tsx::ShelfDiscoverFeed`, at `/shelves/:shelfId/discover` |
| Endpoint | `GET /api/v1/recommendations/shelves/{shelf_id}` |
| Service | `get_shelf_recommendations(..., shelf_id, ...)` — 404s via `shelves_repository.get_owned` if not owned |
| Surface context | `ShelfContext(shelf_id, shelf_name, shelf_description, shelf_book_ids: frozenset[int])` — **the richest context that exists** |
| Exclusions | `shelf_exclusions` = rated ∪ not-interested ∪ **this shelf's books only** (other shelves stay eligible, per domain rule) |
| Extra behavior | Cards default quick-Save to *this* shelf (`BookMasonryGrid defaultShelfId`) |

## 5.3 Individual book page — similar books

| | |
|---|---|
| Frontend | `apps/web/src/components/BookDetailContent.tsx::SimilarBooksSection`, rendered in both the modal and full-page detail routes |
| Endpoint | `GET /api/v1/recommendations/books/{book_id}/similar` |
| Service | `get_similar_recommendations(..., source_book_id, ...)` |
| Surface context | `SimilarBooksContext(source_book_id: int)` — **just the ID, no title/genre/author/tags** |
| Exclusions | `similar_exclusions` = rated ∪ not-interested ∪ {source} — **saved books stay eligible** (deliberate) |
| Client params | `limit: 12`, **no cursor, no infinite scroll** — single fetch |
| Effective logic today | Random. Ignores `source_book_id` except to exclude it. `book_source_similarities` is not consulted. |

## 5.4 Search

**Not a recommendation surface.** Deliberately separate.

| | |
|---|---|
| Frontend | `apps/web/src/routes/Search.tsx` (`?q=`) + `apps/web/src/shell/SearchBar.tsx` (debounced 300 ms suggestions, `limit: 5`, same endpoint) |
| Endpoint | `GET /api/v1/search/books?q=&limit=&cursor=` |
| Logic | **Purely lexical**, in SQL. `search/repository.py::_rank_tier` — a 6-branch `CASE`: exact title → title+author combo → title prefix → title trigram (`%`) → author trigram → description full-text (`to_tsvector/plainto_tsquery`). Tiebreak: `coalesce(ratings_count,-1) DESC, id ASC`. |
| Semantic? | **No.** No embeddings, no vector search. ADR-0012 documents the trigram design. |
| Pagination | Keyset cursor on `(tier, popularity, book_id)` — **not** a persisted batch |
| Exclusions | **None.** Search deliberately shows rated/not-interested/shelved books, with `user_state` attached per result (`search/service.py`) |
| Provider | **Does not touch the recommender package at all.** `SearchContext` exists in `contracts/context.py` with **zero producers.** |

## 5.5 Other collection surfaces (non-recommended, but relevant context sources)

| Surface | Route | Endpoint | Notes |
|---|---|---|---|
| Shelf contents | `/shelves/:id/books` | `GET /shelves/{id}/books` | Keyset cursor on `added_at DESC, book_id DESC` |
| Rated books | `/rated` | `GET /me/ratings` | Sorts: `recent/highest/lowest/title/author`; filters `min_rating`, `max_rating`, `genre`. UI exposes only the first 3 sorts. |
| Shelves index | `/shelves` | `GET /shelves` | Includes ≤4 collage covers per shelf |
| Book detail | `/books/:id` | `GET /books/{id}` | Full metadata + `user_state` |

## Surface signatures as they exist today

```
home_feed  (user_id, limit, cursor, exclude_ids)                    + UserContext + HomeContext()
shelf_feed (user_id, shelf_id, limit, cursor, exclude_ids)          + UserContext + ShelfContext(id,name,description,book_ids)
similar    (user_id, source_book_id, limit, cursor, exclude_ids)    + UserContext + SimilarBooksContext(source_book_id)
search     (user_id, q, limit, cursor)                              ← NO recommender involvement
```

---

# 6. CURRENT RECOMMENDER ABSTRACTION / PLACEHOLDER

## What exists — the abstraction is real and well-formed

`packages/recommender/src/book_recommender/`:

```
contracts/
  context.py    UserContext, RatingSnapshot, ShelfSummarySnapshot, RecentInteractionSnapshot,
                HomeContext | ShelfContext | SimilarBooksContext | SearchContext
                → SurfaceContext = Annotated[..., Field(discriminator="surface")]
  provider.py   RecommendationRequest, RecommendationCandidate, RecommendationBatch,
                RecommendationProvider (Protocol, async)
  engine.py     RecommendationEngineRequest, EngineCandidate, RecommendationEngineResult,
                RecommendationEngine (Protocol, sync)
  reasons.py    ReasonCode (StrEnum, 7 codes)
engines/        mock.py · popularity.py · future_pipeline.py
providers/      in_process.py · fallback.py · remote.py
artifacts/      manifest.py (ArtifactManifest, ArtifactItemMapping) · local_storage.py
exceptions.py   RecommenderError → EngineError/EngineTimeoutError/ProviderError/IncompatibleArtifactError
```

All contract models are Pydantic `frozen=True` (immutable snapshots). Every `Protocol` is structural — a new engine needs no base class, only `def recommend(request) -> RecommendationEngineResult`.

`ReasonCode` values: `POPULAR_WITH_READERS`, `BASED_ON_HIGH_RATINGS`, `SIMILAR_TO_SAVED_BOOKS`, `SIMILAR_TO_SHELF`, `SIMILAR_TO_CURRENT_BOOK`, `SEMANTIC_QUERY_MATCH`, `EXPLORATION`. The API maps them to prose via `REASON_TEXT` in `recommendations/schemas.py`.

## Production-ready vs placeholder

| Component | Status |
|---|---|
| `RecommendationProvider` / `RecommendationEngine` protocols | ✅ Production-ready, stable |
| Typed context/request/batch contracts | ✅ Production-ready |
| `InProcessProvider` | ✅ Real — wraps sync engine in `asyncio.to_thread` |
| `FallbackProvider` | ✅ Real — 5 s `asyncio.timeout`, validity check (dupes + exclusion violations), broad `except Exception` → fallback, sets `fallback_used=True` and `diagnostics.primary_error` |
| Batch persistence + cursor paging | ✅ Real (ADR-0007) |
| Eligibility/exclusion rules | ✅ Real, correct per domain rules, enforced twice (provider + app) |
| Artifact manifest + local storage (with traversal guard) | ✅ Real |
| `PopularityRecommendationEngine` | ✅ Real but **trivial** — filters exclusions from a pre-sorted list. Not personalized. |
| `build_popularity` CLI | ✅ Real — Bayesian-shrunk score in SQL, `prior_strength=50.0`, over `ratings_count + bx_ratings + bx_explicit` vs `average_rating` |
| `MockRecommendationEngine` | 🟡 **Placeholder — and it is the configured default.** |
| `FuturePipelineRecommendationEngine` | 🟡 Raises `EngineError` on every call. Pure seam reservation. |
| `RemoteProvider` | 🟡 Raises `ProviderError`. Skeleton. |
| `SearchContext` | 🟡 Defined, **zero producers** |
| `UserContext.profile_version` | 🟡 Defined, **nothing sets it** |
| `book_source_similarities` | 🔴 Populated, **never read** |
| `catalog_version` staleness check | 🔴 Data present, comparison never performed |

## What is actually serving traffic

`.env` and `.env.example` both set `RECOMMENDATION_PROVIDER=mock`. So `recommendations/wiring.py::build_recommendation_provider` constructs:

```
FallbackProvider(
    primary  = InProcessProvider(MockRecommendationEngine(pool)),
    fallback = InProcessProvider(PopularityRecommendationEngine(ranking))
)
```

`MockRecommendationEngine` (`engines/mock.py`):

- pool = `books_repository.get_active_book_ids(limit=2000)` — **`ORDER BY Book.id ASC`**, i.e. the first 2000 books *by import order*, not the 2000 most popular
- seed = SHA-256 of `f"{request_id}:{user_id}:{surface}"` → different every request (fresh `request_id`)
- `rng.shuffle(eligible)`, take `requested_count`
- score = `1.0 - position/len` (positional, meaningless)
- `reason_code` cycles a per-surface tuple

**Every recommendation surface in the running application is currently a random draw from ~2000 books, ignoring the user entirely.** `UserContext` is built, passed in, and never read by the mock engine.

## Call chain with real symbols

```
routes/Home.tsx::HomePage
  → api/recommendations.ts::getHomeRecommendations
  → recommendations/api.py::get_home
      Depends(get_current_user)                  → modules/auth/dependencies.py
      Depends(get_recommendation_provider)       → recommendations/dependencies.py (app.state cache)
  → recommendations/service.py::get_home_recommendations
      → recommendations/context_builder.py::build_user_context
          → interactions/repository.py::get_rating_context_rows / get_not_interested_book_ids / get_recent_events
          → shelves/repository.py::get_all_shelved_book_ids / list_shelves_with_collage
      → recommendations/eligibility.py::home_exclusions
      → books/repository.py::get_catalog_version
      → session.commit()                          ◄─ transaction boundary
      → recommendations/service.py::_generate_first_page
          → providers/fallback.py::FallbackProvider.recommend
              → providers/in_process.py::InProcessProvider.recommend
                  → asyncio.to_thread → engines/mock.py::MockRecommendationEngine.recommend
          → books/repository.py::get_catalog_cards        (validation)
          → recommendations/repository.py::create_request / create_results / create_impressions
          → session.commit()
  → recommendations/api.py::_to_response  (+ REASON_TEXT lookup in schemas.py)
```

---

# 7. DATA AVAILABLE TO A RECOMMENDER REQUEST

Everything below is available **today, with no architectural change** — most of it is already inside `UserContext`.

## Home

```
Already passed:
  user_id                       UUID
  ratings                       ≤500 × (book_id, rating_value 1-10, rated_at)   newest-first
  saved_book_ids                frozenset[int]  (all shelves, unbounded)
  shelf_ids                     tuple[UUID]
  shelf_summaries               (shelf_id, name, book_count)
  not_interested_book_ids       frozenset[int]  (unbounded)
  recent_interactions           ≤50 × (event_type, book_id, occurred_at)
  hard_exclusions               rated ∪ not_interested ∪ saved
  session_exclusions            client-supplied (always empty in practice)
  catalog_version               str
  requested_count               60
  request_id                    UUID

Trivially addable (query exists, or one-line repository addition):
  shelf_books.added_at per saved book
  which shelf each saved book is on
  user_book_states.created_at (first-touch)
  users.created_at (tenure / cold-start tier)
  interaction_events.payload (previous_rating), shelf_id
  auth_sessions.id — the `sid` JWT claim, already decoded on every request
  full impression history for this user (recommendation_impressions ⋈ requests)
```

## Shelf

```
Everything from Home, plus:
  shelf_id, shelf_name, shelf_description
  shelf_book_ids                frozenset[int]  ← this shelf's full membership
  hard_exclusions = rated ∪ not_interested ∪ shelf_book_ids

Trivially addable:
  per-book added_at within this shelf (recency/ordering of shelf construction)
  aggregated genres / top_genre / catalog_shelf_tags of this shelf's books
    → the shelf's "content centroid", derivable from book_genres +
      book_catalog_shelf_tags with one join. Nothing computes this today.
  the user's other shelves' memberships (for cross-shelf contrast)
```

## Book page (similar)

```
Currently passed:
  source_book_id : int          ← literally the only field in SimilarBooksContext
  + full UserContext

NOT passed, though the request already loaded or can cheaply load it:
  the source book's title / description / primary_author_name / top_genre
    (service.py calls books_repository.get_by_id() purely as an existence check
     and DISCARDS the Book object)
  its genres, catalog_shelf_tags, authors, series_data, publication_year
  its average_rating / ratings_count / bx_ratings
  book_source_similarities rows for it — 269,276 precomputed Goodreads edges,
    already in PostgreSQL, indexed by PK (book_id, similar_book_id), ordered by `rank`
```

## Search

Search never reaches the recommender. `SearchContext(query)` exists but is unreachable — `search/api.py` has no provider dependency.

## In the database but not in the recommendation layer

1. `book_source_similarities` — 269K item-item edges, never queried
2. `book_catalog_shelf_tags` — 1.7M user-shelf-tag signals, the strongest content feature available, never queried
3. `book_genres` / `genres` — only `Book.top_genre` is ever surfaced (and only on detail); the recommender sees neither
4. `recommendation_impressions` — full delivery log, never fed back
5. `recommendation_results.candidate_sources` / `score` / `diagnostics` — written, never read back
6. `books.metadata_quality`, `description`, `num_pages`, `language_code`, `publication_year`, `n_editions` — none reach the recommender
7. `shelf_books.added_at` — timestamp collapsed to a set
8. `interaction_events` beyond the last 50 `(type, book_id, time)` triples
9. `model_versions` — the registry table is written by `build_popularity` and **read by nothing at runtime**

---

# 8. TRAINING DATA VS ONLINE APPLICATION DATA

## What exists

| Concern | Status |
|---|---|
| Book dataset | ✅ `data/processed/books.parquet` — 92,526 rows, 39 columns (schema verified) |
| **Historical interactions** | ✅ `data/processed/interactions.parquet` — **775,090 rows, 83,200 users × 92,526 works**. Schema (verified): `user_id int32, work_id string, rating int8, is_explicit bool`. **No timestamps.** `rating == 0` = implicit (474,910 rows, 61.3%); 1–10 explicit (300,180 rows). |
| Is it in PostgreSQL? | ❌ **No.** Deliberately — `docs/implementation/plan.md`: "not imported into PostgreSQL at all… stays a flat file for Phase 5's training CLIs to read directly." There is no historical-ratings table. |
| Training script | 🟡 One only: `apps/api/src/book_app/cli/build_popularity.py`. It computes in **SQL over PostgreSQL**, and **does not read `interactions.parquet`**. Nothing in the repo reads that file. |
| Artifact directory | ✅ `data/artifacts/` (`ARTIFACT_STORAGE_LOCAL_PATH`), path resolution anchored to repo root by `recommendations/artifact_paths.py::resolve_artifact_root` regardless of CWD. Currently holds `popularity/latest/{manifest.json, scores.json}`. |
| Artifact contract | ✅ `ArtifactManifest` — `model_name, model_version, catalog_version, trained_at, item_count, item_mapping[], files[]` |
| Model registry | ✅ `model_versions` table + `retire_active_versions` / `create_model_version` — at most one ACTIVE per `model_name`. **Never read at runtime.** |
| Config system | ✅ Pydantic-settings `Settings` (`core/config.py`) — `recommendation_provider: Literal["mock","popularity","future_pipeline"]`, `artifact_storage_backend: Literal["local","s3"]`, `artifact_storage_local_path`, `artifact_storage_s3_bucket` |
| S3 artifact storage | ❌ Field exists; **only `LocalArtifactStorage` is implemented** |
| Dependency management | ✅ uv workspace (`pyproject.toml` + `uv.lock`), members `apps/api` + `packages/recommender` |
| **ML dependencies** | ❌ **None.** `apps/api` has pandas + pyarrow (import only). `packages/recommender` depends on **pydantic alone**. No numpy, scipy, sklearn, torch, implicit, faiss, gensim, sentence-transformers. |
| Notebooks | 🟡 `data/notebooks/build_dataset.ipynb` (raw → processed) and `inspect_goodreads.ipynb`. Dataset construction, not model training. |
| Model loading at startup | ✅ Once per process, lazily on first recommendation request — `recommendations/dependencies.py::get_recommendation_provider` caches on `app.state.recommendation_provider`. `main.py` deliberately keeps `create_app()` DB-free. |
| Degradation | ✅ Missing/corrupt artifact → `logger.warning("popularity_artifact_unavailable")` + empty ranking. **Never fails startup.** |

## Assessment

The **artifact lifecycle infrastructure is genuinely complete**: build → manifest with three-way ID mapping → versioned storage → registry row → load-once → serve → fallback on failure. A new offline model plugs into it by writing a CLI shaped like `build_popularity.py`, an engine class, and one config value.

The **two real gaps** are (a) zero numerical/ML dependencies in either package, and (b) `interactions.parquet` — the only collaborative-filtering training data that exists — has never been read by any code. Adding numpy/scipy to `packages/recommender` would be its first non-pydantic dependency; ADR-0006 constrains it to no FastAPI/ORM imports, which numerical libraries do not violate.

Also note: `book_recommender` currently has **no artifact-loading code of its own for anything but manifests** — `_load_popularity_engine` in `wiring.py` (application side) parses `scores.json` by hand. A larger artifact format is unowned territory.

---

# 9. SESSION-BASED RECOMMENDATION FEASIBILITY

## Verdict: **C — would require substantial new tracking**

…with one significant qualification, below.

## What exists

| Requirement | Status |
|---|---|
| Sequence of viewed books | ❌ `GET /books/{id}` writes nothing |
| Clicks | ❌ No click event of any kind |
| Impressions | ✅ **`recommendation_impressions`** — request-scoped, timestamped, rank-positioned |
| Recent saves | ✅ `shelf_book_added` events with `occurred_at` (last 50 in context) |
| Recent ratings | ✅ `rating_*` events with `occurred_at`; `RatingSnapshot.rated_at` |
| Searches | ❌ Nothing persisted; recent 5 live in browser `localStorage` |
| Timestamps | ✅ Present on every persisted event |
| Current browsing context | 🟡 Server knows the *surface* of the current request; nothing about the preceding N requests |
| **Session identifier** | 🟡 **`auth_sessions.id` exists and is on every request** (JWT `sid`, decoded by `get_access_token_claims`) — but it is a **30-day login session**, not a browsing session, and `interaction_events.session_id` is never written |

## Why C and not B

A session-based generator needs a **short, ordered sequence of attention events**. What is recorded is a sparse sequence of *commitments* — a user might rate two books in an hour-long browsing session and save one. That is 3 events for a session in which 200 books were shown. The behavioral signal density is roughly two orders of magnitude too low.

`recommendation_impressions` gives you the *shown* side of the sequence with real timestamps and ranks — genuinely useful, and better than most codebases at this stage. But without a click or open event there is nothing to contrast it against: you can build "what was this user recently shown", not "what did this user recently attend to".

The `session_id` column existing on `interaction_events` means adding one is a repository-signature change, not a migration — real, but it only helps once there are events worth grouping.

## What would move it to B

Three changes, in order of value:

1. A `book_opened` event (server-side, in `books/api.py::get_book` or a small `POST /events`) carrying `book_id`, `surface`, `recommendation_request_id`, `rank_position`, `session_id`.
2. Populating `interaction_events.session_id` — needs a browsing-session id (a `sessionStorage` UUID sent in a header is the obvious minimal choice; `auth_sessions.id` is too coarse at 30 days).
3. A `search_performed` event + the `search_queries` table the FK-less `search_query_id` columns were clearly designed for.

With those, session-based retrieval becomes ordinary work. The **schema already anticipates all three** — every column needed exists and is nullable.

---

# 10. MISSING INSTRUMENTATION

Prioritized. Every "where" below lands on an existing seam.

### 1. Recommendation click / book-detail open — **REQUIRED**

**Record:** `event_type='book_opened'`, `book_id`, `surface`, `recommendation_request_id`, `rank_position`, `session_id`, `occurred_at`.
**Where:** the client already receives `request_id` and `rank` in `RecommendationBookItem` and throws both away (`BookCard.tsx::openDetail` navigates with no reporting). Either send them on `GET /books/{id}`, or add a small event endpoint. `interaction_events` already has every column.
**Why:** without it there is no positive engagement label. Impressions with no click signal cannot train a ranker, cannot compute CTR, cannot evaluate anything. **This is the single highest-value gap.**

### 2. Populate the impression↔action join — **REQUIRED**

**Record:** stamp `recommendation_request_id` + `rank_position` on `rating_set` / `shelf_book_added` when the action originates from a recommendation surface.
**Where:** `append_event()` gains parameters; `books/api.py` and `shelves/api.py` forward client-supplied `request_id`/`rank`. `shelf_books.source_surface` — the column that already exists for exactly this and is never written — is the natural home for the surface half.
**Why:** turns the existing impression log into labeled training data. Cheap: no migration, no new table.

### 3. Browsing `session_id` — **REQUIRED for session-based retrieval, otherwise nice-to-have**

**Record:** a UUID minted per tab in `sessionStorage`, sent as a header, written to `interaction_events.session_id`.
**Where:** column exists and is nullable; `append_event` needs one parameter.
**Why:** without it, events are an undifferentiated per-user stream with no sessionization boundary. Do not reuse `auth_sessions.id` — it spans 30 days.

### 4. Search queries — **REQUIRED if you want semantic/query-conditioned retrieval**

**Record:** a `search_queries` table (`id`, `user_id`, `session_id`, `query_text`, `result_count`, `occurred_at`) + a `search_performed` event; and `search_query_id` + `rank_position` on any resulting `book_opened`.
**Where:** `search/service.py::search_books` is currently pure-read and would need a transaction. Both `interaction_events.search_query_id` and `recommendation_requests.search_query_id` exist FK-less, explicitly awaiting this table.
**Why:** query→click pairs are the cheapest source of content-relevance training data, and search intent is the strongest short-term signal in a discovery app.

### 5. Save/rating timestamps in `UserContext` — **NICE TO HAVE (zero new collection)**

Already stored (`shelf_books.added_at`, `RatingSnapshot.rated_at`). `saved_book_ids` collapses the former to a set. Just widen the context snapshot. Enables recency weighting immediately.

### 6. Viewport impression tracking — **NICE TO HAVE, explicitly deferred**

Currently "impression = delivered in a response" (spec §8.10, ADR-0007). Spec §22 lists viewport tracking as a future extension. Delivery-time impressions overcount by roughly the fraction of a 20-item page never scrolled to. Fix #1 first — a click signal makes the impression definition's imprecision much less damaging.

### 7. Shelf-visit / lens-switch events — **NICE TO HAVE**

Which shelf a user browses *through* is a real interest signal. Purely client-side navigation today. Low value until #1 exists.

### Explicitly **not** recommended

Dwell time, scroll depth, hover, mouse movement. High collection cost, high noise, and pointless before a click signal exists.

---

# 11. RECOMMENDER INTEGRATION SEAMS

## The seam is already cut, and it is in the right place

```
                      ┌──────────────────────────────────────────┐
 recommendations/     │ api.py::get_home / get_shelf / get_similar│   KEEP AS IS
 (apps/api)           └──────────────────┬───────────────────────┘
                                         ▼
                      ┌──────────────────────────────────────────┐
                      │ service.py::get_*_recommendations         │   KEEP
                      │   context_builder.build_user_context      │   EXTEND (§7)
                      │   eligibility.{home,shelf,similar}_excl.  │   KEEP
                      │   session.commit()  ← txn boundary        │   KEEP (hard rule)
                      └──────────────────┬───────────────────────┘
     ══════════════════ PACKAGE BOUNDARY (no ORM/FastAPI beyond here) ══════════
                                         ▼
                      RecommendationRequest (contracts/provider.py)      KEEP
                                         ▼
                      RecommendationProvider.recommend ── FallbackProvider  KEEP
                                         ▼
                      RecommendationEngine.recommend                     ← ★ PLUG IN HERE
                      ┌──────────────────────────────────────────┐
                      │  PipelineRecommendationEngine (NEW)       │
                      │   ├─ surface configuration        NEW     │
                      │   ├─ candidate generators         NEW     │
                      │   │    CF · Content · Shelf · Pop · Session│
                      │   ├─ candidate union / dedup      NEW     │
                      │   ├─ feature enrichment           NEW     │
                      │   ├─ ranker                       NEW     │
                      │   └─ diversity / UX re-rank       NEW     │
                      └──────────────────┬───────────────────────┘
                                         ▼
                      RecommendationEngineResult (ordered, authoritative)  KEEP
     ═══════════════════════════════════════════════════════════════════════════
                                         ▼
                      get_catalog_cards validation → persist batch →
                      impressions → cursor paging → API response          KEEP
```

**`FuturePipelineRecommendationEngine` is that plug point, already reserved** (`engines/future_pipeline.py`) and already wired: `wiring.py` selects it when `RECOMMENDATION_PROVIDER=future_pipeline`, and it currently raises `EngineError` — which `FallbackProvider` catches, degrading to popularity. **You can ship a partial pipeline behind the existing fallback with zero route or service changes.**

## Keep unchanged

- Both protocols and every contract type in `contracts/`
- `eligibility.py` — application-owned product rules, correctly outside the recommender
- `InProcessProvider` (`asyncio.to_thread` off the event loop) and `FallbackProvider`
- Batch persistence, cursor paging, defensive `get_catalog_cards` validation
- The `session.commit()`-before-inference ordering
- `ArtifactManifest` / `LocalArtifactStorage` / `model_versions`
- `ReasonCode` enum + `REASON_TEXT` mapping — the existing 7 codes already cover CF, content, shelf, popularity, session-exploration, and semantic-query cases

## Must be introduced

| Component | Suggested home | Notes |
|---|---|---|
| Surface configuration | `engines/pipeline/config.py` | Which generators + weights per `SurfaceContext` variant. The discriminated union already gives you the dispatch key. |
| `CandidateGenerator` protocol | `contracts/` | Sibling to `RecommendationEngine`. Same structural-Protocol style. |
| Generator implementations | `engines/pipeline/generators/` | — |
| Candidate union / dedup / normalization | `engines/pipeline/` | Note `EngineCandidate.candidate_sources: tuple[str,...]` is **already plural** — designed for multi-generator provenance. `recommendation_results.candidate_sources` is a TEXT[] column ready to persist it. |
| Feature enrichment | `engines/pipeline/features.py` | ⚠️ **Constraint:** the engine has no DB access (ADR-0006). Item features must come from artifacts loaded at startup, or `UserContext`/`SurfaceContext` must be widened. This is the single biggest architectural decision ahead. |
| Ranker | `engines/pipeline/ranking.py` | — |
| Diversity / UX re-ranker | `engines/pipeline/rerank.py` | Must run *inside* the engine — order is authoritative once it leaves (spec §10.7); nothing downstream may re-sort. |
| Item-feature repository | `apps/api/.../books/repository.py` | New read methods (similarity edges, genres/tags in bulk) to feed contexts or build artifacts |
| Artifact loaders for real models | `packages/recommender/artifacts/` | `wiring.py` currently hand-parses `scores.json` |
| Numerical dependencies | `packages/recommender/pyproject.toml` | Currently pydantic-only |

## The one architectural tension to resolve first

ADR-0006 states the recommender **receives immutable snapshots and never queries the database**. That is clean and testable, but it means a content or CF generator cannot look up "genres of the 40 books in this shelf" at request time. Three options:

1. **Widen `ShelfContext`/`SimilarBooksContext`** — the app pre-loads item features and passes them in. Preserves the boundary; grows the contract per surface; adds DB reads inside the pre-inference transaction.
2. **Load item features from artifacts at startup** — an in-memory `book_id → features` map built offline. Preserves the boundary perfectly; costs RAM (92,524 books) and adds a rebuild dependency on catalog changes.
3. **Give the engine a read-only, ORM-free data port** — a Protocol the app implements. Bends ADR-0006's letter while keeping `packages/recommender` free of SQLAlchemy imports.

Option 2 matches the existing artifact design most closely and is the only one that keeps the pre-inference transaction untouched. Worth deciding explicitly before writing generator code, because it determines every generator's constructor signature.

---

# 12. TECHNICAL CONSTRAINTS (verified only)

**Concurrency & execution**

- Routes are `async def`; every service/repository is **synchronous SQLAlchemy**. Only `provider.recommend` is awaited. Sync DB work therefore blocks the event loop — the recommendation path is the sole exception, isolated via `asyncio.to_thread`.
- `FallbackProvider` timeout is **5.0 s** (`providers/fallback.py`). Exceeding it silently degrades to popularity with `fallback_used=True`. **This is the hard latency budget.**
- DB pool: `pool_size=5`, `max_overflow=10` → **15 connections max per container** (`core/config.py`).
- `asyncio.to_thread` uses the default executor — a shared, bounded thread pool. A CPU-bound engine will contend across concurrent requests.

**Statefulness & deployment**

- Containers must be stateless (ADR-0009, spec §17). Two things violate this today and are documented as local-only: `InMemoryFixedWindowRateLimiter` (`shared/rate_limit.py`) and the per-process `app.state.recommendation_provider`.
- The provider is built **once per process, lazily on first request** — first-request latency includes model load. With N workers, the model is loaded N times into N address spaces. **Artifact size × worker count is a real memory constraint** (the current popularity `manifest.json` alone is 8.9 MB).
- No Redis, Celery, Kafka, or Kubernetes — forbidden by `CLAUDE.md`.
- Docker Compose is authored but **never runtime-verified** (plan.md: Docker unavailable in the dev environment). `infra/aws/` contains a README only — no IaC.
- Local file dependencies: `data/artifacts` and `data/processed/covers` are bind-mounted **read-only** in compose. S3 backends are configured but unimplemented for both.

**Pagination & ordering**

- `limit` ≤ 60; `BATCH_SIZE = 60`; `BATCH_TTL_MINUTES = 30`. **The provider is asked for exactly 60 candidates and can never be asked for more without changing that constant** — so a full pipeline must produce its final top-60 in one call.
- **Order is authoritative** (spec §10.7, ADR-0006). Neither the API nor the frontend may re-sort. `BookMasonryGrid` distributes items round-robin by index into columns specifically to keep append-only order stable under infinite scroll.
- A bad ordering is **sticky for the batch's 30-minute life** — validation before persistence is the only defense (ADR-0007).
- `score` is nullable and explicitly **not a probability** (spec §20).

**Query patterns**

- `get_catalog_cards` is a single `IN` query — no N+1. `list_shelves_with_collage` is 3 queries regardless of shelf count.
- `_load_popularity_engine` parses an **8.9 MB JSON manifest + 1.8 MB scores.json into a 92,524-tuple Python list** at load. Fine once; a poor template for larger artifacts.
- `MockRecommendationEngine` holds 2,000 ints and shuffles a filtered copy per request.
- Unbounded in `UserContext`: `saved_book_ids` and `not_interested_book_ids` have **no cap** (unlike ratings ≤500 / events ≤50). A heavy user's `hard_exclusions` frozenset grows without limit and is passed to every engine call.

**API/schema expectations the frontend depends on**

- `RecommendationBookItem` must keep `book_id, work_id, title, primary_author_name, cover_object_key, rank, score, reason_code, reason_text`. `BookCardData` (structural type) requires the first five.
- `reason_text` is server-rendered prose from `REASON_TEXT` — new reason codes must be added there or the raw code leaks to the UI.
- Frontend never constructs cover paths (spec §20); it calls `GET /api/v1/covers/{key}`.
- Home eligibility guarantees every returned book is Neutral+unsaved, and `useBookState.ts` **relies on this** — it defaults to `NEUTRAL_STATE` and never fetches state for feed cards. Weakening home exclusions silently produces wrong badges.

**Ops**

- `recommendation_requests/results/impressions` grow unboundedly — no cleanup job (verified).
- Global rate limit: 600 req / 60 s per IP; max body 1 MB.
- `pg_trgm` only. Enabling `pgvector` requires a migration (the image supports it).

---

# 13. FINAL SUMMARY

## A. What the recommender currently knows about a user

Delivered in `UserContext`, per request:

- `user_id`
- Up to **500** ratings — `(book_id, rating_value 1–10, rated_at)`, newest first
- **All** saved book_ids across all shelves (frozenset, no timestamps, no shelf attribution)
- All shelf UUIDs, and `(shelf_id, name, book_count)` summaries
- **All** not-interested book_ids
- Up to **50** recent interactions — `(event_type, book_id, occurred_at)`, mutations only
- Hard exclusions (surface-specific) and session exclusions (always empty in practice)
- `catalog_version`, `request_id`, `requested_count=60`

**Not known:** anything the user looked at, searched for, or clicked; when they saved; which shelf a saved book is on; account age; session boundaries; what they were shown before.

## B. What the recommender currently knows about a book

**At candidate-generation time: only the integer `book_id`.** The engine receives no book metadata whatsoever — no title, author, genre, or popularity. `PopularityRecommendationEngine` works solely off a pre-baked `(book_id, score)` list.

**At response-serialization time** (application side, after the engine returns), `CatalogCardRow` provides: `book_id`, `work_id`, `title`, `primary_author_name`, `cover_object_key`.

**Available in PostgreSQL but not reaching the recommender at all:** description, all genres, all 1.7M catalog shelf tags, all authors, series data, `average_rating`, `ratings_count`, `bx_ratings`, `bx_explicit`, `publication_year`, `publisher`, `language_code`, `format`, `num_pages`, `n_editions`, `metadata_quality`, and **269,276 precomputed similarity edges.**

## C. Recommendation surfaces

| Surface | Endpoint | Context passed | Exclusions | Pagination |
|---|---|---|---|---|
| Home | `GET /recommendations/home` | `UserContext` + `HomeContext()` (empty) | rated ∪ NI ∪ saved-anywhere | persisted batch + cursor |
| Shelf lens | `GET /recommendations/shelves/{id}` | `UserContext` + `ShelfContext(id, name, description, book_ids)` | rated ∪ NI ∪ this-shelf | persisted batch + cursor |
| Similar books | `GET /recommendations/books/{id}/similar` | `UserContext` + `SimilarBooksContext(source_book_id)` | rated ∪ NI ∪ source | supported, unused (`limit:12`, single fetch) |
| Search | `GET /search/books` | **none — no recommender involvement** | none (states shown as badges) | keyset cursor |

## D. Existing recommendation architecture — implemented vs placeholder

**Implemented and production-quality:** the typed provider/engine boundary and every contract type; the discriminated surface-context union; eligibility rules (correct against all domain rules, enforced twice); persisted-batch pagination with opaque cursors; defensive candidate validation against the live catalog; the fallback provider with timeout and validity checks; the artifact manifest with three-way ID mapping, safe local storage, and a model-version registry; load-once-per-process provider caching with graceful degradation; the popularity build CLI with Bayesian shrinkage; the full impression/results persistence layer.

**Placeholder:** the recommendation logic itself. `RECOMMENDATION_PROVIDER=mock` in both `.env` and `.env.example`, so **every surface currently returns a seeded random shuffle of the first 2000 book IDs by insertion order, entirely ignoring `UserContext`.** `FuturePipelineRecommendationEngine` and `RemoteProvider` raise on every call. `SearchContext` and `UserContext.profile_version` have no producers.

**Dead or unwired despite being built:** `book_source_similarities` (269K edges, zero readers); `shelf_books.source_surface` (always NULL); six `interaction_events` columns (`surface`, `session_id`, `recommendation_request_id`, `search_query_id`, `source_book_id`, `rank_position`) that `append_event` cannot even set; the `exclude` query parameter (full API + client support, no call site); `model_versions` (written, never read); `catalog_version` staleness comparison (data present, check absent).

The honest summary: **the plumbing is excellent and the water was never turned on.**

## E. Biggest missing pieces

1. **No click or book-open signal.** No positive engagement label exists anywhere. Blocks ranking, evaluation, CTR, and session modeling simultaneously. *Highest priority by a wide margin.*
2. **No impression→action join.** `request_id` and `rank` are sent to the client and never returned. The impression log cannot be labeled.
3. **`interactions.parquet` (775K historical interactions) has never been read by any code.** The only CF training data in the project is an unopened file.
4. **No item features reach the recommender.** Engines see bare integers — and ADR-0006's no-DB-access rule means fixing this requires an explicit architectural decision (§11), not just a query.
5. **`book_source_similarities` unused.** 269K precomputed item-item edges would make the similar-books surface non-random immediately, with no new modeling.
6. **No content representation.** No embeddings, `pgvector` not enabled, `catalog_shelf_tags` (1.7M links — the best content signal available) never queried.
7. **No search logging.** Query→click pairs, the cheapest relevance data in a discovery app, are discarded.
8. **No browsing session identity.** `session_id` column exists; nothing writes it; `auth_sessions.id` is 30 days and too coarse.
9. **No ML dependencies.** `packages/recommender` depends on pydantic alone.
10. **No candidate-generation, union, ranking, or re-ranking abstraction.** Only the single-engine `recommend()` seam exists.

## F. Candidate-generator feasibility matrix

Judged **only** on infrastructure and data present today.

| Candidate generator | Feasibility | Data available? | Main missing requirement |
|---|---|---|---|
| **ALS / MF collaborative filtering** | **Moderate** | ✅ `interactions.parquet` — 775,090 rows, 83,200 users × 92,526 works, keyed by `work_id`; `ArtifactItemMapping` gives the `work_id → book_id` bridge | No numerical deps (numpy/scipy/implicit); no training script reads the file; **no bridge from a live app user to the historical user space** — a real user's item factors must be folded in from their own ratings at request time |
| **Item-item CF** | **Moderate** | ✅ Same co-occurrence matrix, offline-computable to a `book_id`-keyed neighbor artifact | Same missing deps/script. Item-side only, so **no user-mapping problem** — the easier of the two CF paths |
| **Content embedding similarity** | **Moderate–Difficult** | ✅ 92K descriptions, titles, authors, 10 genres, 173,787 shelf tags | No embedding model, no embedding storage (`pgvector` not enabled, no vector column), no ANN index, no artifact format for a 92K × d matrix, no encoder dependency |
| **User-profile embedding retrieval** | **Difficult** | 🟡 Ratings + saves exist to aggregate from | Requires item embeddings first (above). Then a per-request profile build — cheap, since `UserContext` already carries the ratings |
| **Shelf-conditioned retrieval** | **Easy–Moderate** | ✅ **Best-supported surface.** `ShelfContext` already carries `shelf_book_ids`, `shelf_name`, `shelf_description`; exclusions correct; `book_genres` + `book_catalog_shelf_tags` queryable | Needs an item→feature source inside the engine (see §11's tension). With a tag/genre artifact this is a tag-overlap scorer and nothing more |
| **Popularity fallback** | **Already done** | ✅ `PopularityRecommendationEngine` + `build_popularity` CLI + live artifact (92,524 items) + wired as the universal fallback | Nothing. Optionally: the unenforced `catalog_version` staleness check |
| **Session-based retrieval** | **Difficult** | ❌ Only ≤50 mutation events + delivery-time impressions | Book-open/click events, a browsing `session_id`, search logging. See §9 — schema-ready, data-absent |
| **Similar-books retrieval** | **Easy** | ✅ **269,276 `book_source_similarities` edges already in PostgreSQL**, PK-indexed, ranked; `SimilarBooksContext` and the endpoint both live | Only a read query + a way to get edges to the engine (query in the service and widen the context, or bake a neighbor artifact). **Lowest effort, highest immediate visible improvement of anything in this table.** |

## G. Questions that remain unanswered from the codebase

1. **Was `interactions.parquet` ever validated against the imported catalog?** `docs/implementation/plan.md` records the file's shape but no join test against `books.work_id`. 2 of 92,526 rows fail import — the exact overlap is unmeasured.
2. **How should a live application user be positioned in the historical CF space?** Their `user_id` is a UUID; historical users are int32 and explicitly not app users (spec §6.7). Fold-in from `UserContext.ratings` is the obvious approach, but nothing in the repo commits to it.
3. **What is the real latency budget?** Only `FallbackProvider`'s 5.0 s timeout is codified. No p50/p95 target, no APM, no timing instrumentation. ADR-0006 says the caller should log "provider, model version, request ID, latency, and fallback" — **`service.py` logs none of it.**
4. **Is `BATCH_SIZE = 60` a product decision or an expedient?** It caps the pipeline's output; no rationale beyond "larger than one page".
5. **Which of §11's three item-feature options is intended?** ADR-0006 forbids DB access from the engine; nothing states how a content generator is meant to obtain item data.
6. **Expected catalog growth?** Loading 92,524 items per worker is fine; 10× is not, with the current JSON artifact format.
7. **Is the impression definition intended to stay delivery-time?** Spec §22 lists viewport tracking as a future extension; ADR-0007 calls it "deferred, not rejected".
8. **Real user-scale data volumes?** Only the demo seed exists (8 ratings, 3 not-interested, 6 shelved for one `demo_reader` user). There is no evidence of production traffic, so cold-start is effectively the *only* regime the system has been exercised in.
9. **Is the `_read_cursor_page` duplicate-impression path actually hit in practice?** The unique-constraint violation is unambiguous in code; not executed (no running database in the investigation session) and no test covers it.
10. **AWS deployment shape?** `infra/aws/` is a README only; `artifact_storage_backend="s3"` and `cover_storage_backend="s3"` are configurable but unimplemented. How artifacts reach a running container in production is undefined.

---

## Two highest-leverage takeaways

**The similar-books surface can stop being random today** — 269,276 ranked Goodreads similarity edges are already in PostgreSQL, already indexed, and have never been read by a single line of serving code.

**The impression log is better than it looks**: `recommendation_requests` ⋈ `recommendation_results` ⋈ `recommendation_impressions` gives you surface, model version, the full 60-candidate batch with scores and sources, the delivered subset, rank position, and timestamps — retained forever, since nothing deletes them. It is missing exactly one thing to become a training set: a click.
