"""Import CLI against the real sample fixture (spec §13.3: "sample Parquet import").

Uses the actual ``data/sample/books.parquet`` fixture (see
scripts/data_import/build_sample_fixture.py), not a hand-crafted stand-in —
including the one deliberately-invalid row it carries over from the full
dataset (empty ``work_id``), so the rejection path is exercised against real
data, not a synthetic case.
"""

from __future__ import annotations

from pathlib import Path

from book_app.cli.import_catalog import run_import
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_BOOKS = REPO_ROOT / "data" / "sample" / "books.parquet"


def test_sample_fixture_exists() -> None:
    assert SAMPLE_BOOKS.is_file(), (
        "data/sample/books.parquet is missing - regenerate with "
        "`uv run --project apps/api python scripts/data_import/build_sample_fixture.py`"
    )


def test_import_upserts_books_and_relationships(
    test_session_factory: sessionmaker[Session], test_engine: Engine
) -> None:
    report = run_import(
        test_session_factory,
        source=SAMPLE_BOOKS,
        batch_size=100,
        dry_run=False,
        max_rejected_samples=5,
    )

    assert report.total_rows > 0
    assert report.books_upserted > 0
    assert report.rows_rejected >= 1  # the deliberately-invalid empty-work_id row

    with test_engine.connect() as conn:
        book_count = conn.execute(text("SELECT count(*) FROM books")).scalar_one()
        author_count = conn.execute(text("SELECT count(*) FROM authors")).scalar_one()
        book_author_count = conn.execute(
            text("SELECT count(*) FROM book_authors")
        ).scalar_one()

    assert book_count == report.books_upserted
    assert author_count > 0
    assert book_author_count > 0


def test_empty_work_id_row_is_rejected_not_upserted(
    test_session_factory: sessionmaker[Session], test_engine: Engine
) -> None:
    run_import(
        test_session_factory,
        source=SAMPLE_BOOKS,
        batch_size=100,
        dry_run=False,
        max_rejected_samples=5,
    )

    with test_engine.connect() as conn:
        blank_work_id_count = conn.execute(
            text("SELECT count(*) FROM books WHERE work_id = ''")
        ).scalar_one()
    assert blank_work_id_count == 0


def test_dry_run_persists_nothing(
    test_session_factory: sessionmaker[Session], test_engine: Engine
) -> None:
    report = run_import(
        test_session_factory,
        source=SAMPLE_BOOKS,
        batch_size=100,
        dry_run=True,
        max_rejected_samples=5,
    )

    assert report.books_upserted > 0  # counted during the run, just never committed

    with test_engine.connect() as conn:
        book_count = conn.execute(text("SELECT count(*) FROM books")).scalar_one()
    assert book_count == 0


def test_import_is_idempotent(
    test_session_factory: sessionmaker[Session], test_engine: Engine
) -> None:
    run_import(
        test_session_factory,
        source=SAMPLE_BOOKS,
        batch_size=100,
        dry_run=False,
        max_rejected_samples=5,
    )
    with test_engine.connect() as conn:
        counts_first = {
            table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in ("books", "authors", "book_authors", "genres", "book_genres")
        }

    run_import(
        test_session_factory,
        source=SAMPLE_BOOKS,
        batch_size=100,
        dry_run=False,
        max_rejected_samples=5,
    )
    with test_engine.connect() as conn:
        counts_second = {
            table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in ("books", "authors", "book_authors", "genres", "book_genres")
        }

    assert counts_first == counts_second
