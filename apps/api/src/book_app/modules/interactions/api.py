"""Interaction HTTP routes (spec §9.4): the rated-books listing. Request
parsing, status codes — no domain logic here (spec §4.2), that's all in
``service.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from book_app.core.dependencies import get_db
from book_app.modules.auth.dependencies import get_current_user
from book_app.modules.interactions import service as interactions_service
from book_app.modules.interactions.rating_scale import internal_to_public
from book_app.modules.interactions.repository import RatingsSort
from book_app.modules.interactions.schemas import RatedBookItem
from book_app.modules.users.models import User
from book_app.shared.pagination import Page

router = APIRouter(prefix="/me", tags=["ratings"])

# The whole Query(...) object (not just its default=) has to be the
# module-level singleton — ruff's B008 flags any *call* used as an argument
# default, and Query(default=RatingsSort.RECENT) is still a call even when
# RatingsSort.RECENT itself is hoisted out.
_SORT_QUERY_PARAM = Query(default=RatingsSort.RECENT)


@router.get("/ratings", response_model=Page[RatedBookItem])
def list_ratings(
    sort: RatingsSort = _SORT_QUERY_PARAM,
    min_rating: float | None = Query(default=None),
    max_rating: float | None = Query(default=None),
    genre: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Page[RatedBookItem]:
    rows, next_cursor = interactions_service.list_ratings(
        db,
        user_id=current_user.id,
        sort=sort,
        min_rating=min_rating,
        max_rating=max_rating,
        genre=genre,
        cursor_str=cursor,
        limit=limit,
    )
    items = [
        RatedBookItem(
            book_id=r.book_id,
            work_id=r.work_id,
            title=r.title,
            primary_author_name=r.primary_author_name,
            cover_object_key=r.cover_object_key,
            rating=internal_to_public(r.rating_value),
            rated_at=r.rated_at,
        )
        for r in rows
    ]
    return Page[RatedBookItem](items=items, next_cursor=next_cursor)
