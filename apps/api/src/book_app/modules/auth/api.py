"""Auth HTTP routes (spec §9.1). Request parsing, status codes, cookies —
no domain logic here, that's all in ``service.py`` (spec §4.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from book_app.core.config import Settings, get_settings
from book_app.core.dependencies import get_db
from book_app.modules.auth import service as auth_service
from book_app.modules.auth.cookies import (
    REFRESH_TOKEN_COOKIE,
    clear_auth_cookies,
    set_auth_cookies,
)
from book_app.modules.auth.dependencies import (
    get_auth_rate_limiter,
    get_current_user,
    require_csrf,
)
from book_app.modules.auth.exceptions import NotAuthenticatedError, RateLimitedError
from book_app.modules.auth.schemas import ChangePasswordRequest, LoginRequest, RegisterRequest
from book_app.modules.users.models import User
from book_app.modules.users.schemas import UserPublic
from book_app.shared.rate_limit import RateLimiter
from book_app.shared.text import normalize_for_uniqueness

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
    rate_limiter: RateLimiter = Depends(get_auth_rate_limiter),
) -> User:
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.check(f"register:{client_ip}"):
        raise RateLimitedError()

    return auth_service.register(
        db,
        username=body.username,
        password=body.password,
        password_confirmation=body.password_confirmation,
    )


@router.post("/login", response_model=UserPublic)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    rate_limiter: RateLimiter = Depends(get_auth_rate_limiter),
) -> User:
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"login:{client_ip}:{normalize_for_uniqueness(body.username)}"
    if not rate_limiter.check(rate_key):
        raise RateLimitedError()

    result = auth_service.login(
        db,
        username=body.username,
        password=body.password,
        user_agent=request.headers.get("user-agent"),
        settings=settings,
    )
    set_auth_cookies(
        response,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        csrf_token=result.csrf_token,
        settings=settings,
    )
    return result.user


@router.post("/refresh", response_model=UserPublic)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if not refresh_token:
        raise NotAuthenticatedError()

    result = auth_service.refresh(db, refresh_token=refresh_token, settings=settings)
    set_auth_cookies(
        response,
        access_token=result.access_token,
        refresh_token=None,  # not rotated on every use — see service.refresh's docstring
        csrf_token=result.csrf_token,
        settings=settings,
    )
    return result.user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> None:
    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if refresh_token:
        auth_service.logout(db, refresh_token=refresh_token)
    clear_auth_cookies(response, settings=settings)


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> None:
    auth_service.change_password(
        db,
        user=current_user,
        current_password=body.current_password,
        new_password=body.new_password,
        new_password_confirmation=body.new_password_confirmation,
    )
