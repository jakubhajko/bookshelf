# Book Discovery App — Product and Engineering Specification

**Status:** Approved architecture specification  
**Primary use:** Source of truth for implementing the application with Claude Code  
**Scope:** Build the application platform first. The full modular recommendation funnel will be integrated later through the contract defined here.

---

## 1. Product objective

Build a logged-in, Pinterest-inspired book discovery application.

A registered user can:

- browse a personalized masonry home feed;
- search for books;
- open a detailed book view;
- rate books on a 0.5–5 star scale;
- mark books as Not Interested;
- create and manage shelves;
- save one book to zero, one, or several shelves;
- browse saved books inside a shelf;
- open a shelf-specific discovery feed that uses the shelf as a recommendation lens;
- browse all rated books;
- log out and later log in again without losing shelves, ratings, history, or recommendation signals.

The initial application must work before the final recommender is implemented. It must include a typed recommendation boundary plus deterministic mock and popularity fallback providers.

The full future recommendation system may contain:

1. candidate generation;
2. candidate union and deduplication;
3. ranking;
4. reranking and reorganization;
5. an ordered result batch.

Those stages belong inside the recommender package. The application must not depend on their internal structure.

---

## 2. Non-goals for the first application version

Do not implement the following in the first version:

- microservices;
- the final collaborative/content recommendation funnel;
- neural ranking models;
- online learning;
- streaming infrastructure;
- Kafka, RabbitMQ, Celery, or Redis;
- social following, messaging, likes, comments, or public profiles;
- image search;
- user-generated books or metadata editing;
- separate book-edition entities;
- a separate “read” state;
- anonymous persistent accounts;
- password recovery by email;
- user-uploaded cover images;
- admin UI;
- production AWS infrastructure provisioning.

The code must make future additions possible without prematurely implementing them.

---

## 3. Approved architecture

### 3.1 Architectural style

Use a **modular monolith in a monorepo**.

Logical boundaries must be strong, but the initial application must not be split into independent network services.

```text
React/TypeScript frontend
          |
          | HTTP/JSON
          v
FastAPI application
          |
          +---- PostgreSQL
          |
          +---- RecommendationProvider
                  |
                  +---- MockRecommendationEngine
                  +---- PopularityRecommendationEngine
                  +---- FuturePipelineRecommendationEngine
```

### 3.2 Technology choices

Backend:

- Python
- FastAPI
- Pydantic
- SQLAlchemy 2.x
- Alembic
- PostgreSQL
- psycopg 3
- Argon2id password hashing
- a focused JWT implementation
- pytest
- Ruff
- mypy
- uv with a committed lockfile

Frontend:

- React
- TypeScript
- Vite
- React Router
- TanStack Query
- Tailwind CSS
- accessible headless UI primitives
- a simple icon library
- Vitest
- React Testing Library
- Playwright for critical end-to-end flows

Infrastructure:

- Docker
- Docker Compose
- GitHub Actions
- future AWS mapping:
  - frontend: S3 + CloudFront
  - API: ECS Fargate + Application Load Balancer
  - database: RDS PostgreSQL
  - covers: S3 + CloudFront
  - model artifacts: S3
  - images: ECR
  - secrets: Secrets Manager or Parameter Store
  - logs: CloudWatch

### 3.3 AWS-ready means

- stateless API containers;
- environment-based configuration;
- no absolute machine-specific paths;
- explicit migrations;
- health checks;
- structured stdout logs;
- storage abstractions;
- versioned model artifacts;
- no committed secrets.

It does not mean AWS resources must be provisioned in the first version.

---

## 4. Repository structure

```text
book-recommender/
├── apps/
│   ├── api/
│   │   ├── pyproject.toml
│   │   ├── alembic.ini
│   │   ├── migrations/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── src/book_app/
│   │       ├── main.py
│   │       ├── core/
│   │       ├── modules/
│   │       ├── shared/
│   │       └── cli/
│   └── web/
│       ├── package.json
│       ├── tsconfig.json
│       ├── vite.config.ts
│       ├── Dockerfile
│       ├── public/
│       └── src/
├── packages/
│   └── recommender/
│       ├── pyproject.toml
│       ├── tests/
│       └── src/book_recommender/
├── scripts/
│   ├── data_import/
│   ├── development/
│   └── model_management/
├── tests/
│   ├── integration/
│   └── end_to_end/
├── data/
│   ├── raw/
│   ├── processed/
│   └── sample/
├── docs/
│   ├── architecture/
│   ├── api/
│   ├── adr/
│   └── implementation/
├── infra/
│   ├── docker/
│   └── aws/
├── docker-compose.yml
├── Makefile
├── .env.example
├── .gitignore
├── CLAUDE.md
└── README.md
```

