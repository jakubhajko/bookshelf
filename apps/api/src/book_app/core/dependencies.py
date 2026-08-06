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

from book_app.core.config import Settings


def get_engine(request: Request) -> Engine:
    engine: Engine = request.app.state.db_engine
    return engine


def get_request_settings(request: Request) -> Settings:
    """The `Settings` instance *this app was actually built with*
    (`create_app(settings=...)`), not `core.config.get_settings()`'s
    `@lru_cache`d process-wide singleton — that cache is populated once,
    by whichever `Settings()` call happens first in the process (in
    practice, `main.py`'s own module-level `app = create_app()` on first
    import), and stays that value for the rest of the process regardless
    of what `Settings` a *specific* `create_app()` call was given
    afterward. A real, if previously dormant, bug: found while writing a
    Phase 9 test that builds its own `Settings(cookie_secure=True)` and
    expected auth's cookie-setting to reflect it — every `Depends(get_settings)`
    call site silently read the default instance instead. Fixed here and
    at every call site (`modules/auth/api.py`,
    `modules/auth/dependencies.py`, `core/request_limits.py`) — dormant
    until now because no *existing* test had overridden a settings field
    `Depends(get_settings)` code actually reads.
    """
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Generator[Session, None, None]:
    """Yield a request-scoped session. The caller's service owns commit/rollback."""
    session_factory = request.app.state.db_session_factory
    session: Session = session_factory()
    try:
        yield session
    finally:
        session.close()
