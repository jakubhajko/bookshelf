"""Builds the immutable typed snapshot the provider boundary consumes (spec
§10.4-§10.5, §11 step 2). The caller ends this read transaction immediately
after building it (spec §11 step 3) — nothing here holds the session open
past its own return.
"""

from __future__ import annotations

from uuid import UUID

from book_recommender.contracts.context import (
    RatingSnapshot,
    RecentInteractionSnapshot,
    ShelfSummarySnapshot,
    UserContext,
)
from sqlalchemy.orm import Session

from book_app.modules.interactions import repository as interactions_repository
from book_app.modules.shelves import repository as shelves_repository


def build_user_context(session: Session, *, user_id: UUID) -> UserContext:
    rating_rows = interactions_repository.get_rating_context_rows(session, user_id=user_id)
    not_interested_ids = interactions_repository.get_not_interested_book_ids(
        session, user_id=user_id
    )
    saved_book_ids = shelves_repository.get_all_shelved_book_ids(session, user_id=user_id)
    shelf_summaries = shelves_repository.list_shelves_with_collage(session, user_id=user_id)
    recent_events = interactions_repository.get_recent_events(session, user_id=user_id)

    return UserContext(
        user_id=user_id,
        ratings=tuple(
            RatingSnapshot(
                book_id=row.book_id, rating_value=row.rating_value, rated_at=row.updated_at
            )
            for row in rating_rows
        ),
        saved_book_ids=frozenset(saved_book_ids),
        shelf_ids=tuple(summary.shelf.id for summary in shelf_summaries),
        not_interested_book_ids=frozenset(not_interested_ids),
        recent_interactions=tuple(
            RecentInteractionSnapshot(
                event_type=row.event_type, book_id=row.book_id, occurred_at=row.occurred_at
            )
            for row in recent_events
        ),
        shelf_summaries=tuple(
            ShelfSummarySnapshot(
                shelf_id=summary.shelf.id, name=summary.shelf.name, book_count=summary.book_count
            )
            for summary in shelf_summaries
        ),
    )
