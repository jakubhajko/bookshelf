"""Session cleanup repository tests (spec §11: "clean sessions" CLI)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from book_app.modules.auth import repository as session_repository
from book_app.modules.users import repository as user_repository
from book_app.modules.users.models import User
from sqlalchemy.orm import Session, sessionmaker


def _make_user(db: Session, username: str = "cleanup_target") -> User:
    return user_repository.create_user(
        db,
        username=username,
        normalized_username=username,
        password_hash="irrelevant-for-this-test",
    )


def test_deletes_expired_and_revoked_but_keeps_active(
    test_session_factory: sessionmaker[Session],
) -> None:
    now = datetime.now(UTC)
    with test_session_factory() as db:
        user = _make_user(db)

        active = session_repository.create_session(
            db,
            user_id=user.id,
            refresh_token_hash="active-hash",
            csrf_token_hash="csrf-1",
            expires_at=now + timedelta(days=10),
            user_agent=None,
        )
        expired = session_repository.create_session(
            db,
            user_id=user.id,
            refresh_token_hash="expired-hash",
            csrf_token_hash="csrf-2",
            expires_at=now - timedelta(days=1),
            user_agent=None,
        )
        revoked = session_repository.create_session(
            db,
            user_id=user.id,
            refresh_token_hash="revoked-hash",
            csrf_token_hash="csrf-3",
            expires_at=now + timedelta(days=10),
            user_agent=None,
        )
        session_repository.revoke(db, revoked, now=now)
        db.commit()

        deleted_count = session_repository.delete_expired_or_revoked(db, now=now)
        db.commit()

        assert deleted_count == 2
        assert session_repository.get_by_id(db, active.id) is not None
        assert session_repository.get_by_id(db, expired.id) is None
        assert session_repository.get_by_id(db, revoked.id) is None


def test_no_op_when_nothing_to_clean(
    test_session_factory: sessionmaker[Session],
) -> None:
    now = datetime.now(UTC)
    with test_session_factory() as db:
        user = _make_user(db)
        session_repository.create_session(
            db,
            user_id=user.id,
            refresh_token_hash="still-active",
            csrf_token_hash="csrf",
            expires_at=now + timedelta(days=10),
            user_agent=None,
        )
        db.commit()

        assert session_repository.delete_expired_or_revoked(db, now=now) == 0
