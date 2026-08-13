"""CLI: build the popularity recommendation artifact (rec-spec §15).

    uv run --project apps/api python -m book_app.cli.build_popularity [options]

or via ``make build-popularity``. Computes a Bayesian-shrunk popularity
score per active book from ``ratings_count``/``bx_ratings``/``bx_explicit``
(support) and ``average_rating`` (quality): "support adjustment" pulls a
book's score toward the catalog-wide mean when it has few ratings, so two
five-star reviews don't outrank thousands averaging 4.5. ``bx_explicit`` is
a verified subset of ``bx_ratings`` (every active row has ``bx_explicit <=
bx_ratings``) — counting it a second time in ``support`` is a deliberate
choice to weight explicit engagement more heavily, not a double-counting
bug. A fallback and baseline (rec-spec §15), not a real recommender.

Recommender Phase R3 moved the file writing to
``book_recommender.artifacts.write_artifact``: scores are a ``float64``
column in ``scores.npz`` and the item mapping is a compact ``mapping.npz``,
where both used to be JSON with one object per catalog item.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from book_recommender.artifacts import LocalArtifactStorage, write_artifact, write_popularity_scores
from book_recommender.config import POPULARITY
from sqlalchemy import Float, select
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session, sessionmaker

from book_app.core.config import get_settings
from book_app.core.database import create_db_engine, create_session_factory
from book_app.core.logging import configure_logging, get_logger
from book_app.modules.books import repository as books_repository
from book_app.modules.books.models import Book
from book_app.modules.recommendations.artifact_build import (
    ArtifactBuildReport,
    new_model_version,
    register_model_version,
)
from book_app.modules.recommendations.artifact_paths import resolve_artifact_root
from book_app.shared.enums import CatalogStatus

logger = get_logger("book_app.cli.build_popularity")

DEFAULT_PRIOR_STRENGTH = 50.0
PREVIEW_SIZE = 10


def compute_popularity_ranking(
    session: Session, *, prior_strength: float
) -> list[tuple[int, str, float]]:
    """Returns ``(book_id, work_id, score)`` for every active book, most
    popular first."""
    global_mean_stmt = select(sa_func.avg(Book.average_rating)).where(
        Book.catalog_status == CatalogStatus.ACTIVE, Book.average_rating.isnot(None)
    )
    global_mean_raw = session.execute(global_mean_stmt).scalar_one()
    global_mean = float(global_mean_raw) if global_mean_raw is not None else 0.0

    support = (
        sa_func.coalesce(Book.ratings_count, 0)
        + sa_func.coalesce(Book.bx_ratings, 0)
        + sa_func.coalesce(Book.bx_explicit, 0)
    ).cast(Float)
    quality = sa_func.coalesce(Book.average_rating, global_mean)
    score = (support / (support + prior_strength)) * quality + (
        prior_strength / (support + prior_strength)
    ) * global_mean

    stmt = (
        select(Book.id, Book.work_id, score.label("score"))
        .where(Book.catalog_status == CatalogStatus.ACTIVE)
        .order_by(score.desc(), Book.id.asc())
    )
    return [(row.id, row.work_id, float(row.score)) for row in session.execute(stmt)]


def run_build(
    session_factory: sessionmaker[Session],
    *,
    artifact_root: Path,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
    dry_run: bool = False,
) -> ArtifactBuildReport:
    with session_factory() as session:
        ranking = compute_popularity_ranking(session, prior_strength=prior_strength)
        catalog_version = books_repository.get_catalog_version(session)
        model_version = new_model_version()
        top_preview = [
            {"book_id": book_id, "work_id": work_id, "score": round(score, 4)}
            for book_id, work_id, score in ranking[:PREVIEW_SIZE]
        ]

        if dry_run or not ranking:
            return ArtifactBuildReport(
                model_name=POPULARITY.name,
                model_version=model_version,
                catalog_version=catalog_version,
                item_count=len(ranking),
                dry_run=dry_run,
                stats={"prior_strength": str(prior_strength)},
                preview=top_preview,
            )

        scores = [score for _, _, score in ranking]
        written = write_artifact(
            LocalArtifactStorage(artifact_root),
            POPULARITY,
            model_version=model_version,
            catalog_version=catalog_version,
            items=[(book_id, work_id) for book_id, work_id, _ in ranking],
            payloads={"scores.npz": lambda path: write_popularity_scores(path, scores)},
            config={"prior_strength": prior_strength},
        )
        register_model_version(session, POPULARITY, written)
        session.commit()

        return ArtifactBuildReport(
            model_name=POPULARITY.name,
            model_version=model_version,
            catalog_version=catalog_version,
            item_count=len(ranking),
            dry_run=False,
            checksums=written.checksums,
            stale_files=written.stale_files,
            stats={"prior_strength": str(prior_strength)},
            preview=top_preview,
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the popularity recommendation artifact.")
    parser.add_argument(
        "--prior-strength",
        type=float,
        default=DEFAULT_PRIOR_STRENGTH,
        help="Bayesian shrinkage strength — higher pulls low-support books harder toward the mean",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute and preview without writing"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    configure_logging(settings)

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        report = run_build(
            session_factory,
            artifact_root=resolve_artifact_root(settings.artifact_storage_local_path),
            prior_strength=args.prior_strength,
            dry_run=args.dry_run,
        )
    finally:
        engine.dispose()

    print(report.summary_line())
    for line in report.warning_lines():
        print(line)
    for row in report.preview:
        print(f"  #{row['book_id']} ({row['work_id']}): {row['score']}")

    logger.info(
        "build_popularity_completed",
        item_count=report.item_count,
        model_version=report.model_version,
        catalog_version=report.catalog_version,
        dry_run=report.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
