"""Shelf HTTP routes (spec §9.3). Request parsing, status codes — no domain
logic here (spec §4.2), that's all in ``service.py``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from book_app.core.dependencies import get_db
from book_app.modules.auth.dependencies import get_current_user, require_csrf
from book_app.modules.shelves import service as shelves_service
from book_app.modules.shelves.models import Shelf
from book_app.modules.shelves.repository import ShelfSummary
from book_app.modules.shelves.schemas import (
    ShelfBookItem,
    ShelfCreateRequest,
    ShelfPublic,
    ShelfUpdateRequest,
)
from book_app.modules.users.models import User
from book_app.shared.pagination import Page

router = APIRouter(prefix="/shelves", tags=["shelves"])


def _to_shelf_public(summary: ShelfSummary) -> ShelfPublic:
    shelf = summary.shelf
    return ShelfPublic(
        id=shelf.id,
        name=shelf.name,
        description=shelf.description,
        book_count=summary.book_count,
        cover_object_keys=summary.cover_object_keys,
        created_at=shelf.created_at,
        updated_at=shelf.updated_at,
    )


def _new_shelf_to_public(shelf: Shelf) -> ShelfPublic:
    """A shelf fresh out of ``create_shelf`` cannot have any books yet —
    nothing else could have added one in the same transaction — so this
    skips the summary query rather than asking the DB to confirm zero."""
    return ShelfPublic(
        id=shelf.id,
        name=shelf.name,
        description=shelf.description,
        book_count=0,
        cover_object_keys=[],
        created_at=shelf.created_at,
        updated_at=shelf.updated_at,
    )


@router.get("", response_model=list[ShelfPublic])
def list_shelves(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> list[ShelfPublic]:
    summaries = shelves_service.list_shelves(db, user_id=current_user.id)
    return [_to_shelf_public(s) for s in summaries]


@router.post("", response_model=ShelfPublic, status_code=status.HTTP_201_CREATED)
def create_shelf(
    body: ShelfCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> ShelfPublic:
    shelf = shelves_service.create_shelf(
        db, user_id=current_user.id, name=body.name, description=body.description
    )
    return _new_shelf_to_public(shelf)


@router.get("/{shelf_id}", response_model=ShelfPublic)
def get_shelf(
    shelf_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> ShelfPublic:
    summary = shelves_service.get_shelf(db, user_id=current_user.id, shelf_id=shelf_id)
    return _to_shelf_public(summary)


@router.patch("/{shelf_id}", response_model=ShelfPublic)
def update_shelf(
    shelf_id: UUID,
    body: ShelfUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> ShelfPublic:
    updates = body.model_dump(exclude_unset=True)
    summary = shelves_service.update_shelf(
        db, user_id=current_user.id, shelf_id=shelf_id, updates=updates
    )
    return _to_shelf_public(summary)


@router.delete("/{shelf_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shelf(
    shelf_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> None:
    shelves_service.delete_shelf(db, user_id=current_user.id, shelf_id=shelf_id)


@router.get("/{shelf_id}/books", response_model=Page[ShelfBookItem])
def list_shelf_books(
    shelf_id: UUID,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Page[ShelfBookItem]:
    rows, next_cursor = shelves_service.list_shelf_books(
        db, user_id=current_user.id, shelf_id=shelf_id, cursor_str=cursor, limit=limit
    )
    items = [
        ShelfBookItem(
            book_id=r.book_id,
            work_id=r.work_id,
            title=r.title,
            primary_author_name=r.primary_author_name,
            cover_object_key=r.cover_object_key,
            added_at=r.added_at,
        )
        for r in rows
    ]
    return Page[ShelfBookItem](items=items, next_cursor=next_cursor)


@router.put("/{shelf_id}/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def add_book(
    shelf_id: UUID,
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> None:
    shelves_service.add_book_to_shelf(
        db, user_id=current_user.id, shelf_id=shelf_id, book_id=book_id
    )


@router.delete("/{shelf_id}/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_book(
    shelf_id: UUID,
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> None:
    shelves_service.remove_book_from_shelf(
        db, user_id=current_user.id, shelf_id=shelf_id, book_id=book_id
    )
