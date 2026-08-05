"""Search HTTP route (spec §9.6). Request parsing only — ranking lives in
``repository.py``, enrichment in ``service.py`` (spec §4.2). GET-only, so no
CSRF dependency (spec §6.5 scopes CSRF to POST/PUT/PATCH/DELETE).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from book_app.core.dependencies import get_db
from book_app.modules.auth.dependencies import get_current_user
from book_app.modules.search import service as search_service
from book_app.modules.search.schemas import SearchResultsResponse
from book_app.modules.users.models import User

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/books", response_model=SearchResultsResponse)
def search_books(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=60),
    cursor: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SearchResultsResponse:
    items, next_cursor = search_service.search_books(
        db, user_id=current_user.id, query=q, limit=limit, cursor_str=cursor
    )
    return SearchResultsResponse(items=items, next_cursor=next_cursor)
