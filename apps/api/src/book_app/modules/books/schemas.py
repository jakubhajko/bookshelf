"""Request/response schemas for book endpoints (spec §9.2). Never expose ORM
objects directly (spec §4.2) — built explicitly in ``service.py``/``api.py``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel


class BookAuthorPublic(BaseModel):
    name: str
    role: str | None


class BookUserState(BaseModel):
    """This user's relationship to the book (spec §5.2). Neutral is
    ``rating=None`` and ``not_interested=False``; the other two states are
    mutually exclusive by construction (enforced in ``modules.interactions``)."""

    rating: float | None
    not_interested: bool
    shelf_ids: list[UUID]


class BookDetail(BaseModel):
    """Spec §12.7's detail page fields, minus the similar-books grid (that's
    ``GET /recommendations/books/{id}/similar``, spec §9.5, Phase 5)."""

    id: int
    work_id: str
    title: str
    title_without_series: str | None
    description: str | None
    has_description: bool
    primary_author_name: str | None
    authors: list[BookAuthorPublic]
    top_genre: str | None
    genres: list[str]
    series_data: dict[str, Any] | None
    average_rating: float | None
    ratings_count: int | None
    text_reviews_count: int | None
    num_pages: int | None
    publication_year: int | None
    publisher: str | None
    language_code: str | None
    format: str | None
    is_ebook: bool | None
    cover_object_key: str | None
    has_cover: bool
    user_state: BookUserState


class PreferenceState(BaseModel):
    """Response for the rating/Not-Interested mutation endpoints — narrower
    than :class:`BookUserState` since those never change shelf membership
    (spec §5.3: "preserve shelf memberships"), so returning ``shelf_ids``
    would cost an extra query for a value that can't have changed."""

    rating: float | None
    not_interested: bool


class RatingRequest(BaseModel):
    rating: float


class ShelfSyncRequest(BaseModel):
    shelf_ids: list[UUID]
