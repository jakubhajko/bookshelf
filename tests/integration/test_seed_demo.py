"""seed-demo CLI integration tests against real PostgreSQL (spec §16:
"Create a development demo user with representative shelves, ratings,
saves, and rejections. Never enable demo credentials in production.").
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from book_app.cli.seed_demo import (
    DEMO_USERNAME,
    DemoSeedingDisabledError,
    run_seed,
)
from book_app.core.config import Settings
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

TOTAL_BOOKS_NEEDED = 20


def _insert_enough_books(insert_book: Callable[..., int]) -> None:
    for i in range(TOTAL_BOOKS_NEEDED):
        insert_book(
            title=f"Demo Book {i}", work_id=f"demo-seed-{i}", ratings_count=100 - i
        )


def test_refuses_to_run_when_demo_mode_is_disabled(
    test_session_factory: sessionmaker[Session],
) -> None:
    settings = Settings(environment="test", demo_mode_enabled=False)
    with pytest.raises(DemoSeedingDisabledError):
        run_seed(test_session_factory, settings=settings)


def test_seeds_a_representative_demo_account(
    test_session_factory: sessionmaker[Session],
    test_engine: Engine,
    insert_book: Callable[..., int],
) -> None:
    _insert_enough_books(insert_book)
    settings = Settings(environment="test", demo_mode_enabled=True)

    report = run_seed(test_session_factory, settings=settings)

    assert report.username == DEMO_USERNAME
    assert report.rated_count > 0
    assert report.not_interested_count > 0
    assert report.shelved_count > 0
    assert len(report.shelf_names) == 2

    with test_engine.connect() as conn:
        user_id = conn.execute(
            text("SELECT id FROM users WHERE username = :u"), {"u": DEMO_USERNAME}
        ).scalar_one()
        rating_count = conn.execute(
            text(
                "SELECT count(*) FROM user_book_states "
                "WHERE user_id = :uid AND rating_value IS NOT NULL"
            ),
            {"uid": user_id},
        ).scalar_one()
        not_interested_count = conn.execute(
            text(
                "SELECT count(*) FROM user_book_states "
                "WHERE user_id = :uid AND not_interested = true"
            ),
            {"uid": user_id},
        ).scalar_one()
        shelf_count = conn.execute(
            text("SELECT count(*) FROM shelves WHERE user_id = :uid"), {"uid": user_id}
        ).scalar_one()

    assert rating_count == report.rated_count
    assert not_interested_count == report.not_interested_count
    assert shelf_count == 2


def test_rerunning_resets_rather_than_duplicates(
    test_session_factory: sessionmaker[Session],
    test_engine: Engine,
    insert_book: Callable[..., int],
) -> None:
    _insert_enough_books(insert_book)
    settings = Settings(environment="test", demo_mode_enabled=True)

    first = run_seed(test_session_factory, settings=settings)
    second = run_seed(test_session_factory, settings=settings)

    assert first.rated_count == second.rated_count
    assert first.shelved_count == second.shelved_count

    with test_engine.connect() as conn:
        user_count = conn.execute(
            text("SELECT count(*) FROM users WHERE username = :u"), {"u": DEMO_USERNAME}
        ).scalar_one()
        shelf_count = conn.execute(text("SELECT count(*) FROM shelves")).scalar_one()

    assert user_count == 1
    assert shelf_count == 2  # not 4 — the second run reset before reseeding