### 4.1 Backend module layout

```text
book_app/
├── main.py
├── core/
│   ├── config.py
│   ├── database.py
│   ├── logging.py
│   ├── security.py
│   ├── middleware.py
│   ├── dependencies.py
│   └── exceptions.py
├── modules/
│   ├── auth/
│   ├── users/
│   ├── books/
│   ├── shelves/
│   ├── interactions/
│   ├── search/
│   └── recommendations/
├── shared/
│   ├── schemas/
│   ├── pagination/
│   ├── enums.py
│   ├── types.py
│   └── storage/
└── cli/
    ├── import_catalog.py
    ├── seed_demo.py
    ├── build_popularity.py
    ├── export_training_data.py
    └── cleanup_sessions.py
```

Each domain module normally contains:

```text
module/
├── api.py
├── schemas.py
├── models.py
├── repository.py
├── service.py
├── dependencies.py
└── exceptions.py
```

Only create files that have a real responsibility.

### 4.2 Layer ownership

`api.py`:

- HTTP routes;
- request parsing;
- status codes;
- dependency injection;
- response schemas;
- HTTP exception mapping.

`service.py`:

- use cases;
- domain invariants;
- authorization;
- transaction boundaries;
- event creation;
- orchestration.

`repository.py`:

- SQLAlchemy queries;
- persistence;
- no HTTP concerns;
- no commits.

`models.py`:

- SQLAlchemy persistence models only.

`schemas.py`:

- Pydantic request and response types;
- never expose ORM objects directly.

Dependency direction:

```text
routes -> services -> repositories/provider interfaces -> infrastructure
```

The recommender package must not import FastAPI or application ORM models.

---

## 5. Domain model and invariants

### 5.1 Canonical book

The dataset is already deduplicated to work level.

**One catalog row equals one recommendable book.**

Do not create a work/edition hierarchy.

### 5.2 User-book preference state

Each user-book pair can be:

Neutral:

```text
rating_value = NULL
not_interested = FALSE
```

Rated:

```text
rating_value in [1, 10]
not_interested = FALSE
```

Not Interested:

```text
rating_value = NULL
not_interested = TRUE
```

Invalid:

```text
rating_value IS NOT NULL
AND not_interested = TRUE
```

Prevent the invalid state in service logic and a database check constraint.

There is no separate read state. A rating means the user has read or knows the book.

Store ratings as integer 1–10. Display as 0.5–5.0 stars.

### 5.3 State transitions

Set rating:

- verify user and book;
- atomically clear Not Interested;
- set rating;
- append event;
- preserve shelf memberships.

Change rating:

- update current value;
- append `rating_changed` with old and new values.

Remove rating:

- clear rating;
- return to Neutral;
- append `rating_removed`;
- preserve shelves.

Set Not Interested:

- atomically clear any rating;
- set Not Interested;
- append event with previous rating if present;
- preserve shelves.

Remove Not Interested:

- return to Neutral;
- append event.

A Not Interested book may remain in shelves.

### 5.4 Shelves

A shelf:

- belongs to one user;
- has a name and optional description;
- contains zero or more books;
- can be renamed or deleted;
- acts as an organizational collection and recommendation context.

A book may belong to zero, one, or many shelves.

Shelf names are unique per user after Unicode normalization and case folding.

Deleting a shelf deletes current memberships but leaves ratings, Not Interested states, other shelves, books, and historical events intact.

### 5.5 Eligibility

Home excludes:

- rated books;
- Not Interested books;
- books saved to any shelf;
- inactive books;
- books already returned in the current feed session.

Shelf discovery excludes:

- books already in that shelf;
- rated books;
- Not Interested books;
- inactive books.

Books saved to other shelves remain eligible.

Similar books excludes:

- source book;
- rated books;
- Not Interested books;
- inactive books.

Saved books may appear.

Search keeps rated, saved, and Not Interested books visible with state badges.

---

## 6. Authentication and identity

### 6.1 Accounts

Registration:

- username;
- password;
- password confirmation.

Login:

- username;
- password.

Persistent user UUID owns all shelves, state, events, and profiles. Logout revokes only the current session.

### 6.2 Username rules

- 3–30 visible characters;
- Unicode letters, digits, underscore, and hyphen;
- reject leading/trailing whitespace;
- reject control/invisible formatting characters;
- preserve original form;
- normalize with Unicode normalization and case folding;
- enforce case-insensitive uniqueness;
- immutable in version one.

