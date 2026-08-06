"""FastAPI dependencies for authenticated / CSRF-protected routes.

``get_access_token_claims`` -> ``get_current_session`` is the shared chain:
FastAPI caches a dependency's result per request, so a route depending on
both ``get_current_user`` and ``require_csrf`` still only decodes the JWT
and looks up the session once each — and, more importantly than the
caching, checking the session (not just the JWT signature/expiry) on every
authenticated request is what makes logout's revocation take effect
immediately instead of only once the ~15-minute access token would have
expired anyway.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from book_app.core.config import Settings
from book_app.core.dependencies import get_db, get_request_settings
from book_app.core.security import AccessTokenClaims, InvalidAccessTokenError, decode_access_token
from book_app.core.security import hash_opaque_token as _hash_opaque_token
from book_app.modules.auth import repository as session_repository
from book_app.modules.auth.cookies import ACCESS_TOKEN_COOKIE, CSRF_HEADER_NAME
from book_app.modules.auth.exceptions import (
    CsrfInvalidError,
    NotAuthenticatedError,
    SessionInvalidError,
)
from book_app.modules.auth.models import AuthSession
from book_app.modules.users import repository as user_repository
from book_app.modules.users.models import User
from book_app.shared.enums import AccountStatus
from book_app.shared.rate_limit import InMemoryFixedWindowRateLimiter, RateLimiter


def get_access_token_claims(
    request: Request, settings: Settings = Depends(get_request_settings)
) -> AccessTokenClaims:
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        raise NotAuthenticatedError()
    try:
        return decode_access_token(token, settings)
    except InvalidAccessTokenError as exc:
        raise NotAuthenticatedError() from exc


def get_current_session(
    claims: AccessTokenClaims = Depends(get_access_token_claims),
    db: Session = Depends(get_db),
) -> AuthSession:
    """Not just JWT-valid but *currently* live: not revoked, not expired.

    Without this check, logout (or the session-cleanup CLI) would only stop
    a stolen/former access token from working once it naturally expired —
    up to spec §6.4's ~15 minutes later — rather than immediately, which is
    what "revocation" (spec §14) is supposed to mean.
    """
    auth_session = session_repository.get_by_id(db, claims.session_id)
    now = datetime.now(UTC)
    if auth_session is None or auth_session.revoked_at is not None or auth_session.expires_at < now:
        raise SessionInvalidError()
    return auth_session


def get_current_user(
    claims: AccessTokenClaims = Depends(get_access_token_claims),
    _session: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> User:
    user = user_repository.get_by_id(db, claims.user_id)
    if user is None or user.account_status is not AccountStatus.ACTIVE:
        raise NotAuthenticatedError()
    return user


def require_csrf(
    request: Request,
    auth_session: AuthSession = Depends(get_current_session),
) -> None:
    """For POST/PUT/PATCH/DELETE routes only (spec §6.5) — not a dependency
    of GET routes."""
    provided = request.headers.get(CSRF_HEADER_NAME)
    if not provided or _hash_opaque_token(provided) != auth_session.csrf_token_hash:
        raise CsrfInvalidError()


def get_auth_rate_limiter(request: Request) -> RateLimiter:
    """The limiter instance lives on ``app.state`` (created once in
    ``create_app``) — a fresh instance per request would never accumulate
    any attempts and would be useless."""
    limiter: RateLimiter = request.app.state.auth_rate_limiter
    return limiter


def build_auth_rate_limiter(settings: Settings) -> InMemoryFixedWindowRateLimiter:
    return InMemoryFixedWindowRateLimiter(
        max_attempts=settings.auth_rate_limit_max_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
