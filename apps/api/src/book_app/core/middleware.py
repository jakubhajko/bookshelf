"""Request-scoped context: request IDs, access logging, CORS, and security
headers. CSRF verification and rate limiting live elsewhere
(`modules/auth/dependencies.py`, `core/request_limits.py`).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from book_app.core.config import Settings

logger = structlog.get_logger("book_app.request")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns/propagates a request ID and emits one structured access-log line per request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER, str(uuid.uuid4()))
        request.state.request_id = request_id
        start = time.perf_counter()

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


def configure_cors(app: FastAPI, settings: Settings) -> None:
    """Exact, credentialed CORS — never a wildcard origin (spec §14)."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """spec §14 "security headers". Deliberately does **not** set a
    Content-Security-Policy, `Cross-Origin-Resource-Policy`, or
    `Cross-Origin-Opener-Policy`: this API is consumed cross-origin by the
    frontend by design (different ports even in local dev, spec §6.4), so
    CORP/COOP would block the app's own legitimate fetches. A CSP mainly
    matters for HTML a browser executes — this API returns HTML only from
    `/docs`/`/redoc` (interactive OpenAPI UI, which loads its assets from a
    CDN a strict `script-src` would break) and JSON everywhere else, where
    CSP has nothing to restrict. The CSP that actually matters — for what
    the SPA's own JS executes — belongs on the frontend's static-asset
    server instead (production nginx config, spec §17)."""

    def __init__(self, app: object, *, hsts_enabled: bool) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._hsts_enabled = hsts_enabled

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if self._hsts_enabled:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response


def configure_security_headers(app: FastAPI, settings: Settings) -> None:
    # HSTS only makes sense once traffic is actually HTTPS-only — gated on
    # the same `cookie_secure` flag spec §6.4's cookie security already
    # uses for exactly that condition, not a separate setting. Over plain
    # HTTP in local dev, browsers ignore the header anyway, but setting it
    # unconditionally would be misleading in the code, not just inert.
    app.add_middleware(SecurityHeadersMiddleware, hsts_enabled=settings.cookie_secure)