Reserve obvious system names such as `admin`, `api`, `auth`, `login`, `logout`, `register`, `me`, `system`, `support`, and `demo`.

### 6.3 Passwords

- 10–128 characters;
- Argon2id;
- never log or return;
- no email recovery in version one;
- optional development CLI reset.

### 6.4 Sessions

Use short-lived access tokens plus revocable database-backed refresh sessions.

Cookies:

- HttpOnly for access and refresh;
- Secure in production;
- SameSite=Lax unless reviewed deployment requirements dictate otherwise;
- credentials included by frontend.

Recommended defaults:

- access: about 15 minutes;
- refresh session: about 30 days.

Store only refresh token hashes.

Each login creates a separate session. Logout revokes the current session.

### 6.5 CSRF

Implement session-bound CSRF protection for POST/PUT/PATCH/DELETE:

- readable CSRF token;
- frontend sends `X-CSRF-Token`;
- backend verifies it;
- rotate when appropriate.

Do not rely on CORS alone.

### 6.6 Authorization

Personalized routes infer the current user from auth. Do not accept arbitrary user IDs from the frontend. Verify shelf ownership and user resource ownership on the backend.

### 6.7 Historical users

Users in `interactions.parquet` are anonymous training identities. Do not import them into registered application users.

---

## 7. Source dataset contract

### 7.1 `books.parquet`

- 92,526 rows;
- one row per canonical work;
- unique string key `work_id`;
- 39 columns.

Identity:

- `work_id`
- `isbn`
- `isbn13`
- `book_id`
- `url`
- `image_url`

Text:

- `title`
- `title_without_series`
- `description`
- `has_description`
- `description_source`

Authors:

- `authors`
- `author_ids`
- `author_roles`
- `primary_author`

Taxonomy:

- `genres`
- `genre_counts`
- `top_genre`
- `shelves`
- `shelf_counts`
- `n_shelves`

Graph:

- `similar_books`
- `series`

Numeric:

- `average_rating`
- `ratings_count`
- `text_reviews_count`
- `num_pages`
- `publication_year`

Publishing:

- `publisher`
- `language_code`
- `format`
- `is_ebook`

Covers:

- `has_cover`
- `cover_file`
- `cover_source`

Rollup:

- `n_editions`
- `edition_isbns`
- `bx_ratings`
- `bx_explicit`

### 7.2 `interactions.parquet`

- 775,090 rows;
- 83,200 historical users;
- 92,526 works;
- all work IDs join to books;
- no duplicate `(user_id, work_id)`;
- no timestamps.

Columns:

- `user_id` int32
- `work_id` string
- `rating` int8
- `is_explicit` bool

Rating 0 is implicit, not negative. Rating 1–10 is explicit.

Do not invent timestamps or implement temporal evaluation from this source.

### 7.3 Covers

Local `covers/` contains files named `<isbn>.jpg`, joined through `cover_file`.

Store only a `cover_object_key`, not an absolute path. Implement local and S3 storage backends.

### 7.4 Import boundary

Dataset adapter produces canonical typed records. Raw Parquet column knowledge stays inside the adapter.

Import must be:

- explicit;
- idempotent;
- batched;
- validated;
- dry-run capable;
- report generating;
- independent of Parquet row order;
- upserted by `work_id`;
- non-destructive by default.

Do not import during API startup.

### 7.5 IDs

PostgreSQL creates internal BIGINT `books.id`.

Preserve:

```text
work_id -> book_id
```

Every model artifact explicitly stores:

```text
book_id
work_id
model_item_index
```

---

## 8. PostgreSQL schema

Use PostgreSQL in development, integration tests, and production. Do not substitute SQLite.

Use `TIMESTAMPTZ` in UTC.

Enable `pg_trgm`; optionally enable `vector` for later use.

### 8.1 `users`

```text
id                  UUID PK
username            varchar(30)
normalized_username varchar(80) UNIQUE
password_hash       text
account_status      ACTIVE|DISABLED|PENDING_DELETION
created_at          timestamptz
updated_at          timestamptz
```

### 8.2 `auth_sessions`

```text
id                  UUID PK
user_id             UUID FK users ON DELETE CASCADE
refresh_token_hash  text UNIQUE
csrf_token_hash     text
created_at          timestamptz
expires_at          timestamptz
last_used_at        timestamptz nullable
revoked_at          timestamptz nullable
user_agent          text nullable
client_metadata     jsonb default {}
```

Indexes on user/revoked/expiry and expiry.

### 8.3 `books`

