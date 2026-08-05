# ADR-0012: Deterministic SQL tiered ranking for search

## Status

Accepted (Phase 8).

## Context

Spec §9.6 defines `GET /search/books?q=...` with a specific seven-tier
initial ranking (exact title → exact title/author combination → title
prefix → trigram fuzzy title → author → description full text →
popularity tie-break) and requires that "search keeps prior user states
visible" — unlike Home/Shelf-discovery/Similar, which use spec §5.5's
eligibility rules to exclude rated/Not-Interested/shelved books, search
must show a book regardless of the visitor's history with it, badged
instead of hidden. `modules/search` didn't exist before this phase;
Phase 2 (migration `43bc30e307a2`) already built the trigram (`title`,
`primary_author_name`) and full-text (`description`) GIN indexes this
ranking needs, but nothing queried them until now.

This ranking is a deterministic, rule-based ordering over indexed
Postgres columns — not a model, not something `packages/recommender`
owns. Spec §2/§20 rule out building the real recommendation funnel and
forbid recommender logic in routes, but neither applies here: there is no
model, no learned ranking, and no ambiguity about what "correct" means for
a given query — the ordering is a direct, auditable function of the SQL
itself.

## Decision

One SQL query per search request (`modules/search/repository.py`), no
caching or persisted batches (unlike recommendations, ADR-0007 — this is
cheap to recompute and has no non-determinism to guard against). Ranking
tiers 1-6 collapse into a single `CASE` expression (`_rank_tier`) — the
first matching branch wins, so an exact-title match is never
double-counted as a fuzzy one — evaluated with:

- Tiers 1-3 (exact title, exact title/author, title prefix): plain
  `lower()`/`LIKE` comparisons.
- Tiers 4-5 (fuzzy title, author): pg_trgm's `%` similarity operator
  (`Column.op('%')(query)`), not a bare `similarity()` call — verified
  directly that only the operator form is planner-recognized against the
  `gin_trgm_ops` indexes from migration `43bc30e307a2`.
- Tier 6 (description): `to_tsvector('english', ...) @@ plainto_tsquery(...)`,
  matching the full-text GIN index's own expression exactly.
- Tier 7 (popularity tie-break): `COALESCE(ratings_count, -1) DESC` as
  the final `ORDER BY` key within a tier — the dataset's existing
  Goodreads rating-count column, not `packages/recommender`'s
  Bayesian-shrunk popularity artifact (a different concept computed
  offline for a different purpose; reusing it here would mean a live
  request depending on a file the recommender package owns, inverting the
  module boundary ADR-0002 sets up).

Pagination is a 3-key keyset cursor (`tier`, `popularity`, `book_id`),
verified by executing an actual page-boundary query against the real
dataset and confirming it resumes with no gap or duplicate — the same
technique `/me/ratings` already uses (`interactions/repository.py`), just
one key deeper.

Every result carries its own `user_state` (`modules/search/schemas.py`'s
`SearchResultItem`, reusing `BookUserState` from `modules/books/schemas.py`)
— rating, Not Interested, and shelf membership, batch-fetched (new
`interactions_repository.get_states_for_books` /
`shelves_repository.get_shelf_ids_for_books`) rather than one query per
result. This is the one meaningful shape difference from
`RecommendationBookItem`, which carries no `user_state` at all because
spec §5.5's eligibility rules make every recommended book provably
Neutral and unsaved by construction — search has no such guarantee, so it
can't skip the enrichment.

## Alternatives considered

- **`similarity(a, b) > threshold` instead of the `%` operator** —
  rejected. Functionally similar, but the bare function form isn't
  recognized by Postgres's planner as index-eligible against a
  `gin_trgm_ops` index; the `%` operator is. Confirmed by executing both
  forms against the real dataset before choosing.
- **A separate lightweight "suggestions" endpoint for the frontend's
  debounced dropdown** — rejected. Spec §9.6 lists exactly one search
  route; the frontend gets suggestions by calling the same
  `GET /search/books` with a small `limit`, not a second backend surface.
- **Reusing `packages/recommender`'s popularity artifact for tier 7** —
  rejected (see Decision). Would require a live request to read a file
  owned by a different module for an unrelated purpose, and would tie
  search's tie-break to whether `make build-popularity` has ever been
  run — `ratings_count` is always present from import.
- **Persisted batches/cursors, mirroring ADR-0007** — rejected. That
  design exists to avoid re-running expensive, non-deterministic model
  inference per page. This query is neither: it's a deterministic
  function of indexed columns, cheap enough to recompute per page, so a
  persistence layer would add complexity without solving a real problem.

## Consequences

- Search ranking has no model version, no training data, and nothing to
  retrain — it changes only if this query changes, which is a code
  review, not a data pipeline concern.
- `ratings_count` being NULL for a book (no source rating data) sorts it
  last within its tier, not first or randomly — same `COALESCE(..., -1)`
  NULLS-last-as-lowest pattern already established in
  `interactions/repository.py`.
- A future change to what "popularity" means for search (e.g. wanting the
  same Bayesian-shrunk score recommendations use) would need that score
  written to a queryable column, not read from the artifact file directly
  — a genuine, deferred design question, not solved here.
