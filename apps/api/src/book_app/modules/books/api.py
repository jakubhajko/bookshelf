"""Book HTTP routes (spec §9.2). Request parsing, status codes — no domain
logic here (spec §4.2): reads go through ``books.service``, preference/shelf
writes delegate straight to ``interactions.service``/``shelves.service``,
the modules that actually own those transitions.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from book_app.core.dependencies import get_db
from book_app.modules.auth.dependencies import get_current_user, require_csrf
from book_app.modules.books import service as books_service
from book_app.modules.books.schemas import (
    BookAuthorPublic,
    BookDetail,
    BookUserState,
    PreferenceState,
    RatingRequest,
    ShelfSyncRequest,
)
from book_app.modules.interactions import service as interactions_service
from book_app.modules.interactions.models import UserBookState
from book_app.modules.interactions.rating_scale import internal_to_public
from book_app.modules.shelves import service as shelves_service
from book_app.modules.shelves.schemas import ShelfIdsResponse
from book_app.modules.users.models import User

router = APIRouter(prefix="/books", tags=["books"])


def _to_book_detail(view: books_service.BookDetailView) -> BookDetail:
    book = view.book
    return BookDetail(
        id=book.id,
        work_id=book.work_id,
        title=book.title,
        title_without_series=book.title_without_series,
        description=book.description,
        has_description=book.has_description,
        primary_author_name=book.primary_author_name,
        authors=[BookAuthorPublic(name=a.name, role=a.role) for a in view.authors],
        top_genre=book.top_genre,
        genres=view.genres,
        series_data=book.series_data,
        average_rating=book.average_rating,
        ratings_count=book.ratings_count,
        text_reviews_count=book.text_reviews_count,
        num_pages=book.num_pages,
        publication_year=book.publication_year,
        publisher=book.publisher,
        language_code=book.language_code,
        format=book.format,
        is_ebook=book.is_ebook,
        cover_object_key=book.cover_object_key,
        has_cover=book.has_cover,
        user_state=BookUserState(
            rating=view.user_rating, not_interested=view.not_interested, shelf_ids=view.shelf_ids
        ),
    )


def _to_preference_state(state: UserBookState) -> PreferenceState:
    return PreferenceState(
        rating=internal_to_public(state.rating_value) if state.rating_value is not None else None,
        not_interested=state.not_interested,
    )


@router.get("/{book_id}", response_model=BookDetail)
def get_book(
    book_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
) -> BookDetail:
    view = books_service.get_book_detail(db, user_id=current_user.id, book_id=book_id)
    return _to_book_detail(view)


@router.put("/{book_id}/rating", response_model=PreferenceState)
def set_rating(
    book_id: int,
    body: RatingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> PreferenceState:
    state = interactions_service.set_rating(
        db, user_id=current_user.id, book_id=book_id, public_rating=body.rating
    )
    return _to_preference_state(state)


@router.delete("/{book_id}/rating", status_code=status.HTTP_204_NO_CONTENT)
def remove_rating(
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> None:
    interactions_service.remove_rating(db, user_id=current_user.id, book_id=book_id)


@router.put("/{book_id}/not-interested", response_model=PreferenceState)
def set_not_interested(
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> PreferenceState:
    state = interactions_service.set_not_interested(db, user_id=current_user.id, book_id=book_id)
    return _to_preference_state(state)


@router.delete("/{book_id}/not-interested", status_code=status.HTTP_204_NO_CONTENT)
def remove_not_interested(
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> None:
    interactions_service.remove_not_interested(db, user_id=current_user.id, book_id=book_id)


@router.put("/{book_id}/shelves", response_model=ShelfIdsResponse)
def sync_shelves(
    book_id: int,
    body: ShelfSyncRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> ShelfIdsResponse:
    shelf_ids = shelves_service.sync_book_shelves(
        db, user_id=current_user.id, book_id=book_id, shelf_ids=body.shelf_ids
    )
    return ShelfIdsResponse(shelf_ids=shelf_ids)
