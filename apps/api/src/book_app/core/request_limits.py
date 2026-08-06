"""General (non-auth) request limits (spec §14: "request limits") — a
per-IP rate limit across every route, plus a request-body size cap. Auth's
own, stricter, per-endpoint limiting (spec §14's "pluggable auth
rate-limit boundary," `modules/auth/dependencies.py`) is a separate,
unrelated boundary — this is the broader, coarser backstop spec §14 lists
as its own bullet.

Applied globally via ``FastAPI(dependencies=[...])`` in ``main.py`` rather
than ASGI middleware — ``Starlette``'s ``BaseHTTPMiddleware`` has a
long-documented history of exceptions raised inside ``dispatch()`` not
reliably reaching an app's own ``@app.exception_handler``s. A global
FastAPI dependency uses the exact same well-supported exception path the
existing per-route ``Depends(...)`` auth rate limiting already relies on
(`modules/auth/api.py`), just registered once for every route instead of
per-endpoint.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from book_app.core.config import Settings
from book_app.core.dependencies import get_request_settings
from book_app.shared.rate_limit import RateLimiter

# Health checks are polled frequently by infra (ALB target-group checks,
# local scripts) and must never be rate-limited — a false-positive block
# here could take the whole service down from an infra layer's point of
# view, exactly what this limit exists to prevent elsewhere.
_EXEMPT_PATH_PREFIXES = ("/api/v1/health/",)


def get_general_rate_limiter(request: Request) -> RateLimiter:
    """Mirrors ``modules.auth.dependencies.get_auth_rate_limiter`` — a
    separate limiter instance/keyspace from the auth-specific one, built
    once in ``create_app`` and stored on ``app.state``."""
    limiter: RateLimiter = request.app.state.general_rate_limiter
    return limiter


def check_general_rate_limit(
    request: Request, limiter: RateLimiter = Depends(get_general_rate_limiter)
) -> None:
    if request.url.path.startswith(_EXEMPT_PATH_PREFIXES):
        return
    client_ip = request.client.host if request.client else "unknown"
    if not limiter.check(f"general:{client_ip}"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests.")


def check_request_size(
    request: Request, settings: Settings = Depends(get_request_settings)
) -> None:
    """Rejects on `Content-Length` alone — cheap, and runs before any
    dependency or route code touches the body, so an oversized upload
    never reaches Pydantic parsing. Doesn't guard a request that omits or
    lies about `Content-Length`; a hard cap on the ASGI receive stream
    itself would be needed for that and is a heavier change than this
    phase's "request limits" bullet calls for.
    """
    content_length = request.headers.get("content-length")
    if content_length is None:
        return
    try:
        size = int(content_length)
    except ValueError:
        return
    if size > settings.max_request_body_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Request body too large.")