```text
id                       BIGSERIAL PK
work_id                  text UNIQUE NOT NULL
source_book_id           text nullable
isbn                     text nullable
isbn13                   text nullable
source_url               text nullable
source_image_url         text nullable
title                    text NOT NULL
title_without_series     text nullable
description              text nullable
description_source       text nullable
primary_author_name      text nullable
top_genre                text nullable
series_data              jsonb nullable
average_rating           numeric(4,2) nullable
ratings_count            integer nullable
text_reviews_count       integer nullable
num_pages                integer nullable
publication_year         smallint nullable
publisher                text nullable
language_code            text nullable
format                   text nullable
is_ebook                 boolean nullable
cover_object_key         text nullable
cover_source             text nullable
n_editions               integer nullable
edition_isbns            text[] nullable
bx_ratings               integer nullable
bx_explicit              integer nullable
catalog_status           ACTIVE|HIDDEN|INVALID
metadata_quality         real nullable
source_metadata          jsonb default {}
created_at               timestamptz
updated_at               timestamptz
```

Derive `has_cover` and `has_description`.

Indexes:

- unique work ID;
- title/author trigram;
- full-text search;
- catalog status;
- top genre;
- publication year;
- popularity fields.

### 8.4 Catalog relationships

`authors`:

```text
id, source_author_id, name, normalized_name, created_at
```

`book_authors`:

```text
book_id, author_id, role, position
```

`genres`:

```text
id, name, normalized_name UNIQUE
```

`book_genres`:

```text
book_id, genre_id, source_count, position
```

`catalog_shelf_tags`:

```text
id, name, normalized_name UNIQUE
```

`book_catalog_shelf_tags`:

```text
book_id, tag_id, source_count, position
```

`book_source_similarities`:

```text
book_id, similar_book_id, rank, source
```

### 8.5 `user_book_states`

```text
user_id         UUID FK
book_id         BIGINT FK
rating_value    SMALLINT nullable
not_interested  boolean default false
created_at      timestamptz
updated_at      timestamptz
PK (user_id, book_id)
```

Checks:

- rating is null or 1–10;
- rating and Not Interested cannot coexist.

### 8.6 `shelves`

```text
id               UUID PK
user_id          UUID FK
name             varchar(100)
normalized_name  varchar(200)
description      text nullable
created_at       timestamptz
updated_at       timestamptz
UNIQUE (user_id, normalized_name)
```

### 8.7 `shelf_books`

```text
shelf_id       UUID FK
book_id        BIGINT FK
added_at       timestamptz
source_surface nullable
PK (shelf_id, book_id)
```

### 8.8 `search_queries`

```text
id, user_id, query_text, normalized_query, mode, created_at, metadata
```

### 8.9 `interaction_events`

Append-only:

```text
id                         BIGSERIAL PK
user_id                    UUID FK
book_id                    BIGINT nullable
event_type                 enum/text
surface                    enum/text nullable
shelf_id                   UUID nullable
session_id                 UUID nullable
recommendation_request_id  UUID nullable
search_query_id            UUID nullable
source_book_id             BIGINT nullable
rank_position              integer nullable
payload                    jsonb default {}
occurred_at                timestamptz
```

Index user/event ID, user/time, book/time, event/time, request ID, and search ID.

### 8.10 Recommendation persistence

`model_versions`:

```text
id, model_name, model_version, catalog_version,
provider_name, status, manifest, created_at, activated_at
```

`recommendation_requests`:

```text
id, user_id, surface, shelf_id, source_book_id, search_query_id,
provider_name, model_name, model_version, catalog_version,
fallback_used, context_summary, generated_at, expires_at
```

`recommendation_results`:

```text
request_id, position, book_id, score,
candidate_sources, reason_code, reason_context, diagnostics
PK (request_id, position)
UNIQUE (request_id, book_id)
```

`recommendation_impressions`:

```text
id, request_id, book_id, rank_position, page_cursor, shown_at
UNIQUE (request_id, book_id)
```

In version one, impression means delivered in a successful API response.

### 8.11 Migration order

1. extensions/enums;
2. users/sessions;
3. catalog core;
4. catalog relationships;
5. user-book state;
6. shelves;
7. search/events;
8. model/recommendation registry;
9. results/impressions;
10. search indexes;
11. vector/profile tables later.

Test migrations against an empty PostgreSQL database.

---

## 9. API contract

Base:

```text
/api/v1
```

### 9.1 Authentication

```text
POST /auth/register
POST /auth/login
POST /auth/refresh
POST /auth/logout
GET  /auth/me
POST /auth/change-password
```

