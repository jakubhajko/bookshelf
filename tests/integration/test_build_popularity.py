"""build-popularity CLI integration tests against real PostgreSQL (spec
§10.12, §13.3).
"""

from __future__ import annotations

from pathlib import Path

from book_app.cli.build_popularity import run_build
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker


def _insert_scored_book(
    engine: Engine,
    *,
    work_id: str,
    title: str,
    ratings_count: int | None,
    average_rating: float | None,
    bx_ratings: int | None = 0,
    bx_explicit: int | None = 0,
) -> int:
    with engine.begin() as conn:
        book_id: int = conn.execute(
            text(
                "INSERT INTO books "
                "(work_id, title, catalog_status, ratings_count, average_rating, "
                "bx_ratings, bx_explicit) "
                "VALUES (:work_id, :title, 'ACTIVE', :ratings_count, :average_rating, "
                ":bx_ratings, :bx_explicit) RETURNING id"
            ),
            {
                "work_id": work_id,
                "title": title,
                "ratings_count": ratings_count,
                "average_rating": average_rating,
                "bx_ratings": bx_ratings,
                "bx_explicit": bx_explicit,
            },
        ).scalar_one()
    return book_id


def test_dry_run_persists_nothing(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    _insert_scored_book(
        test_engine, work_id="w1", title="A", ratings_count=100, average_rating=4.5
    )

    report = run_build(test_session_factory, artifact_root=tmp_path, dry_run=True)

    assert report.dry_run is True
    assert report.item_count == 1
    assert list(tmp_path.iterdir()) == []
    with test_engine.connect() as conn:
        version_count = conn.execute(
            text("SELECT count(*) FROM model_versions")
        ).scalar_one()
    assert version_count == 0


def test_high_support_high_rating_book_outranks_low_support_perfect_book(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    """The whole point of "support adjustment" (spec §10.12): a book with
    two five-star ratings shouldn't outrank one with thousands averaging
    4.5.

    Needs enough "anchor" books at a realistic, moderate rating for the
    catalog-wide mean to actually resemble one — with only the two books
    under test present, the global mean is just their own average, which
    defeats the entire premise: shrinking "lucky" toward a mean that's
    mostly *its own 5.0* barely shrinks it at all.
    """
    for i in range(20):
        _insert_scored_book(
            test_engine,
            work_id=f"anchor-{i}",
            title=f"Anchor {i}",
            ratings_count=200,
            average_rating=3.8,
        )
    trusted = _insert_scored_book(
        test_engine,
        work_id="trusted",
        title="Trusted",
        ratings_count=5000,
        average_rating=4.5,
    )
    lucky = _insert_scored_book(
        test_engine, work_id="lucky", title="Lucky", ratings_count=2, average_rating=5.0
    )

    report = run_build(test_session_factory, artifact_root=tmp_path)
    assert report.item_count == 22

    ranked_ids = [row["book_id"] for row in report.preview]
    trusted_rank = ranked_ids.index(trusted)
    lucky_rank = ranked_ids.index(lucky) if lucky in ranked_ids else len(ranked_ids)
    assert trusted_rank < lucky_rank


def test_run_build_writes_artifact_and_activates_model_version(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    _insert_scored_book(
        test_engine, work_id="w1", title="A", ratings_count=10, average_rating=4.0
    )
    _insert_scored_book(
        test_engine, work_id="w2", title="B", ratings_count=20, average_rating=3.0
    )

    report = run_build(test_session_factory, artifact_root=tmp_path)
    assert report.dry_run is False

    artifact_dir = tmp_path / "popularity" / "latest"
    assert (artifact_dir / "manifest.json").is_file()
    assert (artifact_dir / "scores.npz").is_file()
    assert (artifact_dir / "mapping.npz").is_file()
    assert report.stale_files == ()

    with test_engine.connect() as conn:
        row = conn.execute(
            text("SELECT model_name, status, model_version FROM model_versions")
        ).one()
    assert row.model_name == "popularity"
    assert row.status == "ACTIVE"
    assert row.model_version == report.model_version


def test_rebuilding_retires_the_previous_active_version(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    _insert_scored_book(
        test_engine, work_id="w1", title="A", ratings_count=10, average_rating=4.0
    )

    run_build(test_session_factory, artifact_root=tmp_path)
    run_build(test_session_factory, artifact_root=tmp_path)

    with test_engine.connect() as conn:
        rows = conn.execute(text("SELECT status FROM model_versions ORDER BY id")).all()
    # Exactly one ACTIVE popularity version ever exists at a time — the
    # first build's row must have been retired by the second.
    assert [r.status for r in rows] == ["RETIRED", "ACTIVE"]


def test_a_previous_formats_payload_is_reported_as_stale_not_deleted(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    """The pre-R3 popularity artifact wrote ``scores.json``. Rebuilding leaves
    it on disk — inert, since the loader reads only what the manifest declares
    — and the build says so rather than deleting a file it does not own."""
    _insert_scored_book(
        test_engine, work_id="w1", title="A", ratings_count=10, average_rating=4.0
    )
    leftover = tmp_path / "popularity" / "latest" / "scores.json"
    leftover.parent.mkdir(parents=True)
    leftover.write_text('{"scores": [1.0]}')

    report = run_build(test_session_factory, artifact_root=tmp_path)

    assert report.stale_files == ("scores.json",)
    assert leftover.is_file()
    assert report.warning_lines()


def test_no_active_books_produces_an_empty_report(
    test_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    report = run_build(test_session_factory, artifact_root=tmp_path)
    assert report.item_count == 0
    assert report.preview == []
