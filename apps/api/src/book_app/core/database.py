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
    """Engine configured to survive a transaction-mode connection pooler.

    ``pool_pre_ping`` checks a pooled connection is still alive before handing
    it out — a local Postgres over a Unix socket rarely drops one, a managed
    database across the public internet does (idle timeouts, pooler restarts,
    NAT expiry), and without this those surface as a random error on some
    unlucky request rather than a transparent reconnect.

    ``prepare_threshold=None`` disables psycopg's automatic server-side
    prepared statements. psycopg prepares a statement after it has been
    executed a few times, which is a useful optimisation when the client owns
    its backend connection for the whole session. Behind a *transaction-mode*
    pooler (Supabase's port 6543, PgBouncer, RDS Proxy) it is a bug: the
    pooler returns the backend to a shared pool after every transaction, so
    the next execution can land on a different backend where that prepared
    statement was never created — ``prepared statement "_pg3_0" does not
    exist``, intermittently, only under concurrency. Disabling it costs a
    little planning time per query and removes the failure mode entirely.

    Both settings are correct for a local, directly-connected Postgres too, so
    this is deliberately unconditional rather than another environment flag to
    get wrong.
    """
    return create_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_max_overflow,
        pool_pre_ping=True,
        connect_args={"prepare_threshold": None},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Repositories never commit; services own the transaction (spec §11)."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def check_database_ready(engine: Engine) -> None:
    """Raise ``sqlalchemy.exc.SQLAlchemyError`` if PostgreSQL is unreachable."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
