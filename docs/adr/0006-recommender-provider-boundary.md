# ADR-0006: Typed recommender provider boundary

## Status

Accepted (approved in `APP_SPECIFICATION.md` §10, §20 before implementation started).

**Partly superseded by ADR-0013 (Recommender Phase 0):** the scope
limitation below — that building the real recommendation funnel is out of
scope — no longer holds. The funnel is now in scope and is being built
*behind* this boundary. Everything else in this ADR remains live and
binding: the provider/engine protocols, the discriminated-union typed
contexts, application-owned eligibility, defensive result validation,
authoritative engine ordering, and `packages/recommender`'s freedom from
FastAPI/ORM imports. The rejected alternative "build the real
recommendation funnel now" is retained as historical context recording why
the boundary existed before the pipeline did.

## Context

The full recommendation system (candidate generation, union/dedup, ranking,
reranking) doesn't exist yet and shouldn't be built prematurely, but the
application needs a stable way to request recommendations today (via mock and
popularity engines) and swap in the real pipeline later without changing any
route or service code.

## Decision

The application depends only on a typed `RecommendationProvider` protocol
(`async def recommend(request) -> RecommendationBatch`) implemented by an
in-process provider, a fallback provider, and (as a skeleton only) a
remote-provider interface. Internally, providers call a synchronous
`RecommendationEngine` protocol implemented by `MockRecommendationEngine`,
`PopularityRecommendationEngine`, and a placeholder
`FuturePipelineRecommendationEngine` adapter. Everything the app sends in is a
discriminated-union typed context (`HomeContext` / `ShelfContext` /
`SimilarBooksContext` / `SearchContext`) plus an immutable user-context
snapshot; everything it gets back is an ordered, validated batch with stable
reason codes (§10.9). The application owns eligibility/exclusion rules and
sends them as hard exclusions; the recommender obeys them, and the API
validates the result defensively regardless. `packages/recommender` has zero
FastAPI or ORM imports, enforced structurally (separate package, own
dependency manifest) and by a hygiene test.

## Alternatives considered

- **Build the real recommendation funnel now** — explicitly out of scope
  (spec §2/§20: "Do not implement the final recommendation funnel"). Mock and
  popularity providers satisfy every product requirement (home feed, shelf
  discovery, similar books) until real models exist.
- **Let routes call recommendation logic directly** — rejected; spec §20
  forbids recommendation algorithms in routes, and it would make the eventual
  pipeline swap a routes-and-services change instead of a one-line provider
  wiring change.
- **Have the recommender query the database itself** — rejected. The
  recommender receives immutable snapshots built by the application; this
  keeps `packages/recommender` free of ORM/session concerns and testable in
  complete isolation (spec §13.2: "remain independent of ORM/FastAPI").

## Consequences

- Adding the real pipeline later means writing a new `RecommendationEngine`
  (or provider) and switching configuration — no route, service, or schema
  change required, as long as the new engine honors the same protocol and
  reason codes.
- Because scores are explicitly not assumed to be probabilities and order is
  authoritative (spec §10.7), the API and frontend must never re-sort
  recommendation results by score themselves.
- Contract tests (spec §13.2) apply identically to mock, popularity, and
  (eventually) the real pipeline, since they test the protocol, not any one
  implementation.
