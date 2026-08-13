"""Shelf persistence: no HTTP concerns, no commits (spec §4.2) — the
caller's service owns the transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from book_app.modules.books.models import Book
from book_app.modules.shelves.models import Shelf, ShelfBook

COLLAGE_COVER_LIMIT = 4


def get_by_id(session: Session, shelf_id: UUID) -> Shelf | None:
    return session.get(Shelf, shelf_id)


def get_owned(session: Session, *, user_id: UUID, shelf_id: UUID) -> Shelf | None:
    shelf = get_by_id(session, shelf_id)
    if shelf is None or shelf.user_id != user_id:
        return None
    return shelf


def get_by_normalized_name(
    session: Session, *, user_id: UUID, normalized_name: str
) -> Shelf | None:
    stmt = select(Shelf).where(Shelf.user_id == user_id, Shelf.normalized_name == normalized_name)
    return session.execute(stmt).scalar_one_or_none()


def create_shelf(
    session: Session, *, user_id: UUID, name: str, normalized_name: str, description: str | None
) -> Shelf:
    shelf = Shelf(
        user_id=user_id, name=name, normalized_name=normalized_name, description=description
    )
    session.add(shelf)
    session.flush()
    return shelf


def delete_shelf(session: Session, shelf: Shelf) -> None:
    session.delete(shelf)
    session.flush()


@dataclass(frozen=True)
class ShelfSummary:
    shelf: Shelf
    book_count: int
    cover_object_keys: list[str]


def list_shelves_with_collage(session: Session, *, user_id: UUID) -> list[ShelfSummary]:
    """Ordered by most-recently-updated first (spec §12.8: "updated order").
    Collage covers are each shelf's most-recently-added books, up to
    COLLAGE_COVER_LIMIT (spec §9.3: "enough cover data for a collage
    without N+1 frontend requests")."""
    shelves = list(
        session.execute(
            select(Shelf).where(Shelf.user_id == user_id).order_by(Shelf.updated_at.desc())
        ).scalars()
    )
    if not shelves:
        return []

    shelf_ids = [s.id for s in shelves]

    count_rows = session.execute(
        select(ShelfBook.shelf_id, func.count())
        .where(ShelfBook.shelf_id.in_(shelf_ids))
        .group_by(ShelfBook.shelf_id)
    ).all()
    counts: dict[UUID, int] = {shelf_id: count for shelf_id, count in count_rows}

    covers_by_shelf: dict[UUID, list[str]] = {s.id: [] for s in shelves}
    cover_rows = session.execute(
        select(ShelfBook.shelf_id, Book.cover_object_key)
        .join(Book, Book.id == ShelfBook.book_id)
        .where(ShelfBook.shelf_id.in_(shelf_ids), Book.cover_object_key.isnot(None))
        .order_by(ShelfBook.shelf_id, ShelfBook.added_at.desc())
    ).all()
    for shelf_id, cover_key in cover_rows:
        bucket = covers_by_shelf[shelf_id]
        if len(bucket) < COLLAGE_COVER_LIMIT:
            bucket.append(cover_key)

    return [
        ShelfSummary(
            shelf=s, book_count=counts.get(s.id, 0), cover_object_keys=covers_by_shelf[s.id]
        )
        for s in shelves
    ]


def get_shelf_summary(session: Session, *, shelf: Shelf) -> ShelfSummary:
    """Single-shelf equivalent of :func:`list_shelves_with_collage`'s
    enrichment, for the shelf-detail endpoint (GET/PATCH one shelf)."""
    book_count = session.execute(
        select(func.count()).select_from(ShelfBook).where(ShelfBook.shelf_id == shelf.id)
    ).scalar_one()
    # The WHERE clause already guarantees no NULLs at the SQL level; the
    # `if key is not None` re-states that for mypy, which can't see through
    # `.isnot(None)` to narrow the column's `str | None` Python type.
    cover_keys = [
        key
        for key in session.execute(
            select(Book.cover_object_key)
            .select_from(ShelfBook)
            .join(Book, Book.id == ShelfBook.book_id)
            .where(ShelfBook.shelf_id == shelf.id, Book.cover_object_key.isnot(None))
            .order_by(ShelfBook.added_at.desc())
            .limit(COLLAGE_COVER_LIMIT)
        ).scalars()
        if key is not None
    ]
    return ShelfSummary(shelf=shelf, book_count=book_count, cover_object_keys=cover_keys)


@dataclass(frozen=True)
class ShelfBookRow:
    book_id: int
    work_id: str
    title: str
    primary_author_name: str | None
    cover_object_key: str | None
    added_at: datetime


def list_shelf_books(
    session: Session, *, shelf_id: UUID, limit: int, cursor: dict[str, Any] | None
) -> list[ShelfBookRow]:
    stmt = (
        select(
            Book.id,
            Book.work_id,
            Book.title,
            Book.primary_author_name,
            Book.cover_object_key,
            ShelfBook.added_at,
        )
        .join(Book, Book.id == ShelfBook.book_id)
        .where(ShelfBook.shelf_id == shelf_id)
    )
    if cursor is not None:
        added_at = datetime.fromisoformat(cursor["added_at"])
        tiebreak = cursor["book_id"]
        stmt = stmt.where(
            or_(
                ShelfBook.added_at < added_at,
                and_(ShelfBook.added_at == added_at, Book.id < tiebreak),
            )
        )
    stmt = stmt.order_by(ShelfBook.added_at.desc(), Book.id.desc()).limit(limit)

    rows = session.execute(stmt).all()
    return [
        ShelfBookRow(
            book_id=row.id,
            work_id=row.work_id,
            title=row.title,
            primary_author_name=row.primary_author_name,
            cover_object_key=row.cover_object_key,
            added_at=row.added_at,
        )
        for row in rows
    ]


def get_membership(session: Session, *, shelf_id: UUID, book_id: int) -> ShelfBook | None:
    return session.get(ShelfBook, (shelf_id, book_id))


def add_book(
    session: Session, *, shelf_id: UUID, book_id: int, source_surface: str | None = None
) -> ShelfBook:
    membership = get_membership(session, shelf_id=shelf_id, book_id=book_id)
    if membership is None:
        membership = ShelfBook(shelf_id=shelf_id, book_id=book_id, source_surface=source_surface)
        session.add(membership)
        session.flush()
    return membership


def remove_book(session: Session, *, shelf_id: UUID, book_id: int) -> bool:
    """Returns True if a membership was actually removed (False if it wasn't there)."""
    membership = get_membership(session, shelf_id=shelf_id, book_id=book_id)
    if membership is None:
        return False
    session.delete(membership)
    session.flush()
    return True


def get_shelf_ids_for_book(session: Session, *, user_id: UUID, book_id: int) -> list[UUID]:
    """Which of this user's shelves currently contain this book (book detail's shelf controls)."""
    stmt = (
        select(ShelfBook.shelf_id)
        .join(Shelf, Shelf.id == ShelfBook.shelf_id)
        .where(Shelf.user_id == user_id, ShelfBook.book_id == book_id)
    )
    return list(session.execute(stmt).scalars().all())


def get_shelf_ids_for_books(
    session: Session, *, user_id: UUID, book_ids: Sequence[int]
) -> dict[int, list[UUID]]:
    """Batched form of :func:`get_shelf_ids_for_book` — search results
    (spec §9.6) need every result's shelf membership at once, not one query
    per row."""
    if not book_ids:
        return {}
    stmt = (
        select(ShelfBook.book_id, ShelfBook.shelf_id)
        .join(Shelf, Shelf.id == ShelfBook.shelf_id)
        .where(Shelf.user_id == user_id, ShelfBook.book_id.in_(book_ids))
    )
    result: dict[int, list[UUID]] = {}
    for book_id, shelf_id in session.execute(stmt).all():
        result.setdefault(book_id, []).append(shelf_id)
    return result


def get_owned_shelf_ids(session: Session, *, user_id: UUID, shelf_ids: Sequence[UUID]) -> set[UUID]:
    """Subset of shelf_ids that both exist and belong to user_id."""
    if not shelf_ids:
        return set()
    stmt = select(Shelf.id).where(Shelf.user_id == user_id, Shelf.id.in_(shelf_ids))
    return set(session.execute(stmt).scalars().all())


# --- Read-side queries (Phase 5: recommendation context/eligibility) --------


def get_all_shelved_book_ids(session: Session, *, user_id: UUID) -> set[int]:
    """Every book on any of this user's shelves — spec §5.5: Home excludes
    "books saved to any shelf"."""
    stmt = (
        select(ShelfBook.book_id)
        .join(Shelf, Shelf.id == ShelfBook.shelf_id)
        .where(Shelf.user_id == user_id)
    )
    return set(session.execute(stmt).scalars())


@dataclass(frozen=True)
class SavedBookRow:
    book_id: int
    shelf_id: UUID
    added_at: datetime


def get_saved_book_rows(session: Session, *, user_id: UUID, limit: int) -> list[SavedBookRow]:
    """Every shelf membership, un-collapsed (rec-spec §5).

    :func:`get_all_shelved_book_ids` flattens the same data to a set for
    eligibility; this keeps one row per `(book, shelf)` pair with its
    `added_at`, which is what shelf-scoped semantic profiling and
    recency-weighted seeding need. A book on three shelves appears three
    times here and once there — both are correct for their purpose.

    Most-recent-first so the `limit` truncates the oldest memberships
    rather than an arbitrary slice; `book_id` breaks timestamp ties so the
    result is deterministic (bulk saves share an `added_at`).
    """
    stmt = (
        select(ShelfBook.book_id, ShelfBook.shelf_id, ShelfBook.added_at)
        .join(Shelf, Shelf.id == ShelfBook.shelf_id)
        .where(Shelf.user_id == user_id)
        .order_by(ShelfBook.added_at.desc(), ShelfBook.book_id, ShelfBook.shelf_id)
        .limit(limit)
    )
    return [
        SavedBookRow(book_id=row.book_id, shelf_id=row.shelf_id, added_at=row.added_at)
        for row in session.execute(stmt)
    ]


def get_book_ids_in_shelf(session: Session, *, shelf_id: UUID) -> set[int]:
    """Books already in *this* shelf — spec §5.5: shelf discovery excludes
    "books already in that shelf" (books on *other* shelves remain eligible,
    which is exactly what scoping this to one shelf_id gives for free)."""
    stmt = select(ShelfBook.book_id).where(ShelfBook.shelf_id == shelf_id)
    return set(session.execute(stmt).scalars())
