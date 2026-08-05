# ADR-0011: Backend-served cover images via an opaque, unauthenticated route

## Status

Accepted (Phase 7).

## Context

Phase 2 built `LocalFileStorage` (safe object-key resolution under a
configured root, spec §14 "safe local cover paths") but nothing in the
running application ever called it — no prior phase rendered an image.
Phase 7 is the first to need `<img>` tags (masonry grid, cards, detail page,
spec §12.1 "image-led"). Spec §20 is explicit: "Do not construct cover
paths in frontend." Every API response that carries a cover only carries an
opaque `cover_object_key` (spec §7.3: "Store only a `cover_object_key`, not
an absolute path"), never a URL — so something on the backend must turn
that key into a fetchable image, and the frontend must not need to know how.

Every other route in this application requires authentication (no
anonymous browsing exists anywhere else in the spec). Cover images are
different: browser `<img src>` requests don't go through
`apps/web/src/api/client.ts`'s session-refresh-and-retry middleware (that
only wraps `openapi-fetch` calls), so gating covers behind the ~15-minute
access token (spec §6.4) would turn every cover into a broken image
partway through an ordinary browsing session, with no automatic recovery.

## Decision

Add `GET /api/v1/covers/{object_key}` (`apps/api/src/book_app/core/covers.py`)
— infrastructure, not a domain module, mirroring `core/health.py`'s existing
precedent (no service/repository/models). It resolves `object_key` through
the same `LocalFileStorage.resolve()` used since Phase 2 (raises
`UnsafeObjectKeyError` on path traversal, mapped to a 404
`COVER_NOT_FOUND` — never a 500, never a leaked filesystem detail) and
streams the file back as `image/jpeg` (the dataset's own fixed contract,
spec §7.3: every cover is a `.jpg`; not a guessed content type).

Deliberately **unauthenticated**. Cover art is public — the same bytes
regardless of which user asks, ultimately sourced from Goodreads/Open
Library (`data/README.md`) — so this isn't a privacy or ownership boundary,
only a path-safety one, and that's enforced independently of auth via
`LocalFileStorage.resolve` itself.

The frontend (`apps/web/src/api/covers.ts`) only ever does
`${API_BASE_URL}/api/v1/covers/${encodeURIComponent(objectKey)}` — appending
an opaque, backend-issued key to a fixed, backend-owned route prefix it
doesn't need to understand the meaning of. It has no knowledge of `.jpg`,
of the local filesystem layout, or of any future S3 key scheme, satisfying
spec §20 without needing a fully-resolved URL in every API response body.

## Alternatives considered

- **Return a fully-resolved URL in every response schema that carries a
  cover** (`BookDetail`, `RecommendationBookItem`, `ShelfPublic`,
  `ShelfBookItem`, `RatedBookItem`) — rejected for this phase. Correct in
  principle, but touches five already-shipped, tested schemas across
  Phases 2/4/5 for a URL that's mechanically derivable from one fixed
  prefix + the key already present; the opaque-route approach gets the same
  frontend-knows-nothing property with a one-line frontend helper instead.
  Worth revisiting if a future backend actually needs per-request
  signed URLs (e.g. private S3 objects), which a flat route can't express.
- **Require authentication on the covers route, matching every other
  route** — rejected. Cover art isn't per-user data, so there's no
  ownership check to make, and doing it anyway trades a real, foreseeable
  bug (broken images ~15 minutes into a session, since `<img>` tags bypass
  the frontend's token-refresh middleware) for consistency with routes that
  actually do gate private data.
- **Serve covers directly from Vite/a static file server on the frontend
  origin** — rejected. Covers are backend-owned data (imported by
  `import_catalog`, resolved against `COVER_STORAGE_LOCAL_PATH`), and this
  would require the frontend build to somehow mirror or proxy backend
  storage, duplicating the path-safety logic `LocalFileStorage` already
  owns.

## Consequences

- Cover images are the one unauthenticated HTTP surface in this
  application. Documented here explicitly so a future security review
  doesn't mistake it for an oversight.
- Swapping `cover_storage_backend` from `local` to `s3` later (spec §17:
  "covers -> S3/CloudFront") changes only `core/covers.py`'s internals —
  most likely a 302 redirect to a signed/public CloudFront URL instead of
  streaming bytes. The frontend contract (`GET /api/v1/covers/{object_key}`)
  does not change, so no frontend code needs to change either.
- `app.state.cover_storage` is now built once in `create_app()`, the same
  pattern already used for `db_engine`/`db_session_factory`/
  `auth_rate_limiter` — the first time `LocalFileStorage` is actually wired
  into a running request path rather than only unit-tested directly.
