"""build-item-metadata CLI against real PostgreSQL (rec-spec §13, §18, §21)."""

from __future__ import annotations

from pathlib import Path

from book_app.cli.build_item_metadata import run_build
from book_app.modules.recommendations.artifact_paths import read_catalog_snapshot
from book_recommender.artifacts import LocalArtifactStorage, load_item_metadata_artifact
from book_recommender.config import ITEM_METADATA
from book_recommender.content.tags import TAG_CLEANING_VERSION
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker


def _insert_book(
    engine: Engine,
    *,
    work_id: str,
    title: str,
    author: str | None = None,
    genre: str | None = None,
    status: str = "ACTIVE",
) -> int:
    with engine.begin() as conn:
        book_id: int = conn.execute(
            text(
                "INSERT INTO books "
                "(work_id, title, primary_author_name, top_genre, catalog_status) "
                "VALUES (:work_id, :title, :author, :genre, :status) RETURNING id"
            ),
            {
                "work_id": work_id,
                "title": title,
                "author": author,
                "genre": genre,
                "status": status,
            },
        ).scalar_one()
    return book_id


def _tag_book(engine: Engine, book_id: int, tags: list[str]) -> None:
    with engine.begin() as conn:
        for position, name in enumerate(tags):
            tag_id = conn.execute(
                text(
                    "INSERT INTO catalog_shelf_tags (name, normalized_name) "
                    "VALUES (:name, :name) "
                    "ON CONFLICT (normalized_name) DO UPDATE SET name = EXCLUDED.name "
                    "RETURNING id"
                ),
                {"name": name},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO book_catalog_shelf_tags "
                    "(book_id, tag_id, source_count, position) "
                    "VALUES (:book_id, :tag_id, :source_count, :position)"
                ),
                {
                    "book_id": book_id,
                    "tag_id": tag_id,
                    "source_count": 1000 - position,
                    "position": position,
                },
            )


def test_dry_run_persists_nothing(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    _insert_book(
        test_engine, work_id="w1", title="Dune", author="Herbert", genre="sci-fi"
    )

    report = run_build(test_session_factory, artifact_root=tmp_path, dry_run=True)

    assert report.dry_run is True
    assert report.item_count == 1
    assert list(tmp_path.iterdir()) == []


def test_metadata_round_trips_through_the_runtime_loader(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    dune = _insert_book(
        test_engine, work_id="w1", title="Dune", author="Frank Herbert", genre="sci-fi"
    )
    _insert_book(
        test_engine, work_id="w2", title="Hyperion", author="Simmons", genre="sci-fi"
    )

    run_build(test_session_factory, artifact_root=tmp_path)

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
    table = load_item_metadata_artifact(LocalArtifactStorage(tmp_path), catalog=catalog)

    row = table.get(dune)
    assert row is not None
    assert (row.title, row.author, row.genre, row.work_id) == (
        "Dune",
        "Frank Herbert",
        "sci-fi",
        "w1",
    )
    assert len(table) == 2


def test_a_book_without_author_or_genre_survives_with_declared_absences(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    """Neither column is NOT NULL in the catalog, and a missing genre must
    stay missing rather than becoming a category the reranker can group on."""
    sparse = _insert_book(test_engine, work_id="w1", title="Untitled Work")

    run_build(test_session_factory, artifact_root=tmp_path)

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
    table = load_item_metadata_artifact(LocalArtifactStorage(tmp_path), catalog=catalog)

    row = table.get(sparse)
    assert row is not None
    assert row.author == ""
    assert row.genre is None
    assert table.genre_of(sparse) is None


def test_inactive_books_are_excluded(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    active = _insert_book(test_engine, work_id="w1", title="Live", genre="sci-fi")
    hidden = _insert_book(test_engine, work_id="w2", title="Hidden", status="HIDDEN")

    report = run_build(test_session_factory, artifact_root=tmp_path)

    assert report.item_count == 1
    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
    table = load_item_metadata_artifact(LocalArtifactStorage(tmp_path), catalog=catalog)
    assert table.get(active) is not None
    assert table.get(hidden) is None


def test_cleaned_tags_are_written_and_declared(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    """R3 created this contract empty with ``tags_version: null``; R5 fills
    it. Both halves are asserted, so filling one without the other fails."""
    book_id = _insert_book(test_engine, work_id="w1", title="Dune", genre="sci-fi")
    _tag_book(test_engine, book_id, ["desert", "to-read", "politics"])

    run_build(test_session_factory, artifact_root=tmp_path)

    manifest = LocalArtifactStorage(tmp_path).load_manifest(ITEM_METADATA.directory)
    assert manifest.config["tags_version"] == TAG_CLEANING_VERSION

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
    table = load_item_metadata_artifact(LocalArtifactStorage(tmp_path), catalog=catalog)
    row = table.get(book_id)
    assert row is not None
    # The bookkeeping tag is gone; the thematic ones survive.
    assert row.tags == ("desert", "politics")
    assert table.has_tags is True


def test_a_book_with_only_bookkeeping_tags_ends_up_with_none(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    book_id = _insert_book(test_engine, work_id="w1", title="Dune", genre="sci-fi")
    _tag_book(test_engine, book_id, ["to-read", "kindle-books", "read-in-2011"])
    other = _insert_book(test_engine, work_id="w2", title="Other", genre="sci-fi")
    _tag_book(test_engine, other, ["desert"])

    run_build(test_session_factory, artifact_root=tmp_path)

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
    table = load_item_metadata_artifact(LocalArtifactStorage(tmp_path), catalog=catalog)
    row = table.get(book_id)
    assert row is not None
    assert row.tags == ()
    assert table.has_tags is True  # the other book has one


def test_rebuilding_the_same_data_produces_identical_payloads(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    _insert_book(
        test_engine, work_id="w1", title="Dune", author="Herbert", genre="sci-fi"
    )
    _insert_book(
        test_engine, work_id="w2", title="Solaris", author="Lem", genre="sci-fi"
    )

    first = run_build(test_session_factory, artifact_root=tmp_path / "a")
    second = run_build(test_session_factory, artifact_root=tmp_path / "b")

    assert first.checksums == second.checksums


def test_long_titles_are_capped(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    book_id = _insert_book(test_engine, work_id="w1", title="x" * 1000, genre="sci-fi")

    run_build(test_session_factory, artifact_root=tmp_path)

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
    table = load_item_metadata_artifact(LocalArtifactStorage(tmp_path), catalog=catalog)
    row = table.get(book_id)
    assert row is not None
    assert len(row.title) == 300
