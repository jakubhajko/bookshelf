"""Builds the immutable typed snapshot the provider boundary consumes (spec
§10.4-§10.5, §11 step 2). The caller ends this read transaction immediately
after building it (spec §11 step 3) — nothing here holds the session open
past its own return.

Recommender Phase R2 (rec-spec §5) widened the snapshot so it preserves the
*structure* of a reader's preferences rather than flattening them:

- per-shelf memberships with `added_at`, alongside the flat
  `saved_book_ids` eligibility still wants;
- the attribution Phase R1 started recording, instead of dropping it here;
- explicit onboarding taste seeds;
- a deterministic `profile_version` over the durable evidence.

## Truncation order

Every unbounded component is ordered most-recent-first and then capped, so
what survives a cap is the newest evidence rather than an arbitrary slice.
Caps live in `interactions.repository` (`MAX_CONTEXT_*`). Nothing here
truncates a *set* — `saved_book_ids` and `not_interested_book_ids` are
eligibility inputs, and silently dropping ids from those would let excluded
books back into a feed, which is a correctness bug rather than a
performance trade-off.
"""

from __future__ import annotations

from uuid import UUID

from book_recommender.contracts.context import (
    RatingSnapshot,
    RecentInteractionSnapshot,
    SavedBookSnapshot,
    ShelfSummarySnapshot,
    TasteSeedSnapshot,
    UserContext,
)
from sqlalchemy.orm import Session

from book_app.modules.interactions import repository as interactions_repository
from book_app.modules.recommendations.profile_version import compute_profile_version
from book_app.modules.shelves import repository as shelves_repository


def build_user_context(session: Session, *, user_id: UUID) -> UserContext:
    rating_rows = interactions_repository.get_rating_context_rows(session, user_id=user_id)
    not_interested_ids = interactions_repository.get_not_interested_book_ids(
        session, user_id=user_id
    )
    saved_book_ids = shelves_repository.get_all_shelved_book_ids(session, user_id=user_id)
    saved_book_rows = shelves_repository.get_saved_book_rows(
        session,
        user_id=user_id,
        limit=interactions_repository.MAX_CONTEXT_SAVED_BOOKS,
    )
    shelf_summaries = shelves_repository.list_shelves_with_collage(session, user_id=user_id)
    recent_events = interactions_repository.get_recent_events(session, user_id=user_id)
    taste_seed_rows = interactions_repository.get_taste_seed_context_rows(session, user_id=user_id)

    # Computed from the *truncated* components deliberately: the version is
    # a fingerprint of what the engine will actually see, so it stays a
    # sound cache key for anything derived from this context.
    profile_version = compute_profile_version(
        ratings=[(row.book_id, row.rating_value) for row in rating_rows],
        saved_books=[(row.book_id, row.shelf_id, row.added_at) for row in saved_book_rows],
        not_interested_book_ids=not_interested_ids,
        taste_seeds=[(row.book_id, row.source, row.selected_at) for row in taste_seed_rows],
    )

    return UserContext(
        user_id=user_id,
        ratings=tuple(
            RatingSnapshot(
                book_id=row.book_id, rating_value=row.rating_value, rated_at=row.updated_at
            )
            for row in rating_rows
        ),
        saved_book_ids=frozenset(saved_book_ids),
        saved_books=tuple(
            SavedBookSnapshot(book_id=row.book_id, shelf_id=row.shelf_id, added_at=row.added_at)
            for row in saved_book_rows
        ),
        shelf_ids=tuple(summary.shelf.id for summary in shelf_summaries),
        not_interested_book_ids=frozenset(not_interested_ids),
        recent_interactions=tuple(
            RecentInteractionSnapshot(
                event_type=row.event_type,
                book_id=row.book_id,
                occurred_at=row.occurred_at,
                shelf_id=row.shelf_id,
                surface=row.surface,
                session_id=row.session_id,
                recommendation_request_id=row.recommendation_request_id,
                search_query_id=row.search_query_id,
                source_book_id=row.source_book_id,
                rank_position=row.rank_position,
            )
            for row in recent_events
        ),
        shelf_summaries=tuple(
            ShelfSummarySnapshot(
                shelf_id=summary.shelf.id, name=summary.shelf.name, book_count=summary.book_count
            )
            for summary in shelf_summaries
        ),
        taste_seeds=tuple(
            TasteSeedSnapshot(book_id=row.book_id, source=row.source, selected_at=row.selected_at)
            for row in taste_seed_rows
        ),
        profile_version=profile_version,
    )
