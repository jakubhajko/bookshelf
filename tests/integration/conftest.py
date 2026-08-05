"""Shared fixtures for integration tests (spec §13.3: real PostgreSQL, never SQLite).

Runs against a dedicated ``book_app_test`` database — created fresh (drop +
recreate + migrate) once per test session, never the dev database `make
db-start` provisions (``book_app``). Recreating it from nothing and running
Alembic against it is also, itself, the "empty-db migrations" check spec
§19 asks for.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Iterator
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest
from book_app.core.config import Settings
from book_app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
APPS_API_DIR = REPO_ROOT / "apps" / "api"

TEST_DB_NAME = "book_app_test"
DEFAULT_DEV_DATABASE_URL = (
    "postgresql+psycopg://book_app:book_app@localhost:5434/book_app"
)


def _base_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DEV_DATABASE_URL)


def _run_alembic(*args: str, database_url: str) -> None:
    result = subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=APPS_API_DIR,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"`alembic {' '.join(args)}` failed (exit {result.returncode}):\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return str(make_url(_base_url()).set(database=TEST_DB_NAME))


@pytest.fixture
def run_alembic() -> Callable[..., None]:
    """Exposes the module-level helper as a fixture so tests don't cross-import test files."""
    return _run_alembic


@pytest.fixture(scope="session")
def fresh_test_database(test_database_url: str) -> Iterator[str]:
    admin_url = make_url(_base_url()).set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin_engine.dispose()

    _run_alembic("upgrade", "head", database_url=test_database_url)

    yield test_database_url


@pytest.fixture
def test_engine(fresh_test_database: str) -> Iterator[Engine]:
    engine = create_engine(fresh_test_database)
    yield engine
    engine.dispose()


@pytest.fixture
def test_session_factory(test_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False
    )


@pytest.fixture(autouse=True)
def _clean_all_tables(test_engine: Engine) -> None:
    """Truncate before each test — a clean slate regardless of prior test outcomes."""
    with test_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE auth_sessions, shelf_books, shelves, user_book_states, "
                "interaction_events, users, "
                "book_source_similarities, book_catalog_shelf_tags, "
                "book_genres, book_authors, catalog_shelf_tags, genres, authors, books "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def test_settings(test_database_url: str) -> Settings:
    return Settings(environment="test", database_url=test_database_url)


@pytest.fixture
def client(test_settings: Settings) -> Iterator[TestClient]:
    """An HTTP client for the real app, wired to the integration test database."""
    app = create_app(settings=test_settings)
    with TestClient(app) as test_client:
        yield test_client


def _insert_book(
    engine: Engine,
    *,
    title: str = "Test Book",
    work_id: str | None = None,
    primary_author_name: str | None = "Test Author",
    catalog_status: str = "ACTIVE",
    cover_object_key: str | None = None,
) -> int:
    with engine.begin() as conn:
        book_id: int = conn.execute(
            text(
                "INSERT INTO books "
                "(work_id, title, primary_author_name, catalog_status, cover_object_key) "
                "VALUES (:work_id, :title, :author, :status, :cover_object_key) RETURNING id"
            ),
            {
                "work_id": work_id or f"test-work-{uuid4()}",
                "title": title,
                "author": primary_author_name,
                "status": catalog_status,
                "cover_object_key": cover_object_key,
            },
        ).scalar_one()
    return book_id


@pytest.fixture
def insert_book(test_engine: Engine) -> Callable[..., int]:
    """Inserts a minimal-but-valid ``books`` row for tests that need a real
    book_id without running the full import pipeline; returns its id.
    Exposes the module-level helper as a fixture so tests don't
    cross-import test files — same reasoning as ``run_alembic`` above."""
    return partial(_insert_book, test_engine)
