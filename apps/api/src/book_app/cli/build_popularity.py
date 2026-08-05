"""CLI: build the popularity recommendation artifact (spec §10.12, §11).

    uv run --project apps/api python -m book_app.cli.build_popularity [options]

or via ``make build-popularity``. Computes a Bayesian-shrunk popularity
score per active book from ``ratings_count``/``bx_ratings``/``bx_explicit``
(support) and ``average_rating`` (quality): "support adjustment" (spec
§10.12) pulls a book's score toward the catalog-wide mean when it has few
ratings, so two five-star reviews don't outrank thousands averaging 4.5.
``bx_explicit`` is a verified subset of ``bx_ratings`` (every active row has
``bx_explicit <= bx_ratings``) — counting it a second time in ``support`` is
a deliberate choice to weight explicit engagement more heavily, not a
double-counting bug. A fallback and baseline (spec §10.12), not a real
recommender.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from book_recommender.artifacts import ArtifactItemMapping, ArtifactManifest, LocalArtifactStorage
from sqlalchemy import Float, select
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session, sessionmaker

from book_app.core.config import get_settings
from book_app.core.database import create_db_engine, create_session_factory
from book_app.core.logging import configure_logging, get_logger
from book_app.modules.books import repository as books_repository
from book_app.modules.books.models import Book
from book_app.modules.recommendations import repository as recommendations_repository
from book_app.modules.recommendations.artifact_paths import (
    POPULARITY_ARTIFACT_DIR,
    POPULARITY_MODEL_NAME,
    resolve_artifact_root,
)
from book_app.shared.enums import CatalogStatus, ModelVersionStatus

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


@dataclass
class BuildReport:
    item_count: int
    model_version: str
    catalog_version: str
    dry_run: bool
    top_preview: list[dict[str, Any]]


def run_build(
    session_factory: sessionmaker[Session],
    *,
    artifact_root: Path,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
    dry_run: bool = False,
) -> BuildReport:
    with session_factory() as session:
        ranking = compute_popularity_ranking(session, prior_strength=prior_strength)
        catalog_version = books_repository.get_catalog_version(session)
        model_version = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        top_preview = [
            {"book_id": book_id, "work_id": work_id, "score": round(score, 4)}
            for book_id, work_id, score in ranking[:PREVIEW_SIZE]
        ]

        if dry_run or not ranking:
            return BuildReport(
                item_count=len(ranking),
                model_version=model_version,
                catalog_version=catalog_version,
                dry_run=dry_run,
                top_preview=top_preview,
            )

        manifest = ArtifactManifest(
            model_name=POPULARITY_MODEL_NAME,
            model_version=model_version,
            catalog_version=catalog_version,
            trained_at=datetime.now(UTC),
            item_count=len(ranking),
            item_mapping=tuple(
                ArtifactItemMapping(book_id=book_id, work_id=work_id, model_item_index=index)
                for index, (book_id, work_id, _) in enumerate(ranking)
            ),
            files=("scores.json",),
        )
        storage = LocalArtifactStorage(artifact_root)
        storage.save_manifest(POPULARITY_ARTIFACT_DIR, manifest)
        scores_path = storage.resolve(POPULARITY_ARTIFACT_DIR, "scores.json")
        scores_path.write_text(json.dumps({"scores": [score for _, _, score in ranking]}))

        recommendations_repository.retire_active_versions(session, model_name=POPULARITY_MODEL_NAME)
        recommendations_repository.create_model_version(
            session,
            model_name=POPULARITY_MODEL_NAME,
            model_version=model_version,
            catalog_version=catalog_version,
            provider_name="in_process",
            status=ModelVersionStatus.ACTIVE,
            manifest=manifest.model_dump(mode="json"),
            activated_at=datetime.now(UTC),
        )
        session.commit()

        return BuildReport(
            item_count=len(ranking),
            model_version=model_version,
            catalog_version=catalog_version,
            dry_run=False,
            top_preview=top_preview,
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

    mode = "[DRY RUN] " if report.dry_run else ""
    print(
        f"{mode}build_popularity: {report.item_count} books ranked, "
        f"model_version={report.model_version}, catalog_version={report.catalog_version}"
    )
    for row in report.top_preview:
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