### 9.2 Books and preference state

```text
GET    /books/{book_id}
PUT    /books/{book_id}/rating
DELETE /books/{book_id}/rating
PUT    /books/{book_id}/not-interested
DELETE /books/{book_id}/not-interested
PUT    /books/{book_id}/shelves
```

Public rating body:

```json
{"rating": 4.5}
```

Allowed values are exact half steps from 0.5 to 5.0. Convert to 1–10 internally.

Shelf sync body:

```json
{"shelf_ids": ["uuid-1", "uuid-2"]}
```

This atomically replaces the current user’s shelf memberships for that book after ownership validation.

### 9.3 Shelves

```text
GET    /shelves
POST   /shelves
GET    /shelves/{shelf_id}
PATCH  /shelves/{shelf_id}
DELETE /shelves/{shelf_id}
GET    /shelves/{shelf_id}/books
PUT    /shelves/{shelf_id}/books/{book_id}
DELETE /shelves/{shelf_id}/books/{book_id}
```

Shelf list includes enough cover data for a collage without N+1 frontend requests.

### 9.4 Rated books

```text
GET /me/ratings
```

Cursor pagination and sort/filter options:

- recent;
- highest;
- lowest;
- title;
- author;
- rating range;
- optional genre.

### 9.5 Recommendations

```text
GET /recommendations/home
GET /recommendations/shelves/{shelf_id}
GET /recommendations/books/{book_id}/similar
```

Return:

- request ID;
- surface;
- model version;
- ordered enriched books;
- rank;
- optional score;
- reason code/text;
- opaque next cursor.

The frontend never computes recommendation order.

### 9.6 Search

```text
GET /search/books?q=...
```

Initial ranking:

1. exact title;
2. exact title/author combination;
3. title prefix;
4. trigram fuzzy title;
5. author;
6. description full text;
7. popularity tie-break.

Search keeps prior user states visible.

### 9.7 Health

```text
GET /health/live
GET /health/ready
```

### 9.8 Errors

```json
{
  "error": {
    "code": "SHELF_NOT_FOUND",
    "message": "The requested shelf does not exist.",
    "details": {},
    "request_id": "uuid"
  }
}
```

Never expose stack traces or raw database errors.

### 9.9 Cursor feeds

On initial recommendation request:

1. generate a larger ordered batch;
2. persist it;
3. return first page;
4. persist delivered impressions;
5. encode request ID and next position in an opaque cursor.

Subsequent pages read the same batch.

---

## 10. Recommender contract

### 10.1 Boundary

The app sees one typed provider. It does not know candidate generators, ranking, or reranking internals.

Recommender package:

```text
contracts/
providers/
artifacts/
exceptions.py
```

No FastAPI or ORM imports.

### 10.2 Engine protocol

```python
class RecommendationEngine(Protocol):
    def recommend(
        self,
        request: RecommendationEngineRequest,
    ) -> RecommendationEngineResult:
        ...
```

Implement:

- mock;
- popularity;
- future pipeline adapter placeholder.

### 10.3 Provider protocol

```python
class RecommendationProvider(Protocol):
    async def recommend(
        self,
        request: RecommendationRequest,
    ) -> RecommendationBatch:
        ...
```

Implement:

- in-process provider;
- fallback provider;
- remote-provider interface/skeleton.

Blocking work runs outside the async event loop.

### 10.4 Typed contexts

Use a discriminated union:

- HomeContext;
- ShelfContext with shelf IDs/books/name/description;
- SimilarBooksContext with source book;
- SearchContext with query.

Avoid unrelated nullable fields in one context object.

### 10.5 User context

Provide immutable snapshots of:

- ratings with integer values and timestamps;
- saved books and shelf IDs;
- Not Interested IDs;
- bounded recent interactions;
- shelf summaries;
- optional derived profile version.

### 10.6 Request

Includes:

- request ID;
- user context;
- surface context;
- requested count;
- hard exclusions;
- session exclusions;
- catalog version.

### 10.7 Result

Each candidate contains:

- internal book ID;
- optional score;
- candidate sources;
- reason code;
- reason context;
- diagnostics.

Batch contains:

- model name/version;
- catalog version;
- generated time;
- ordered candidates;
- diagnostics.

Order is authoritative. Scores are not assumed to be probabilities.

### 10.8 Exclusions

The application owns product eligibility and sends hard exclusions. The recommender obeys them. The API validates output defensively.

### 10.9 Reason codes

Use stable codes:

