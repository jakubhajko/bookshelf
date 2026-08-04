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

from fastapi import FastAPI

from book_app.core.config import Settings, get_settings
from book_app.core.database import create_db_engine, create_session_factory
from book_app.core.exceptions import register_exception_handlers
from book_app.core.health import router as health_router
from book_app.core.logging import configure_logging, get_logger
from book_app.core.middleware import RequestContextMiddleware, configure_cors
from book_app.modules.auth.api import router as auth_router
from book_app.modules.auth.dependencies import build_auth_rate_limiter

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

    app = FastAPI(title="Book Discovery API", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.db_engine = engine
    app.state.db_session_factory = session_factory
    app.state.auth_rate_limiter = build_auth_rate_limiter(resolved_settings)

    configure_cors(app, resolved_settings)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    app.include_router(health_router, prefix=API_PREFIX)
    app.include_router(auth_router, prefix=API_PREFIX)

    return app


app = create_app()
