"""Liveness/readiness endpoints (APP_SPECIFICATION.md §9.7).

Not a domain module (no service/repository/models — spec §4.1's module list
is auth/users/books/shelves/interactions/search/recommendations, and health
isn't a domain concept), so this lives under ``core`` instead of inventing an
unlisted ``modules/health``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from book_app.core.database import check_database_ready
from book_app.core.dependencies import get_engine
from book_app.core.exceptions import ServiceUnavailableError

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    """Always OK once the process is up; checks no dependencies."""
    return {"status": "ok"}


@router.get("/ready")
def ready(engine: Engine = Depends(get_engine)) -> dict[str, str]:
    """OK only if PostgreSQL is reachable."""
    try:
        check_database_ready(engine)
    except SQLAlchemyError as exc:
        raise ServiceUnavailableError("Database is unreachable.") from exc
    return {"status": "ok", "database": "ok"}
