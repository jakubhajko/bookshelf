"""Cookie names and set/clear helpers (spec §6.4-§6.5).

HttpOnly for access and refresh; the CSRF cookie is deliberately readable
by frontend JS (spec §6.5), which is what makes it a working CSRF defense
— an attacker's cross-origin page can trigger a request but can't read this
cookie to put its value in the `X-CSRF-Token` header itself.
"""

from __future__ import annotations

from fastapi import Response

from book_app.core.config import Settings

ACCESS_TOKEN_COOKIE = "access_token"
REFRESH_TOKEN_COOKIE = "refresh_token"
CSRF_TOKEN_COOKIE = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"

# The refresh token is the longest-lived, highest-value credential (~30
# days) — scoping its cookie to only the auth routes that read it narrows
# where it's ever sent, unlike access/csrf which every API request needs.
AUTH_ROUTES_PATH = "/api/v1/auth"


def _set_cookie(
    response: Response,
    name: str,
    value: str,
    *,
    max_age: int,
    httponly: bool,
    path: str,
    settings: Settings,
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=httponly,
        path=path,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
    )


def set_auth_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str | None,
    csrf_token: str,
    settings: Settings,
) -> None:
    """``refresh_token=None`` leaves that cookie untouched (spec §6.4: the
    refresh token isn't rotated on every use, only access/CSRF are)."""
    _set_cookie(
        response,
        ACCESS_TOKEN_COOKIE,
        access_token,
        max_age=settings.access_token_minutes * 60,
        httponly=True,
        path="/",
        settings=settings,
    )
    if refresh_token is not None:
        _set_cookie(
            response,
            REFRESH_TOKEN_COOKIE,
            refresh_token,
            max_age=settings.refresh_token_days * 24 * 60 * 60,
            httponly=True,
            path=AUTH_ROUTES_PATH,
            settings=settings,
        )
    _set_cookie(
        response,
        CSRF_TOKEN_COOKIE,
        csrf_token,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        httponly=False,
        path="/",
        settings=settings,
    )


def clear_auth_cookies(response: Response, *, settings: Settings) -> None:
    for name, path in (
        (ACCESS_TOKEN_COOKIE, "/"),
        (REFRESH_TOKEN_COOKIE, AUTH_ROUTES_PATH),
        (CSRF_TOKEN_COOKIE, "/"),
    ):
        response.delete_cookie(
            name,
            path=path,
            domain=settings.cookie_domain,
            secure=settings.cookie_secure,
            samesite=settings.cookie_samesite,
        )
