"""SQLAlchemy engine/session setup.

Synchronous engine with request-scoped sessions (APP_SPECIFICATION.md §11).
Every module's ``models.py`` declares its ORM models against the single
``Base`` here, so Alembic's ``env.py`` sees one combined metadata object
regardless of which modules exist yet.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from book_app.core.config import Settings


class Base(DeclarativeBase):
    """Shared declarative base for every module's SQLAlchemy models."""


def create_db_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_max_overflow,
        pool_pre_ping=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Repositories never commit; services own the transaction (spec §11)."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def check_database_ready(engine: Engine) -> None:
    """Raise ``sqlalchemy.exc.SQLAlchemyError`` if PostgreSQL is unreachable."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
