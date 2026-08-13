"""Shelf use cases (spec §5.4): CRUD, browsing, and the multi-shelf sync
that ``modules/books`` calls into. Owns transactions — repositories never
commit (spec §4.2).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from book_app.modules.books import repository as books_repository
from book_app.modules.books.exceptions import BookNotFoundError
from book_app.modules.interactions import repository as interactions_repository
from book_app.modules.interactions.attribution import NO_ATTRIBUTION, InteractionAttribution
from book_app.modules.interactions.event_types import EventType
from book_app.modules.shelves import repository as shelves_repository
from book_app.modules.shelves.exceptions import ShelfNameTakenError, ShelfNotFoundError
from book_app.modules.shelves.models import Shelf
from book_app.modules.shelves.repository import ShelfBookRow, ShelfSummary
from book_app.modules.shelves.shelf_name_rules import clean_shelf_name
from book_app.shared.pagination import decode_cursor, encode_cursor
from book_app.shared.text import normalize_for_uniqueness

DEFAULT_PAGE_SIZE = 30


def _require_owned_shelf(session: Session, *, user_id: UUID, shelf_id: UUID) -> Shelf:
    shelf = shelves_repository.get_owned(session, user_id=user_id, shelf_id=shelf_id)
    if shelf is None:
        # Same error whether the shelf doesn't exist or belongs to someone
        # else (spec §6.6) — confirming "it exists but isn't yours" would
        # leak information a 404 doesn't.
        raise ShelfNotFoundError()
    return shelf


def create_shelf(session: Session, *, user_id: UUID, name: str, description: str | None) -> Shelf:
    cleaned_name = clean_shelf_name(name)
    normalized = normalize_for_uniqueness(cleaned_name)
    if (
        shelves_repository.get_by_normalized_name(
            session, user_id=user_id, normalized_name=normalized
        )
        is not None
    ):
        raise ShelfNameTakenError()

    try:
        shelf = shelves_repository.create_shelf(
            session,
            user_id=user_id,
            name=cleaned_name,
            normalized_name=normalized,
            description=description,
        )
    except IntegrityError as exc:
        # Race: two concurrent creates with the same normalized name. The
        # pre-check above is a UX nicety, not the source of truth.
        session.rollback()
        raise ShelfNameTakenError() from exc

    session.commit()
    return shelf


def update_shelf(
    session: Session, *, user_id: UUID, shelf_id: UUID, updates: dict[str, Any]
) -> ShelfSummary:
    """``updates`` only contains keys the caller actually provided (PATCH
    semantics) — 'description' absent leaves it untouched, present-and-None
    clears it."""
    shelf = _require_owned_shelf(session, user_id=user_id, shelf_id=shelf_id)

    if "name" in updates:
        cleaned_name = clean_shelf_name(updates["name"])
        normalized = normalize_for_uniqueness(cleaned_name)
        if normalized != shelf.normalized_name:
            existing = shelves_repository.get_by_normalized_name(
                session, user_id=user_id, normalized_name=normalized
            )
            if existing is not None and existing.id != shelf.id:
                raise ShelfNameTakenError()
        shelf.name = cleaned_name
        shelf.normalized_name = normalized

    if "description" in updates:
        shelf.description = updates["description"]

    session.commit()
    return shelves_repository.get_shelf_summary(session, shelf=shelf)


def delete_shelf(session: Session, *, user_id: UUID, shelf_id: UUID) -> None:
    shelf = _require_owned_shelf(session, user_id=user_id, shelf_id=shelf_id)
    shelves_repository.delete_shelf(session, shelf)
    session.commit()


def list_shelves(session: Session, *, user_id: UUID) -> list[ShelfSummary]:
    return shelves_repository.list_shelves_with_collage(session, user_id=user_id)


def get_shelf(session: Session, *, user_id: UUID, shelf_id: UUID) -> ShelfSummary:
    shelf = _require_owned_shelf(session, user_id=user_id, shelf_id=shelf_id)
    return shelves_repository.get_shelf_summary(session, shelf=shelf)


def list_shelf_books(
    session: Session,
    *,
    user_id: UUID,
    shelf_id: UUID,
    cursor_str: str | None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[ShelfBookRow], str | None]:
    _require_owned_shelf(session, user_id=user_id, shelf_id=shelf_id)

    cursor = decode_cursor(cursor_str) if cursor_str else None
    rows = shelves_repository.list_shelf_books(
        session, shelf_id=shelf_id, limit=limit + 1, cursor=cursor
    )

    page_rows = rows[:limit]
    next_cursor: str | None = None
    if len(rows) > limit and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"added_at": last.added_at.isoformat(), "book_id": last.book_id}
        )

    return page_rows, next_cursor


def add_book_to_shelf(
    session: Session,
    *,
    user_id: UUID,
    shelf_id: UUID,
    book_id: int,
    attribution: InteractionAttribution = NO_ATTRIBUTION,
) -> None:
    _require_owned_shelf(session, user_id=user_id, shelf_id=shelf_id)
    if books_repository.get_by_id(session, book_id) is None:
        raise BookNotFoundError()

    if shelves_repository.get_membership(session, shelf_id=shelf_id, book_id=book_id) is not None:
        return  # idempotent no-op, nothing changed

    shelves_repository.add_book(
        session, shelf_id=shelf_id, book_id=book_id, source_surface=attribution.surface
    )
    interactions_repository.append_event(
        session,
        user_id=user_id,
        book_id=book_id,
        event_type=EventType.SHELF_BOOK_ADDED,
        shelf_id=shelf_id,
        attribution=attribution,
    )
    session.commit()


def remove_book_from_shelf(
    session: Session, *, user_id: UUID, shelf_id: UUID, book_id: int
) -> None:
    _require_owned_shelf(session, user_id=user_id, shelf_id=shelf_id)

    removed = shelves_repository.remove_book(session, shelf_id=shelf_id, book_id=book_id)
    if not removed:
        return  # idempotent no-op

    interactions_repository.append_event(
        session,
        user_id=user_id,
        book_id=book_id,
        event_type=EventType.SHELF_BOOK_REMOVED,
        shelf_id=shelf_id,
    )
    session.commit()


def sync_book_shelves(
    session: Session,
    *,
    user_id: UUID,
    book_id: int,
    shelf_ids: list[UUID],
    attribution: InteractionAttribution = NO_ATTRIBUTION,
) -> list[UUID]:
    """Atomically replace the book's shelf memberships for this user (spec
    §9.2: "atomically replaces the current user's shelf memberships for
    that book after ownership validation").

    Attribution describes the *save*, so it is recorded on additions only.
    A removal in the same sync gets an event without it: the surface the
    reader happened to be on when un-shelving says nothing about why the
    book was saved in the first place, and stamping the removal with it
    would misattribute the original save's origin.
    """
    if books_repository.get_by_id(session, book_id) is None:
        raise BookNotFoundError()

    requested = set(shelf_ids)
    owned = shelves_repository.get_owned_shelf_ids(
        session, user_id=user_id, shelf_ids=list(requested)
    )
    if owned != requested:
        raise ShelfNotFoundError()

    current = set(
        shelves_repository.get_shelf_ids_for_book(session, user_id=user_id, book_id=book_id)
    )
    to_add = sorted(requested - current, key=str)
    to_remove = sorted(current - requested, key=str)

    for shelf_id in to_add:
        shelves_repository.add_book(
            session, shelf_id=shelf_id, book_id=book_id, source_surface=attribution.surface
        )
        interactions_repository.append_event(
            session,
            user_id=user_id,
            book_id=book_id,
            event_type=EventType.SHELF_BOOK_ADDED,
            shelf_id=shelf_id,
            attribution=attribution,
        )
    for shelf_id in to_remove:
        shelves_repository.remove_book(session, shelf_id=shelf_id, book_id=book_id)
        interactions_repository.append_event(
            session,
            user_id=user_id,
            book_id=book_id,
            event_type=EventType.SHELF_BOOK_REMOVED,
            shelf_id=shelf_id,
        )

    session.commit()
    return sorted(requested, key=str)
