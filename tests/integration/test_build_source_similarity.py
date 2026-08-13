"""build-source-similarity CLI against real PostgreSQL (rec-spec §14).

The invariant under test is the one rec-spec §14 asks the build to
re-validate rather than assume: every exported edge resolves to an *active*
catalog book. The foreign keys guarantee the row exists; they say nothing
about ``catalog_status``.
"""

from __future__ import annotations

from pathlib import Path

from book_app.cli.build_source_similarity import run_build
from book_app.modules.recommendations.artifact_paths import read_catalog_snapshot
from book_recommender.artifacts import (
    LocalArtifactStorage,
    load_source_similarity_artifact,
)
from book_recommender.config import SOURCE_SIMILARITY
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker


def _insert_book(
    engine: Engine, *, work_id: str, title: str, status: str = "ACTIVE"
) -> int:
    with engine.begin() as conn:
        book_id: int = conn.execute(
            text(
                "INSERT INTO books (work_id, title, catalog_status) "
                "VALUES (:work_id, :title, :status) RETURNING id"
            ),
            {"work_id": work_id, "title": title, "status": status},
        ).scalar_one()
    return book_id


def _insert_edge(
    engine: Engine, *, book_id: int, similar_book_id: int, rank: int
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO book_source_similarities "
                "(book_id, similar_book_id, rank, source) "
                "VALUES (:book_id, :similar_book_id, :rank, 'goodreads')"
            ),
            {"book_id": book_id, "similar_book_id": similar_book_id, "rank": rank},
        )


def _books(engine: Engine, count: int) -> list[int]:
    return [
        _insert_book(engine, work_id=f"w-{index}", title=f"Book {index}")
        for index in range(count)
    ]


def test_dry_run_persists_nothing(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    ids = _books(test_engine, 2)
    _insert_edge(test_engine, book_id=ids[0], similar_book_id=ids[1], rank=0)

    report = run_build(test_session_factory, artifact_root=tmp_path, dry_run=True)

    assert report.dry_run is True
    assert report.stats["edges_exported"] == 1
    assert list(tmp_path.iterdir()) == []
    with test_engine.connect() as conn:
        assert (
            conn.execute(text("SELECT count(*) FROM model_versions")).scalar_one() == 0
        )


def test_exported_graph_round_trips_through_the_runtime_loader(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    ids = _books(test_engine, 4)
    _insert_edge(test_engine, book_id=ids[0], similar_book_id=ids[1], rank=0)
    _insert_edge(test_engine, book_id=ids[0], similar_book_id=ids[2], rank=1)
    _insert_edge(test_engine, book_id=ids[3], similar_book_id=ids[0], rank=0)

    run_build(test_session_factory, artifact_root=tmp_path)

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
    graph = load_source_similarity_artifact(
        LocalArtifactStorage(tmp_path), catalog=catalog
    )

    assert graph.neighbor_book_ids(ids[0]) == (ids[1], ids[2])
    assert graph.neighbor_book_ids(ids[3]) == (ids[0],)
    assert graph.neighbor_book_ids(ids[1]) == ()
    assert graph.edge_count == 3
    assert graph.sources == ("goodreads",)


def test_edges_touching_an_inactive_book_are_dropped_and_counted(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    """rec-spec §14's "still validate this invariant during artifact build".
    A foreign key keeps the row alive after a book is retired; the artifact
    must not carry the edge."""
    ids = _books(test_engine, 2)
    retired = _insert_book(
        test_engine, work_id="w-retired", title="Retired", status="HIDDEN"
    )
    _insert_edge(test_engine, book_id=ids[0], similar_book_id=ids[1], rank=0)
    _insert_edge(test_engine, book_id=ids[0], similar_book_id=retired, rank=1)
    _insert_edge(test_engine, book_id=retired, similar_book_id=ids[0], rank=0)

    report = run_build(test_session_factory, artifact_root=tmp_path)

    assert report.stats["edges_in_database"] == 3
    assert report.stats["edges_exported"] == 1
    assert report.stats["dropped_out_of_catalog"] == 2
    assert report.item_count == 2

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
    graph = load_source_similarity_artifact(
        LocalArtifactStorage(tmp_path), catalog=catalog
    )
    assert graph.neighbor_book_ids(ids[0]) == (ids[1],)


def test_self_edges_are_dropped(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    ids = _books(test_engine, 2)
    _insert_edge(test_engine, book_id=ids[0], similar_book_id=ids[0], rank=0)
    _insert_edge(test_engine, book_id=ids[0], similar_book_id=ids[1], rank=1)

    report = run_build(test_session_factory, artifact_root=tmp_path)

    assert report.stats["dropped_self_edges"] == 1
    assert report.stats["edges_exported"] == 1


def test_every_active_book_gets_an_item_index_even_without_neighbours(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    """All families share one item space, so a book with no source
    neighbours still needs a ``model_item_index`` — it just gets an empty
    CSR row."""
    ids = _books(test_engine, 5)
    _insert_edge(test_engine, book_id=ids[0], similar_book_id=ids[1], rank=0)

    report = run_build(test_session_factory, artifact_root=tmp_path)

    assert report.item_count == 5
    assert report.stats["books_with_neighbors"] == 1


def test_rebuilding_the_same_data_produces_identical_payloads(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    """rec-spec §28's determinism requirement, end to end from PostgreSQL."""
    ids = _books(test_engine, 3)
    _insert_edge(test_engine, book_id=ids[0], similar_book_id=ids[1], rank=0)
    _insert_edge(test_engine, book_id=ids[2], similar_book_id=ids[0], rank=0)

    first = run_build(test_session_factory, artifact_root=tmp_path / "a")
    second = run_build(test_session_factory, artifact_root=tmp_path / "b")

    assert first.checksums == second.checksums
    assert set(first.checksums) == {"mapping.npz", "graph.npz"}


def test_build_registers_an_active_model_version(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    ids = _books(test_engine, 2)
    _insert_edge(test_engine, book_id=ids[0], similar_book_id=ids[1], rank=0)

    report = run_build(test_session_factory, artifact_root=tmp_path)

    with test_engine.connect() as conn:
        row = conn.execute(
            text("SELECT model_name, status, model_version FROM model_versions")
        ).one()
    assert row.model_name == SOURCE_SIMILARITY.name
    assert row.status == "ACTIVE"
    assert row.model_version == report.model_version


def test_manifest_stays_small_now_that_the_mapping_is_a_separate_file(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    """Schema version 1 inlined one JSON object per catalog item, which put
    an 8.9 MB row into ``model_versions.manifest`` for the real catalog."""
    ids = _books(test_engine, 10)
    _insert_edge(test_engine, book_id=ids[0], similar_book_id=ids[1], rank=0)

    run_build(test_session_factory, artifact_root=tmp_path)

    manifest_path = tmp_path / SOURCE_SIMILARITY.directory / "manifest.json"
    assert manifest_path.stat().st_size < 2000
    assert "work_id" not in manifest_path.read_text()


def test_no_active_books_produces_an_empty_report(
    test_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    report = run_build(test_session_factory, artifact_root=tmp_path)

    assert report.item_count == 0
    assert list(tmp_path.iterdir()) == []
