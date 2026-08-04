"""Auth use cases (spec §6): registration, login, refresh, logout,
change-password. Owns transactions — repositories never commit (spec §4.2).

Password rules are validated here, not via Pydantic field constraints on
the request schemas: a Pydantic validation error echoes the submitted value
in its error details, and a password must never appear in any response
body (spec §6.3: "never log or return").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from book_app.core.config import Settings
from book_app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    verify_password,
)
from book_app.modules.auth import repository as session_repository
from book_app.modules.auth.exceptions import (
    AccountDisabledError,
    IncorrectPasswordError,
    InvalidCredentialsError,
    InvalidPasswordError,
    PasswordMismatchError,
    SessionInvalidError,
)
from book_app.modules.users import repository as user_repository
from book_app.modules.users.exceptions import UsernameTakenError
from book_app.modules.users.models import User
from book_app.modules.users.username_rules import validate_username
from book_app.shared.enums import AccountStatus
from book_app.shared.text import normalize_for_uniqueness

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128


def _validate_password(password: str) -> None:
    if not (MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH):
        raise InvalidPasswordError(
            f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters."
        )


def register(session: Session, *, username: str, password: str, password_confirmation: str) -> User:
    """Creates the account only — does not start a session (spec §13.5 lists
    register and login as separate steps in the critical flow)."""
    validate_username(username)
    _validate_password(password)
    if password != password_confirmation:
        raise PasswordMismatchError()

    normalized = normalize_for_uniqueness(username)
    if user_repository.get_by_normalized_username(session, normalized) is not None:
        raise UsernameTakenError()

    password_hash = hash_password(password)
    try:
        user = user_repository.create_user(
            session,
            username=username,
            normalized_username=normalized,
            password_hash=password_hash,
        )
    except IntegrityError as exc:
        # Race: two concurrent registrations for the same normalized name.
        # The pre-check above is a UX nicety, not the source of truth — the
        # database's unique constraint is.
        session.rollback()
        raise UsernameTakenError() from exc

    session.commit()
    return user


@dataclass(frozen=True)
class LoginResult:
    user: User
    session_id: UUID
    access_token: str
    refresh_token: str
    csrf_token: str


def login(
    session: Session,
    *,
    username: str,
    password: str,
    user_agent: str | None,
    settings: Settings,
) -> LoginResult:
    normalized = normalize_for_uniqueness(username)
    user = user_repository.get_by_normalized_username(session, normalized)
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError()
    if user.account_status is not AccountStatus.ACTIVE:
        raise AccountDisabledError()

    now = datetime.now(UTC)
    refresh_token = generate_opaque_token()
    csrf_token = generate_opaque_token()
    auth_session = session_repository.create_session(
        session,
        user_id=user.id,
        refresh_token_hash=hash_opaque_token(refresh_token),
        csrf_token_hash=hash_opaque_token(csrf_token),
        expires_at=now + timedelta(days=settings.refresh_token_days),
        user_agent=user_agent,
    )
    access_token = create_access_token(
        user_id=user.id, session_id=auth_session.id, settings=settings
    )

    session.commit()
    return LoginResult(
        user=user,
        session_id=auth_session.id,
        access_token=access_token,
        refresh_token=refresh_token,
        csrf_token=csrf_token,
    )


@dataclass(frozen=True)
class RefreshResult:
    user: User
    access_token: str
    csrf_token: str


def refresh(session: Session, *, refresh_token: str, settings: Settings) -> RefreshResult:
    auth_session = session_repository.get_by_refresh_token_hash(
        session, hash_opaque_token(refresh_token)
    )
    now = datetime.now(UTC)
    if auth_session is None or auth_session.revoked_at is not None or auth_session.expires_at < now:
        raise SessionInvalidError()

    user = user_repository.get_by_id(session, auth_session.user_id)
    if user is None or user.account_status is not AccountStatus.ACTIVE:
        raise SessionInvalidError()

    # Rotate the CSRF token "when appropriate" (spec §6.5) — refresh is a
    # natural, regular moment to do so. The refresh token itself is not
    # rotated: the session persists for its full lifetime (spec §6.4), used
    # repeatedly to mint new short-lived access tokens.
    new_csrf_token = generate_opaque_token()
    session_repository.rotate_csrf_token(
        session, auth_session, csrf_token_hash=hash_opaque_token(new_csrf_token)
    )
    session_repository.touch(session, auth_session, now=now)

    access_token = create_access_token(
        user_id=user.id, session_id=auth_session.id, settings=settings
    )

    session.commit()
    return RefreshResult(user=user, access_token=access_token, csrf_token=new_csrf_token)


def logout(session: Session, *, refresh_token: str) -> None:
    """Revokes only the presented session (spec §6.1) and is idempotent —
    logging out twice, or with an already-expired cookie, is not an error."""
    auth_session = session_repository.get_by_refresh_token_hash(
        session, hash_opaque_token(refresh_token)
    )
    if auth_session is None or auth_session.revoked_at is not None:
        return
    session_repository.revoke(session, auth_session, now=datetime.now(UTC))
    session.commit()


def change_password(
    session: Session,
    *,
    user: User,
    current_password: str,
    new_password: str,
    new_password_confirmation: str,
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise IncorrectPasswordError()
    _validate_password(new_password)
    if new_password != new_password_confirmation:
        raise PasswordMismatchError()

    user_repository.update_password_hash(session, user, hash_password(new_password))
    session.commit()
