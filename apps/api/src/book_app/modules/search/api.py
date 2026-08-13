"""Search HTTP routes (spec §9.6, rec-spec §4.4). Request parsing only —
ranking lives in ``repository.py``, enrichment and the submitted-search
write in ``service.py`` (spec §4.2).

The results route stays GET and side-effect free (it also backs the
debounced suggestions dropdown); logging a search is its own explicit POST,
which is why it needs CSRF and the results route doesn't.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from book_app.core.dependencies import get_db
from book_app.modules.auth.dependencies import get_current_user, require_csrf
from book_app.modules.search import service as search_service
from book_app.modules.search.schemas import (
    SearchQueryCreateRequest,
    SearchQueryResponse,
    SearchResultsResponse,
)
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


@router.post("/queries", response_model=SearchQueryResponse, status_code=status.HTTP_201_CREATED)
def record_search_query(
    body: SearchQueryCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> SearchQueryResponse:
    """Record a submitted search and hand back its id (rec-spec §4.4).

    Only the frontend's submit path calls this — pressing Enter, or
    choosing a recent-search chip. The suggestions dropdown never does,
    which is the whole reason this is separate from `GET /books` above.
    """
    row = search_service.record_submitted_search(
        db,
        user_id=current_user.id,
        query_text=body.query_text,
        session_id=body.session_id,
        surface=body.surface,
    )
    return SearchQueryResponse(id=row.id, query_text=row.query_text, occurred_at=row.occurred_at)
