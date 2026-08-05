"""Book use cases (spec §9.2). Read-only orchestration across the catalog,
interactions, and shelves modules — rating/Not-Interested/shelf-sync writes
are owned by ``modules.interactions``/``modules.shelves`` and called
directly from ``api.py``, not re-wrapped here.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from book_app.modules.books import repository as books_repository
from book_app.modules.books.exceptions import BookNotFoundError
from book_app.modules.books.models import Book
from book_app.modules.books.repository import AuthorRef
from book_app.modules.interactions import repository as interactions_repository
from book_app.modules.interactions.rating_scale import internal_to_public
from book_app.modules.shelves import repository as shelves_repository


@dataclass(frozen=True)
class BookDetailView:
    book: Book
    authors: list[AuthorRef]
    genres: list[str]
    user_rating: float | None
    not_interested: bool
    shelf_ids: list[UUID]


def get_book_detail(session: Session, *, user_id: UUID, book_id: int) -> BookDetailView:
    book = books_repository.get_by_id(session, book_id)
    if book is None:
        raise BookNotFoundError()

    authors = books_repository.get_authors_for_book(session, book_id)
    genres = books_repository.get_genre_names_for_book(session, book_id)

    state = interactions_repository.get_state(session, user_id=user_id, book_id=book_id)
    user_rating = (
        internal_to_public(state.rating_value)
        if state is not None and state.rating_value is not None
        else None
    )
    not_interested = state is not None and state.not_interested

    shelf_ids = shelves_repository.get_shelf_ids_for_book(session, user_id=user_id, book_id=book_id)

    return BookDetailView(
        book=book,
        authors=authors,
        genres=genres,
        user_rating=user_rating,
        not_interested=not_interested,
        shelf_ids=shelf_ids,
    )