- `POPULAR_WITH_READERS`
- `BASED_ON_HIGH_RATINGS`
- `SIMILAR_TO_SAVED_BOOKS`
- `SIMILAR_TO_SHELF`
- `SIMILAR_TO_CURRENT_BOOK`
- `SEMANTIC_QUERY_MATCH`
- `EXPLORATION`

API maps codes to prose.

### 10.10 Fallback

```text
configured primary
    -> failure/timeout/invalid
popularity fallback
    -> failure
503
```

Log provider, model version, request ID, latency, and fallback.

### 10.11 Mock provider

Must:

- support every surface;
- respect exclusions;
- return unique active books;
- be deterministic in tests;
- return realistic sources/reasons;
- support optional controlled failure/latency;
- not merely return first rows.

### 10.12 Popularity provider

Precompute an artifact from:

- `bx_ratings`;
- `bx_explicit`;
- external rating count;
- average rating;
- support adjustment.

It is a fallback and baseline, not the final recommender.

### 10.13 Artifacts

Immutable manifest includes:

- model name/version;
- catalog version;
- trained time;
- item count;
- item mapping;
- model/config files.

Implement local and S3 storage abstractions. Load once at startup. Reject incompatible mappings and activate fallback.

---

## 11. Runtime workflows

Use synchronous SQLAlchemy with request-scoped sessions.

Repositories never commit. Services own transactions.

Preference/shelf mutations update current state and append events in one transaction.

Do not hold a DB transaction open during recommendation inference.

Recommendation workflow:

1. read context;
2. build immutable snapshot;
3. end read transaction;
4. call provider;
5. validate result;
6. add fallback candidates if needed;
7. persist request and batch;
8. enrich visible page;
9. persist delivered impressions;
10. return.

No task queue in version one.

CLI commands:

- import catalog;
- seed demo;
- build popularity;
- export training data;
- clean sessions;
- data-quality report.

Typed environment configuration must include database, JWT/session, cookie, CORS, CSRF, cover storage, artifact storage, provider, logs, and demo toggles.

---

## 12. Frontend specification

### 12.1 Visual direction

Dark-first, minimalist, image-led, and content-dense.

Use design tokens for background, surfaces, text, borders, accent, radii, sidebar, and top bar.

First version is dark only, but tokens permit a future light theme.

### 12.2 Shell

Desktop:

- fixed narrow left rail;
- sticky top bar;
- large search field;
- avatar menu;
- scrollable content.

Left rail has exactly:

1. Home
2. Shelves
3. Rated

Mobile uses bottom navigation.

Profile menu:

- username;
- account;
- change password;
- logout.

### 12.3 Routes

```text
/register
/login
/
/search?q=...
/books/:bookId
/shelves
/shelves/:shelfId/books
/shelves/:shelfId/discover
/rated
/account
```

### 12.4 Home

- masonry feed;
- shelf-lens row under top bar;
- For You + user shelves;
- infinite scroll;
- stable rendered order;
- skeletons;
- page retry;
- scroll restoration.

New users receive fallback feed and a subtle guidance message. No forced onboarding.

### 12.5 Grid

Responsive masonry:

- wide desktop 7–8;
- desktop 5–6;
- tablet 3–4;
- mobile 2;
- narrow 1–2.

Preserve cover ratio. Missing covers use title/author placeholders.

### 12.6 Card

Below cover:

- title, maximum two lines;
- primary author, one muted line.

Hover/focus overlay:

- top-left shelf selector;
- top-right Save/Saved.

Shelf selector:

- searchable;
- multi-select;
- create shelf;
- shelf discovery context is default target;
- remember last-used shelf during session.

Touch controls remain usable without hover.

State badges appear where relevant.

### 12.7 Detail

Desktop route-backed modal over prior page. Mobile full-screen. Direct route renders full page.

Show:

- cover;
- title/authors;
- description;
- year/pages/publisher/language/format/series;
- useful genres;
- external rating;
- user rating;
- shelf controls;
- Not Interested;
- similar grid.

Rating is five stars with ten accessible half-step values and remove action.

Not Interested confirms if clearing a rating and never removes shelves.

### 12.8 Shelves

Overview uses board-like cover collages, name, count, and updated order.

Create, rename, edit description, and delete.

Shelf detail tabs:

- Books;
- Discover.

Discover uses shelf lens, excludes current shelf contents, allows books from other shelves, and defaults Save to current shelf.

### 12.9 Rated

Grid of rated books with user rating.

Sort:

- recent;
- highest;
- lowest;
- title;
- author.

Filters:

- rating range;
- optional genre.

### 12.10 Search

Large sticky bar.

