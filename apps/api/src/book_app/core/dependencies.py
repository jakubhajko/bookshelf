"""Shared FastAPI dependencies.

Kept minimal in Phase 1: the engine/session accessors every later module's
``api.py`` will depend on. Domain-specific dependencies (current user, shelf
ownership, etc.) are added by their own modules starting Phase 3.
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session


def get_engine(request: Request) -> Engine:
    engine: Engine = request.app.state.db_engine
    return engine


def get_db(request: Request) -> Generator[Session, None, None]:
    """Yield a request-scoped session. The caller's service owns commit/rollback."""
    session_factory = request.app.state.db_session_factory
    session: Session = session_factory()
    try:
        yield session
    finally:
        session.close()
