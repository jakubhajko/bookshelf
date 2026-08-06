"""FastAPI application factory.

``app`` at module level is the ASGI entrypoint (``uvicorn book_app.main:app``).
Tests call ``create_app()`` directly with their own ``Settings`` instead of
importing the module-level singleton, so nothing about running the test
suite requires a live database — only requests that actually touch the DB
(currently just ``GET /api/v1/health/ready``) do.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from book_app.core.config import Settings, get_settings
from book_app.core.covers import resolve_cover_storage_root
from book_app.core.covers import router as covers_router
from book_app.core.database import create_db_engine, create_session_factory
from book_app.core.exceptions import register_exception_handlers
from book_app.core.health import router as health_router
from book_app.core.logging import configure_logging, get_logger
from book_app.core.middleware import (
    RequestContextMiddleware,
    configure_cors,
    configure_security_headers,
)
from book_app.core.request_limits import check_general_rate_limit, check_request_size
from book_app.modules.auth.api import router as auth_router
from book_app.modules.auth.dependencies import build_auth_rate_limiter
from book_app.modules.books.api import router as books_router
from book_app.modules.interactions.api import router as interactions_router
from book_app.modules.recommendations.api import router as recommendations_router
from book_app.modules.search.api import router as search_router
from book_app.modules.shelves.api import router as shelves_router
from book_app.shared.rate_limit import InMemoryFixedWindowRateLimiter
from book_app.shared.storage.local import LocalFileStorage

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)
    logger = get_logger("book_app.startup")

    engine = create_db_engine(resolved_settings)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("app_started", environment=resolved_settings.environment.value)
        yield
        engine.dispose()
        logger.info("app_stopped")

    # General (non-auth) request limits (spec §14, core/request_limits.py) —
    # registered globally so every route gets them without each api.py
    # remembering to add its own Depends(...), the same way auth's own
    # rate limiting is opted into per-endpoint deliberately (spec §14
    # scopes that one to login/register specifically).
    app = FastAPI(
        title="Book Discovery API",
        version="0.1.0",
        lifespan=lifespan,
        dependencies=[Depends(check_general_rate_limit), Depends(check_request_size)],
    )
    app.state.settings = resolved_settings
    app.state.db_engine = engine
    app.state.db_session_factory = session_factory
    app.state.auth_rate_limiter = build_auth_rate_limiter(resolved_settings)
    app.state.general_rate_limiter = InMemoryFixedWindowRateLimiter(
        max_attempts=resolved_settings.general_rate_limit_max_requests,
        window_seconds=resolved_settings.general_rate_limit_window_seconds,
    )
    # Local only — see core/covers.py's module docstring for the S3/CloudFront
    # swap plan (spec §17) once a non-local `cover_storage_backend` exists.
    app.state.cover_storage = LocalFileStorage(
        resolve_cover_storage_root(resolved_settings.cover_storage_local_path)
    )

    configure_cors(app, resolved_settings)
    configure_security_headers(app, resolved_settings)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    app.include_router(health_router, prefix=API_PREFIX)
    app.include_router(covers_router, prefix=API_PREFIX)
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(books_router, prefix=API_PREFIX)
    app.include_router(shelves_router, prefix=API_PREFIX)
    app.include_router(interactions_router, prefix=API_PREFIX)
    app.include_router(recommendations_router, prefix=API_PREFIX)
    app.include_router(search_router, prefix=API_PREFIX)

    return app


app = create_app()