- debounced suggestions;
- query in URL;
- title/author/recent suggestions;
- masonry results;
- user-state badges;
- no technical mode control in version one.

### 12.11 State management

Use:

- TanStack Query;
- React Router;
- local UI state;
- minimal AuthProvider.

No Redux.

Centralized query keys.

Optimistic updates for rating, rejection, and shelf membership, with rollback and authoritative invalidation.

### 12.12 Accessibility

- alt text;
- focus equivalents for hover;
- accessible icon labels/tooltips;
- modal focus trap;
- Escape;
- accessible star input;
- adequate contrast;
- reduced motion;
- mutation announcements.

---

## 13. Testing and quality

### 13.1 Backend unit tests

Cover:

- username normalization;
- auth/session/CSRF;
- rating transitions;
- Not Interested transitions;
- shelf ownership/uniqueness;
- multi-shelf sync;
- exclusions;
- provider fallback;
- result validation;
- cursor logic;
- error mapping.

### 13.2 Recommender contract tests

All providers must:

- return unique IDs;
- respect exclusions;
- respect count;
- support deterministic tests;
- return valid metadata/reasons;
- handle empty users/shelves;
- raise typed errors;
- remain independent of ORM/FastAPI.

### 13.3 Integration tests

Real PostgreSQL.

Cover:

- empty-db migrations;
- sample Parquet import;
- auth lifecycle and persistence;
- ownership protection;
- atomic preference events;
- multiple shelves;
- recommendation persistence/pagination;
- lexical search;
- local covers.

### 13.4 Frontend tests

Cover:

- half-star input;
- shelf selector;
- optimistic rollback;
- badges;
- logout;
- route-backed detail;
- shelf tabs;
- empty/error states.

### 13.5 E2E

Critical flow:

1. register;
2. login;
3. browse;
4. open;
5. rate;
6. verify Rated;
7. create shelf;
8. save to multiple shelves;
9. open shelf Discover;
10. reject another book;
11. logout;
12. login;
13. verify persistence.

### 13.6 Quality commands

Backend:

```text
ruff format --check
ruff check
mypy
pytest --cov
```

Frontend:

```text
npm run lint
npm run typecheck
npm run test
npm run build
```

Use a 75% overall backend/recommender coverage floor while explicitly covering all critical rules.

CI must apply migrations to empty PostgreSQL.

---

## 14. Security

Implement:

- Argon2id;
- hashed refresh tokens;
- short access tokens;
- revocation;
- CSRF;
- exact credentialed CORS;
- secure cookies by environment;
- security headers;
- request limits;
- SQL parameterization;
- ownership checks;
- no sensitive logs;
- no stack traces;
- safe local cover paths;
- dependency lockfiles;
- startup failure for insecure production defaults.

Provide a pluggable auth rate-limit boundary. Per-process limiting is acceptable locally; document AWS WAF/shared production limiting.

---

## 15. Observability and failure handling

Structured JSON logs to stdout.

Every request has a request ID.

Log status, latency, authenticated user ID, provider, model version, fallback, recommendation latency, and import summaries without secrets.

Frontend:

- root boundary;
- route errors;
- inline retries;
- mutation toasts;
- optimistic rollback;
- one refresh attempt;
- login redirect after refresh failure.

Expose live/ready health endpoints.

Optional lightweight metrics:

- request counts/latency;
- errors;
- login failures;
- recommender latency;
- fallback rate;
- batch size;
- import counts.

---

## 16. Local development

Docker Compose services:

- db;
- api;
- web.

Use PostgreSQL compatible with future pgvector.

Mount:

- DB volume;
- covers read-only;
- model artifacts read-only.

Provide commands:

```text
make setup
make dev
make up
make down
make logs
make migrate
make import-data
make import-data-dry-run
make seed-demo
make build-popularity
make test
make lint
make typecheck
make e2e
make generate-api-client
```

Create a development demo user with representative shelves, ratings, saves, and rejections. Never enable demo credentials in production.

Generate frontend types/client from FastAPI OpenAPI.

---

## 17. AWS design

Future mapping:

- web build -> S3/CloudFront;
- API image -> ECR/ECS Fargate/ALB;
- PostgreSQL -> RDS;
- covers -> S3/CloudFront;
- artifacts -> S3;
- secrets -> Secrets Manager/SSM;
- logs -> CloudWatch.

Migrations run as a one-off deployment task, not destructively on every startup.

Create an AWS architecture README but do not provision full infrastructure in version one.

---

## 18. Implementation phases

### Phase 0 — Inspect and plan

