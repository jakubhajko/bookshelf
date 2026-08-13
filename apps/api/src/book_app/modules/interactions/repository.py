"""Interaction persistence: no HTTP concerns, no commits (spec §4.2) — the
caller's service owns the transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from book_app.modules.books.models import Book, BookGenre, Genre
from book_app.modules.interactions.attribution import NO_ATTRIBUTION, InteractionAttribution
from book_app.modules.interactions.models import InteractionEvent, UserBookState
from book_app.shared.text import normalize_for_uniqueness


def get_state(session: Session, *, user_id: UUID, book_id: int) -> UserBookState | None:
    return session.get(UserBookState, (user_id, book_id))


def get_states_for_books(
    session: Session, *, user_id: UUID, book_ids: Sequence[int]
) -> dict[int, UserBookState]:
    """Batched form of :func:`get_state` — search results (spec §9.6:
    "keeps prior user states visible") need every result's rating/
    Not-Interested state at once, not one query per row."""
    if not book_ids:
        return {}
    stmt = select(UserBookState).where(
        UserBookState.user_id == user_id, UserBookState.book_id.in_(book_ids)
    )
    return {state.book_id: state for state in session.execute(stmt).scalars()}


def get_or_create_state(session: Session, *, user_id: UUID, book_id: int) -> UserBookState:
    state = get_state(session, user_id=user_id, book_id=book_id)
    if state is None:
        state = UserBookState(user_id=user_id, book_id=book_id)
        session.add(state)
        session.flush()
    return state


def append_event(
    session: Session,
    *,
    user_id: UUID,
    book_id: int | None,
    event_type: str,
    shelf_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
    attribution: InteractionAttribution = NO_ATTRIBUTION,
) -> InteractionEvent:
    """The one place `interaction_events`' six attribution columns are
    written (ADR-0015). They have existed, correctly typed and fully
    indexed, since Phase 4 with no writer at all; routing every event
    through this signature is what makes them real without each caller
    knowing the column list.

    `attribution` defaults to empty rather than being required, so every
    pre-existing call site stays valid and unattributed writes remain a
    first-class case.
    """
    event = InteractionEvent(
        user_id=user_id,
        book_id=book_id,
        event_type=event_type,
        shelf_id=shelf_id,
        payload=payload or {},
        surface=attribution.surface,
        session_id=attribution.session_id,
        recommendation_request_id=attribution.recommendation_request_id,
        search_query_id=attribution.search_query_id,
        source_book_id=attribution.source_book_id,
        rank_position=attribution.rank_position,
    )
    session.add(event)
    session.flush()
    return event


class RatingsSort(StrEnum):
    RECENT = "recent"
    HIGHEST = "highest"
    LOWEST = "lowest"
    TITLE = "title"
    AUTHOR = "author"


@dataclass(frozen=True)
class RatedBookRow:
    book_id: int
    work_id: str
    title: str
    primary_author_name: str | None
    cover_object_key: str | None
    rating_value: int
    rated_at: datetime


# NULLS-last approximation: a book without an author sorts after every book
# that has one. True SQL NULLS LAST keyset pagination needs a compound
# not-null/null-branch condition; for a *rated-books* list (a small,
# personal subset of the catalog) this is a pragmatic simplification, not a
# correctness-critical distinction — documented here rather than silently
# assumed, see docs/implementation/plan.md.
_AUTHOR_SORT_KEY = func.coalesce(Book.primary_author_name, "~")

_SORT_CONFIG: dict[RatingsSort, tuple[Any, str, str]] = {
    RatingsSort.RECENT: (UserBookState.updated_at, "desc", "k"),
    RatingsSort.HIGHEST: (UserBookState.rating_value, "desc", "k"),
    RatingsSort.LOWEST: (UserBookState.rating_value, "asc", "k"),
    RatingsSort.TITLE: (Book.title, "asc", "k"),
    RatingsSort.AUTHOR: (_AUTHOR_SORT_KEY, "asc", "k"),
}


def _genre_filter_subquery(genre: str) -> Any:
    normalized = normalize_for_uniqueness(genre)
    return (
        select(BookGenre.book_id)
        .join(Genre, Genre.id == BookGenre.genre_id)
        .where(Genre.normalized_name == normalized)
    )


def list_rated_books(
    session: Session,
    *,
    user_id: UUID,
    sort: RatingsSort,
    min_rating: int | None,
    max_rating: int | None,
    genre: str | None,
    limit: int,
    cursor: dict[str, Any] | None,
) -> list[RatedBookRow]:
    sort_key, direction, cursor_field = _SORT_CONFIG[sort]

    stmt = (
        select(
            Book.id,
            Book.work_id,
            Book.title,
            Book.primary_author_name,
            Book.cover_object_key,
            UserBookState.rating_value,
            UserBookState.updated_at,
        )
        .join(Book, Book.id == UserBookState.book_id)
        .where(UserBookState.user_id == user_id, UserBookState.rating_value.isnot(None))
    )

    if min_rating is not None:
        stmt = stmt.where(UserBookState.rating_value >= min_rating)
    if max_rating is not None:
        stmt = stmt.where(UserBookState.rating_value <= max_rating)
    if genre is not None:
        stmt = stmt.where(Book.id.in_(_genre_filter_subquery(genre)))

    if cursor is not None:
        key_value = cursor[cursor_field]
        # RECENT's cursor value round-trips through JSON as an ISO string
        # (JSON has no datetime type) — compared as-is against a TIMESTAMPTZ
        # column, that relies on implicit driver-level string->timestamp
        # coercion instead of an explicit one. Parse it back explicitly.
        if sort is RatingsSort.RECENT:
            key_value = datetime.fromisoformat(key_value)
        tiebreak = cursor["book_id"]
        if direction == "desc":
            stmt = stmt.where(
                or_(sort_key < key_value, and_(sort_key == key_value, Book.id < tiebreak))
            )
        else:
            stmt = stmt.where(
                or_(sort_key > key_value, and_(sort_key == key_value, Book.id > tiebreak))
            )

    order = sort_key.desc() if direction == "desc" else sort_key.asc()
    tiebreak_order = Book.id.desc() if direction == "desc" else Book.id.asc()
    stmt = stmt.order_by(order, tiebreak_order).limit(limit)

    rows = session.execute(stmt).all()
    return [
        RatedBookRow(
            book_id=row.id,
            work_id=row.work_id,
            title=row.title,
            primary_author_name=row.primary_author_name,
            cover_object_key=row.cover_object_key,
            rating_value=row.rating_value,
            rated_at=row.updated_at,
        )
        for row in rows
    ]


def cursor_value_for_row(sort: RatingsSort, row: RatedBookRow) -> Any:
    """The value to store in the *next* page's cursor for this sort mode —
    must match what ``list_rated_books`` compares the cursor field against.
    """
    if sort is RatingsSort.RECENT:
        return row.rated_at.isoformat()
    if sort in (RatingsSort.HIGHEST, RatingsSort.LOWEST):
        return row.rating_value
    if sort is RatingsSort.TITLE:
        return row.title
    return row.primary_author_name or "~"


# --- Read-side queries (Phase 5: recommendation context/eligibility) --------

# Conservative bounds on what goes into a UserContext snapshot (spec §10.5:
# "bounded recent interactions" — extended here to ratings too, since a
# long-time user's full rating history has no upper bound otherwise and
# nothing consumes more than this yet; raise later if a real engine needs
# more signal).
MAX_CONTEXT_RATINGS = 500
MAX_CONTEXT_RECENT_INTERACTIONS = 50


def get_rated_book_ids(session: Session, *, user_id: UUID) -> set[int]:
    stmt = select(UserBookState.book_id).where(
        UserBookState.user_id == user_id, UserBookState.rating_value.isnot(None)
    )
    return set(session.execute(stmt).scalars())


def get_not_interested_book_ids(session: Session, *, user_id: UUID) -> set[int]:
    stmt = select(UserBookState.book_id).where(
        UserBookState.user_id == user_id, UserBookState.not_interested.is_(True)
    )
    return set(session.execute(stmt).scalars())


@dataclass(frozen=True)
class RatingContextRow:
    book_id: int
    rating_value: int
    updated_at: datetime


def get_rating_context_rows(session: Session, *, user_id: UUID) -> list[RatingContextRow]:
    stmt = (
        select(UserBookState.book_id, UserBookState.rating_value, UserBookState.updated_at)
        .where(UserBookState.user_id == user_id, UserBookState.rating_value.isnot(None))
        .order_by(UserBookState.updated_at.desc())
        .limit(MAX_CONTEXT_RATINGS)
    )
    return [
        RatingContextRow(
            book_id=row.book_id, rating_value=row.rating_value, updated_at=row.updated_at
        )
        for row in session.execute(stmt)
    ]


@dataclass(frozen=True)
class RecentEventRow:
    event_type: str
    book_id: int | None
    occurred_at: datetime


def get_recent_events(session: Session, *, user_id: UUID) -> list[RecentEventRow]:
    stmt = (
        select(InteractionEvent.event_type, InteractionEvent.book_id, InteractionEvent.occurred_at)
        .where(InteractionEvent.user_id == user_id)
        .order_by(InteractionEvent.occurred_at.desc())
        .limit(MAX_CONTEXT_RECENT_INTERACTIONS)
    )
    return [
        RecentEventRow(event_type=row.event_type, book_id=row.book_id, occurred_at=row.occurred_at)
        for row in session.execute(stmt)
    ]
