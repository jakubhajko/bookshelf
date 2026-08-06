"""CLI: seed a development demo account (spec §16: "Create a development
demo user with representative shelves, ratings, saves, and rejections.
Never enable demo credentials in production.").

    uv run --project apps/api python -m book_app.cli.seed_demo

or via ``make seed-demo``. Refuses to run unless ``demo_mode_enabled=True``
— finally consuming the field Phase 1 provisioned but nothing read until
now. This is a *second*, CLI-level guard on top of ``Settings``' own
startup-time rejection of ``demo_mode_enabled=True`` in production
(``core/config.py``'s ``_reject_insecure_production_defaults``): that
guard stops the *app* from starting with demo mode on in production; this
one stops the *seed script itself* from running, using the same
settings-driven signal, regardless of what ``DATABASE_URL`` happens to
point at.

Idempotent: re-running resets the demo user's ratings/Not-Interested
marks/shelves to the same fresh, representative state rather than erroring
on a second run or silently accumulating duplicates.

Everything goes through the real service layer (``auth_service``,
``interactions_service``, ``shelves_service``) — the same functions the
HTTP API calls — so seeded data is exactly as valid as anything a real
user could produce, with real events, not a raw-SQL shortcut.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from book_app.core.config import Settings, get_settings
from book_app.core.database import create_db_engine, create_session_factory
from book_app.core.logging import configure_logging, get_logger
from book_app.modules.auth import service as auth_service
from book_app.modules.books.models import Book
from book_app.modules.interactions import repository as interactions_repository
from book_app.modules.interactions import service as interactions_service
from book_app.modules.shelves import service as shelves_service
from book_app.modules.users import repository as user_repository
from book_app.modules.users.models import User
from book_app.shared.enums import CatalogStatus
from book_app.shared.text import normalize_for_uniqueness

logger = get_logger("book_app.cli.seed_demo")

# "demo" itself is a reserved username (spec §6.2,
# modules/users/username_rules.py) — deliberately kept unclaimable by real
# registrations, not a name this script fights to bypass.
DEMO_USERNAME = "demo_reader"
DEMO_PASSWORD = "demo-password-not-for-production"  # noqa: S105 - deliberately obvious, dev-only

RATED_BOOK_COUNT = 8
NOT_INTERESTED_BOOK_COUNT = 3
SHELVED_BOOK_COUNT = 6
# A spread representative of a real reader, not all five stars.
RATING_PATTERN = [5.0, 4.5, 4.0, 4.5, 3.5, 5.0, 3.0, 4.0]


class DemoSeedingDisabledError(RuntimeError):
    pass


def _pick_active_books(session: Session, *, offset: int, limit: int) -> list[int]:
    """Real, popular, active book ids. ``offset`` lets rated/rejected/shelved
    categories draw from different books instead of all overlapping the
    same top few."""
    stmt = (
        select(Book.id)
        .where(Book.catalog_status == CatalogStatus.ACTIVE, Book.ratings_count.isnot(None))
        .order_by(Book.ratings_count.desc(), Book.id.asc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.execute(stmt).scalars())


def _get_or_create_demo_user(session: Session) -> User:
    normalized = normalize_for_uniqueness(DEMO_USERNAME)
    existing = user_repository.get_by_normalized_username(session, normalized)
    if existing is not None:
        return existing
    return auth_service.register(
        session,
        username=DEMO_USERNAME,
        password=DEMO_PASSWORD,
        password_confirmation=DEMO_PASSWORD,
    )


def _reset_demo_state(session: Session, *, user_id: UUID) -> None:
    """Clears this user's existing ratings/Not-Interested/shelves through
    the same service functions the HTTP API uses, so re-running this
    script always lands on the same representative state rather than an
    accumulating mess from prior runs."""
    for book_id in interactions_repository.get_rated_book_ids(session, user_id=user_id):
        interactions_service.remove_rating(session, user_id=user_id, book_id=book_id)
    for book_id in interactions_repository.get_not_interested_book_ids(session, user_id=user_id):
        interactions_service.remove_not_interested(session, user_id=user_id, book_id=book_id)
    for shelf in shelves_service.list_shelves(session, user_id=user_id):
        shelves_service.delete_shelf(session, user_id=user_id, shelf_id=shelf.shelf.id)


@dataclass
class SeedReport:
    username: str
    password: str
    rated_count: int
    not_interested_count: int
    shelved_count: int
    shelf_names: list[str]


def run_seed(session_factory: sessionmaker[Session], *, settings: Settings) -> SeedReport:
    if not settings.demo_mode_enabled:
        raise DemoSeedingDisabledError(
            "DEMO_MODE_ENABLED is not set — refusing to seed demo data. "
            "This is deliberate (spec §16: 'never enable demo credentials in "
            "production'); set it in your local .env to seed a dev database."
        )

    with session_factory() as session:
        user = _get_or_create_demo_user(session)
        _reset_demo_state(session, user_id=user.id)

        rated_books = _pick_active_books(session, offset=0, limit=RATED_BOOK_COUNT)
        for book_id, rating in zip(rated_books, RATING_PATTERN, strict=False):
            interactions_service.set_rating(
                session, user_id=user.id, book_id=book_id, public_rating=rating
            )

        not_interested_books = _pick_active_books(
            session, offset=RATED_BOOK_COUNT, limit=NOT_INTERESTED_BOOK_COUNT
        )
        for book_id in not_interested_books:
            interactions_service.set_not_interested(session, user_id=user.id, book_id=book_id)

        shelved_books = _pick_active_books(
            session,
            offset=RATED_BOOK_COUNT + NOT_INTERESTED_BOOK_COUNT,
            limit=SHELVED_BOOK_COUNT,
        )
        currently_reading = shelves_service.create_shelf(
            session,
            user_id=user.id,
            name="Currently Reading",
            description="What I'm reading right now.",
        )
        favorites = shelves_service.create_shelf(
            session, user_id=user.id, name="Favorites", description="Books I love and recommend."
        )
        midpoint = len(shelved_books) // 2
        for book_id in shelved_books[:midpoint]:
            shelves_service.add_book_to_shelf(
                session, user_id=user.id, shelf_id=currently_reading.id, book_id=book_id
            )
        for book_id in shelved_books[midpoint:]:
            shelves_service.add_book_to_shelf(
                session, user_id=user.id, shelf_id=favorites.id, book_id=book_id
            )

        return SeedReport(
            username=DEMO_USERNAME,
            password=DEMO_PASSWORD,
            rated_count=len(rated_books),
            not_interested_count=len(not_interested_books),
            shelved_count=len(shelved_books),
            shelf_names=[currently_reading.name, favorites.name],
        )


def main(argv: list[str] | None = None) -> int:
    # No options yet — accepted for entrypoint consistency with the other cli/* scripts.
    del argv
    settings = get_settings()
    configure_logging(settings)

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        report = run_seed(session_factory, settings=settings)
    except DemoSeedingDisabledError as exc:
        print(f"seed_demo: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(f"seed_demo: user={report.username!r} password={report.password!r}")
    print(f"  rated: {report.rated_count} books")
    print(f"  Not Interested: {report.not_interested_count} books")
    print(f"  shelves: {', '.join(report.shelf_names)} ({report.shelved_count} books total)")

    logger.info(
        "seed_demo_completed",
        username=report.username,
        rated_count=report.rated_count,
        not_interested_count=report.not_interested_count,
        shelved_count=report.shelved_count,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
