# ADR-0007: Persisted recommendation batches with opaque cursors

## Status

Accepted (approved in `APP_SPECIFICATION.md` §9.9, §10.7, §20 before implementation started).

## Context

Recommendation surfaces (home, shelf discovery, similar books) need stable,
duplicate-free infinite scroll. Recomputing recommendations on every page
request would both be expensive and risk returning different orderings (or
duplicates) as the user's state changes mid-scroll.

## Decision

On the first request for a surface, the provider generates a larger ordered
batch than one page needs; the API persists the full batch
(`recommendation_requests` + `recommendation_results`, keyed by
`(request_id, position)`, unique on `(request_id, book_id)`), returns the
first page, and records delivered impressions
(`recommendation_impressions`) — "impression" means "delivered in a
successful API response" in version one, not viewport visibility. Subsequent
pages are served by reading further positions from the same persisted batch
via an opaque cursor encoding the request ID and next position, not by
recomputing. The frontend never computes or re-sorts recommendation order.

## Alternatives considered

- **Stateless offset/limit pagination recomputed per page** — rejected. Can't
  guarantee no duplicates/no reordering across pages as underlying data
  changes between requests, and repeats provider inference cost per page.
- **Client-visible, structured cursors (e.g. raw JSON with request ID and
  offset)** — rejected in favor of an opaque cursor. Keeps the encoding free
  to change later (e.g. adding signing) without a frontend contract change.
- **Track impressions via a separate client-reported "viewed" event instead
  of at delivery time** — deferred, not rejected outright; spec §22 lists
  "viewport impression tracking" as a future extension. Version one's
  simpler delivery-time definition is explicit in spec §8.10.

## Consequences

- `recommendation_requests`/`recommendation_results` act as a short-lived
  cache per surface request, not permanent history — `expires_at` bounds how
  long a batch can still be paged through.
- The recommendation workflow (spec §11) must end its DB read transaction
  before calling the provider and must not hold one open during inference,
  then persist the result and impressions in their own transaction(s)
  afterward — this ordering is a hard constraint on `service.py` in the
  recommendations module, not just a performance suggestion.
- Because order is authoritative and persisted, a provider bug that returns
  a bad ordering is "sticky" for the lifetime of that batch — result
  validation before persistence (spec §10.8) is the only defense, so it must
  run before the batch is written, not after.
