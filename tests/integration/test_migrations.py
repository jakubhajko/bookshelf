"""Migrations apply to an empty PostgreSQL database (spec §13.3, §19).

``fresh_test_database`` (see conftest.py) already drops, recreates, and
migrates ``book_app_test`` from nothing for every test in this package —
this file makes that an explicit, named assertion rather than an implicit
side effect, and additionally proves the full down/up round trip.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Engine, create_engine, inspect, text

EXPECTED_TABLES = {
    "books",
    "authors",
    "book_authors",
    "genres",
    "book_genres",
    "catalog_shelf_tags",
    "book_catalog_shelf_tags",
    "book_source_similarities",
    "alembic_version",
}


def test_upgrade_head_creates_all_catalog_tables(test_engine: Engine) -> None:
    inspector = inspect(test_engine)
    assert EXPECTED_TABLES <= set(inspector.get_table_names())


def test_pg_trgm_extension_is_enabled(test_engine: Engine) -> None:
    with test_engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
        ).first()
    assert result is not None


def test_search_indexes_exist(test_engine: Engine) -> None:
    with test_engine.connect() as conn:
        names = {
            row[0]
            for row in conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'books'")
            )
        }
    assert "ix_books_title_trgm" in names
    assert "ix_books_primary_author_name_trgm" in names
    assert "ix_books_description_fts" in names


def test_downgrade_base_then_upgrade_head_is_clean(
    test_database_url: str, run_alembic: Callable[..., None]
) -> None:
    """The exact cycle validated manually during Phase 2 planning, as an automated test."""
    run_alembic("downgrade", "base", database_url=test_database_url)

    engine = create_engine(test_database_url)
    try:
        inspector = inspect(engine)
        remaining = set(inspector.get_table_names()) - {"alembic_version"}
        assert remaining == set()
    finally:
        engine.dispose()

    run_alembic("upgrade", "head", database_url=test_database_url)

    engine = create_engine(test_database_url)
    try:
        inspector = inspect(engine)
        assert EXPECTED_TABLES <= set(inspector.get_table_names())
    finally:
        engine.dispose()
