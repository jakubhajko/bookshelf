"""Auth session persistence: no HTTP concerns, no commits (spec §4.2) — the
caller's service owns the transaction."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, or_, select
from sqlalchemy.orm import Session

from book_app.modules.auth.models import AuthSession


def create_session(
    session: Session,
    *,
    user_id: UUID,
    refresh_token_hash: str,
    csrf_token_hash: str,
    expires_at: datetime,
    user_agent: str | None,
) -> AuthSession:
    auth_session = AuthSession(
        user_id=user_id,
        refresh_token_hash=refresh_token_hash,
        csrf_token_hash=csrf_token_hash,
        expires_at=expires_at,
        user_agent=user_agent,
    )
    session.add(auth_session)
    session.flush()
    return auth_session


def get_by_id(session: Session, session_id: UUID) -> AuthSession | None:
    return session.get(AuthSession, session_id)


def get_by_refresh_token_hash(session: Session, refresh_token_hash: str) -> AuthSession | None:
    stmt = select(AuthSession).where(AuthSession.refresh_token_hash == refresh_token_hash)
    return session.execute(stmt).scalar_one_or_none()


def revoke(session: Session, auth_session: AuthSession, *, now: datetime) -> None:
    auth_session.revoked_at = now
    session.flush()


def touch(session: Session, auth_session: AuthSession, *, now: datetime) -> None:
    auth_session.last_used_at = now
    session.flush()


def rotate_csrf_token(session: Session, auth_session: AuthSession, *, csrf_token_hash: str) -> None:
    auth_session.csrf_token_hash = csrf_token_hash
    session.flush()


def delete_expired_or_revoked(session: Session, *, now: datetime) -> int:
    """Hard-delete sessions that are expired or already revoked (the `cleanup_sessions` CLI)."""
    stmt = delete(AuthSession).where(
        or_(AuthSession.expires_at < now, AuthSession.revoked_at.is_not(None))
    )
    result = cast(CursorResult[Any], session.execute(stmt))
    session.flush()
    return result.rowcount
