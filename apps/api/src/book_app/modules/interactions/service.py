"""Interaction use cases (spec §5.3): rating / Not-Interested state
transitions with append-only events, and the rated-books listing. Owns
transactions — repositories never commit (spec §4.2).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from book_app.modules.books import repository as books_repository
from book_app.modules.books.exceptions import BookNotFoundError
from book_app.modules.interactions import repository as interactions_repository
from book_app.modules.interactions.attribution import (
    NO_ATTRIBUTION,
    InteractionAttribution,
    TasteSeedSource,
)
from book_app.modules.interactions.event_types import EventType
from book_app.modules.interactions.models import UserBookState
from book_app.modules.interactions.rating_scale import public_to_internal
from book_app.modules.interactions.repository import (
    RatedBookRow,
    RatingsSort,
    TasteSeedBookRow,
)
from book_app.shared.pagination import decode_cursor, encode_cursor

DEFAULT_PAGE_SIZE = 30


def _require_book(session: Session, book_id: int) -> None:
    if books_repository.get_by_id(session, book_id) is None:
        raise BookNotFoundError()


def set_rating(
    session: Session,
    *,
    user_id: UUID,
    book_id: int,
    public_rating: float,
    attribution: InteractionAttribution = NO_ATTRIBUTION,
) -> UserBookState:
    """Set rating (spec §5.3): clears Not Interested atomically, preserves
    shelf memberships (nothing here touches shelf_books). A no-op re-PUT of
    the same value appends no event — and therefore records no attribution
    either, which is correct: nothing happened to attribute."""
    _require_book(session, book_id)
    internal_value = public_to_internal(public_rating)

    state = interactions_repository.get_or_create_state(session, user_id=user_id, book_id=book_id)
    previous_rating = state.rating_value
    previous_not_interested = state.not_interested

    if previous_rating == internal_value and not previous_not_interested:
        return state

    state.not_interested = False
    state.rating_value = internal_value

    if previous_rating is None:
        payload: dict[str, Any] = {"rating": internal_value}
        if previous_not_interested:
            payload["previous_not_interested"] = True
        interactions_repository.append_event(
            session,
            user_id=user_id,
            book_id=book_id,
            event_type=EventType.RATING_SET,
            payload=payload,
            attribution=attribution,
        )
    else:
        interactions_repository.append_event(
            session,
            user_id=user_id,
            book_id=book_id,
            event_type=EventType.RATING_CHANGED,
            payload={"previous_rating": previous_rating, "rating": internal_value},
            attribution=attribution,
        )

    session.commit()
    return state


def remove_rating(session: Session, *, user_id: UUID, book_id: int) -> None:
    """Remove rating (spec §5.3): returns to Neutral, preserves shelves.
    Idempotent — removing an already-absent rating is not an error."""
    _require_book(session, book_id)
    state = interactions_repository.get_state(session, user_id=user_id, book_id=book_id)
    if state is None or state.rating_value is None:
        return

    previous_rating = state.rating_value
    state.rating_value = None

    interactions_repository.append_event(
        session,
        user_id=user_id,
        book_id=book_id,
        event_type=EventType.RATING_REMOVED,
        payload={"previous_rating": previous_rating},
    )
    session.commit()


def set_not_interested(
    session: Session,
    *,
    user_id: UUID,
    book_id: int,
    attribution: InteractionAttribution = NO_ATTRIBUTION,
) -> UserBookState:
    """Set Not Interested (spec §5.3): clears any rating atomically,
    preserves shelves. Idempotent if already Not Interested.

    Attribution matters more here than anywhere else: rec-spec §7.1 makes
    this the single strongest explicit negative signal, so *which* surface
    provoked a rejection is exactly the kind of evidence a later ranker
    needs — rejecting a book shown on Home is a different statement from
    rejecting one shown as similar to a book the reader loves.
    """
    _require_book(session, book_id)
    state = interactions_repository.get_or_create_state(session, user_id=user_id, book_id=book_id)

    if state.not_interested:
        return state

    previous_rating = state.rating_value
    state.rating_value = None
    state.not_interested = True

    payload: dict[str, Any] = {}
    if previous_rating is not None:
        payload["previous_rating"] = previous_rating
    interactions_repository.append_event(
        session,
        user_id=user_id,
        book_id=book_id,
        event_type=EventType.NOT_INTERESTED_SET,
        payload=payload,
        attribution=attribution,
    )
    session.commit()
    return state


def remove_not_interested(session: Session, *, user_id: UUID, book_id: int) -> None:
    """Remove Not Interested (spec §5.3): returns to Neutral. Idempotent if
    not currently Not Interested. Never touches shelves (spec §12.7: "Not
    Interested... never removes shelves" — nothing here does either
    direction)."""
    _require_book(session, book_id)
    state = interactions_repository.get_state(session, user_id=user_id, book_id=book_id)
    if state is None or not state.not_interested:
        return

    state.not_interested = False
    interactions_repository.append_event(
        session, user_id=user_id, book_id=book_id, event_type=EventType.NOT_INTERESTED_REMOVED
    )
    session.commit()


def record_book_opened(
    session: Session,
    *,
    user_id: UUID,
    book_id: int,
    attribution: InteractionAttribution = NO_ATTRIBUTION,
) -> None:
    """Record an intentional book-detail open (rec-spec §4.2).

    Deliberately a write path of its own rather than a side effect of
    `GET /books/{id}` (ADR-0015): a read endpoint that silently writes
    fires on link prefetches, crawlers and every page refresh, none of
    which are a reader deciding to open a book.

    Changes no `user_book_states` row — an open is attention, not a
    preference (rec-spec §7.1), so nothing here touches rating,
    Not Interested, or shelf membership. Repeated opens of the same book
    append repeated events by design; frequency *is* the signal, so
    de-duplicating them would discard it.
    """
    _require_book(session, book_id)
    interactions_repository.append_event(
        session,
        user_id=user_id,
        book_id=book_id,
        event_type=EventType.BOOK_OPENED,
        attribution=attribution,
    )
    session.commit()


def sync_taste_seeds(
    session: Session,
    *,
    user_id: UUID,
    book_ids: list[int],
    source: TasteSeedSource = TasteSeedSource.ONBOARDING,
) -> list[int]:
    """Atomically replace this user's taste seeds (rec-spec §6, ADR-0019).

    Full-replace rather than add/remove deltas, mirroring
    ``shelves.service.sync_book_shelves``: onboarding is a multi-select the
    reader confirms once, so "here is the complete set" is what the client
    actually knows, and it makes the operation idempotent under retries.

    Crucially this touches **no** rating, Not-Interested or shelf state. A
    seed says "this appeals to me", not "I have read this" (a rating) and
    not "I have curated this" (a shelf). Writing it as either would corrupt
    what those mean — ADR-0019 has the argument, and a test asserts it.

    Every requested book is validated before anything is written, so a bad
    id can't leave a half-applied set behind.
    """
    requested = set(book_ids)
    for book_id in sorted(requested):
        _require_book(session, book_id)

    current = interactions_repository.get_taste_seed_book_ids(session, user_id=user_id)

    for book_id in sorted(requested - current):
        interactions_repository.add_taste_seed(
            session, user_id=user_id, book_id=book_id, source=source
        )
        interactions_repository.append_event(
            session,
            user_id=user_id,
            book_id=book_id,
            event_type=EventType.TASTE_SEED_ADDED,
            payload={"source": str(source)},
        )
    for book_id in sorted(current - requested):
        interactions_repository.remove_taste_seed(session, user_id=user_id, book_id=book_id)
        interactions_repository.append_event(
            session,
            user_id=user_id,
            book_id=book_id,
            event_type=EventType.TASTE_SEED_REMOVED,
        )

    session.commit()
    return sorted(requested)


def list_taste_seeds(session: Session, *, user_id: UUID) -> list[TasteSeedBookRow]:
    return interactions_repository.list_taste_seed_books(session, user_id=user_id)


def list_ratings(
    session: Session,
    *,
    user_id: UUID,
    sort: RatingsSort,
    min_rating: float | None,
    max_rating: float | None,
    genre: str | None,
    cursor_str: str | None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[RatedBookRow], str | None]:
    cursor = decode_cursor(cursor_str) if cursor_str else None
    internal_min = public_to_internal(min_rating) if min_rating is not None else None
    internal_max = public_to_internal(max_rating) if max_rating is not None else None

    # Fetch one extra row to know whether a next page exists, without a
    # separate COUNT query.
    rows = interactions_repository.list_rated_books(
        session,
        user_id=user_id,
        sort=sort,
        min_rating=internal_min,
        max_rating=internal_max,
        genre=genre,
        limit=limit + 1,
        cursor=cursor,
    )

    page_rows = rows[:limit]
    next_cursor: str | None = None
    if len(rows) > limit and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"k": interactions_repository.cursor_value_for_row(sort, last), "book_id": last.book_id}
        )

    return page_rows, next_cursor
