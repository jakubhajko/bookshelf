"""Recommendation HTTP routes (spec §9.5). Request parsing, status codes —
no domain logic here (spec §4.2), that's all in ``service.py``. GET-only, so
no CSRF dependency (spec §6.5 scopes CSRF to POST/PUT/PATCH/DELETE).
"""

from __future__ import annotations

from uuid import UUID

from book_recommender.contracts.provider import RecommendationProvider
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from book_app.core.dependencies import get_db
from book_app.modules.auth.dependencies import get_current_user
from book_app.modules.recommendations import service as recommendations_service
from book_app.modules.recommendations.dependencies import get_recommendation_provider
from book_app.modules.recommendations.schemas import (
    REASON_TEXT,
    RecommendationBookItem,
    RecommendationPageResponse,
)
from book_app.modules.recommendations.service import RecommendationPage
from book_app.modules.users.models import User

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

MAX_EXCLUDE_IDS = 500


def _parse_exclude(exclude: str | None) -> frozenset[int]:
    """``exclude`` is a client-tracked "already seen this session" list
    (spec §5.5: Home excludes "books already returned in the current feed
    session") — the persisted-batch design already guarantees no repeats
    *within* one batch (spec ADR-0007), so this only matters across
    separate top-level requests within the same browsing session."""
    if not exclude:
        return frozenset()
    ids: set[int] = set()
    for raw in exclude.split(",")[:MAX_EXCLUDE_IDS]:
        stripped = raw.strip()
        if stripped:
            try:
                ids.add(int(stripped))
            except ValueError:
                continue
    return frozenset(ids)


def _to_response(page: RecommendationPage) -> RecommendationPageResponse:
    return RecommendationPageResponse(
        request_id=page.request_id,
        surface=page.surface,
        model_version=page.model_version,
        items=[
            RecommendationBookItem(
                book_id=item.book.book_id,
                work_id=item.book.work_id,
                title=item.book.title,
                primary_author_name=item.book.primary_author_name,
                cover_object_key=item.book.cover_object_key,
                rank=item.rank,
                score=item.score,
                reason_code=item.reason_code,
                reason_text=REASON_TEXT.get(item.reason_code, item.reason_code),
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get("/home", response_model=RecommendationPageResponse)
async def get_home(
    limit: int = Query(default=20, ge=1, le=60),
    cursor: str | None = Query(default=None),
    exclude: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: RecommendationProvider = Depends(get_recommendation_provider),
) -> RecommendationPageResponse:
    page = await recommendations_service.get_home_recommendations(
        db,
        user_id=current_user.id,
        limit=limit,
        cursor_str=cursor,
        exclude_ids=_parse_exclude(exclude),
        provider=provider,
    )
    return _to_response(page)


@router.get("/shelves/{shelf_id}", response_model=RecommendationPageResponse)
async def get_shelf(
    shelf_id: UUID,
    limit: int = Query(default=20, ge=1, le=60),
    cursor: str | None = Query(default=None),
    exclude: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: RecommendationProvider = Depends(get_recommendation_provider),
) -> RecommendationPageResponse:
    page = await recommendations_service.get_shelf_recommendations(
        db,
        user_id=current_user.id,
        shelf_id=shelf_id,
        limit=limit,
        cursor_str=cursor,
        exclude_ids=_parse_exclude(exclude),
        provider=provider,
    )
    return _to_response(page)


@router.get("/books/{book_id}/similar", response_model=RecommendationPageResponse)
async def get_similar(
    book_id: int,
    limit: int = Query(default=20, ge=1, le=60),
    cursor: str | None = Query(default=None),
    exclude: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: RecommendationProvider = Depends(get_recommendation_provider),
) -> RecommendationPageResponse:
    page = await recommendations_service.get_similar_recommendations(
        db,
        user_id=current_user.id,
        source_book_id=book_id,
        limit=limit,
        cursor_str=cursor,
        exclude_ids=_parse_exclude(exclude),
        provider=provider,
    )
    return _to_response(page)
