"""User persistence: no HTTP concerns, no commits (spec §4.2) — the caller's
service owns the transaction."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from book_app.modules.users.models import User


def get_by_id(session: Session, user_id: UUID) -> User | None:
    return session.get(User, user_id)


def get_by_normalized_username(session: Session, normalized_username: str) -> User | None:
    stmt = select(User).where(User.normalized_username == normalized_username)
    return session.execute(stmt).scalar_one_or_none()


def create_user(
    session: Session, *, username: str, normalized_username: str, password_hash: str
) -> User:
    user = User(
        username=username, normalized_username=normalized_username, password_hash=password_hash
    )
    session.add(user)
    session.flush()  # populate id/created_at without committing
    return user


def update_password_hash(session: Session, user: User, password_hash: str) -> None:
    user.password_hash = password_hash
    session.flush()