- inspect repo;
- read specification;
- create `docs/implementation/plan.md`;
- map gaps, risks, checklist, validation commands;
- create initial ADRs.

### Phase 1 — Foundations

- monorepo;
- uv workspace;
- frontend setup;
- config/logging;
- Docker Compose;
- CI skeleton;
- health endpoints.

### Phase 2 — Database/catalog

- models/migrations;
- import adapter;
- sample Parquet fixture;
- importer/report;
- local cover storage;
- search indexes;
- integration tests.

### Phase 3 — Authentication

- username;
- registration/login;
- cookies/refresh;
- CSRF;
- logout;
- session cleanup;
- tests.

### Phase 4 — Books/state/shelves

- book detail;
- ratings;
- Not Interested;
- events;
- shelves;
- multi-shelf sync;
- Rated endpoint;
- authorization tests.

### Phase 5 — Recommendation boundary

- contracts;
- mock;
- popularity;
- fallback;
- request/result persistence;
- cursors;
- recommendation endpoints;
- tests.

Do not implement the final funnel.

### Phase 6 — Frontend shell/auth

- dark design system;
- shell/navigation;
- search bar;
- auth pages;
- current-user bootstrap;
- generated client.

### Phase 7 — Core frontend

- masonry;
- cards;
- save selector;
- home;
- detail;
- rating;
- rejection;
- similar;
- optimistic updates.

### Phase 8 — Shelves/Rated/Search

- shelf overview/collages;
- tabs;
- Rated;
- search;
- URL state;
- all states.

### Phase 9 — Hardening

- E2E;
- accessibility;
- security headers;
- production Docker builds;
- demo;
- docs;
- final acceptance run.

After each phase:

1. run tests;
2. run lint/type checks;
3. update checklist;
4. report files and issues;
5. never claim success if commands fail.

---

## 19. Acceptance criteria

Functional:

- username/password registration and persistent login state;
- logout/login preserves shelves/history;
- Parquet catalog import;
- local covers;
- home feed through provider;
- title/author search;
- book detail;
- half-star ratings;
- mutual exclusivity with Not Interested;
- state removal;
- full shelf management;
- multi-shelf books;
- Not Interested may remain shelved;
- shelf feed allows books from other shelves;
- Rated page;
- similar books;
- cursor pages without duplicates;
- fallback provider.

Architecture:

- modular monolith;
- no frontend DB access;
- no recommender logic in routes;
- recommender package independent of FastAPI/ORM;
- service-owned transactions;
- append-only events;
- environment config;
- storage abstractions;
- explicit ID mappings.

Quality:

- empty-db migrations;
- critical tests;
- E2E flow;
- lint/type/build success;
- no secrets;
- no stack traces;
- keyboard accessibility;
- setup docs;
- AWS mapping;
- usable `docker compose up` flow.

---

## 20. Claude Code constraints

- Treat this file as source of truth.
- Do not replace the architecture with microservices or a generic CRUD app.
- Do not add Redis, Celery, Kafka, or Kubernetes.
- Do not implement the final recommendation funnel.
- Do not use SQLite.
- Do not couple API code to raw Parquet fields outside the adapter.
- Do not treat historical users as app users.
- Do not invent historical timestamps.
- Do not treat rating 0 as negative.
- Do not expose scores as probabilities.
- Do not return ORM objects directly.
- Do not store raw refresh tokens.
- Do not store JWTs in localStorage.
- Do not enforce domain rules only in frontend.
- Do not construct cover paths in frontend.
- Do not hold DB transactions during inference.
- Do not add unused abstractions.
- Prefer complete vertical slices over disconnected stubs.
- Run tests after each phase.
- State failures honestly.

---

## 21. ADRs

Create ADRs for:

1. modular monolith;
2. monorepo/module boundaries;
3. PostgreSQL/persistence;
4. cookie sessions and CSRF;
5. canonical import boundary;
6. recommender provider boundary;
7. persisted batches/cursors;
8. dark Pinterest-inspired frontend;
9. local-first AWS-ready design.

Each ADR: Context, Decision, Alternatives, Consequences, Status.

---

## 22. Future extensions

Permit later:

- item-item retrieval;
- ALS/BPR/LightFM;
- semantic embeddings;
- source similarity graph;
- shelf-tag retrieval;
- candidate union;
- learned ranking;
- diversity/exploration reranking;
- multi-interest profiles;
- shelf/session profiles;
- pgvector semantic search;
- remote recommender service;
- retraining/model registry;
- email recovery;
- AWS IaC;
- viewport impression tracking.

Do not change the existing semantics of ratings, Not Interested, shelves, or stable book IDs.
