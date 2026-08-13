"""CLI: build the compact item-metadata artifact (rec-spec §13, §18, §21).

    uv run --project apps/api python -m book_app.cli.build_item_metadata [options]

or via ``make build-item-metadata``. Exports the per-book fields the ranker,
the reason builder and interest inspection need at inference time, when
PostgreSQL is off-limits (ADR-0014): title, primary author and broad genre.

The cleaned shelf-tag columns are part of the format but stay empty until
R5 builds the tag cleaner — the implementation plan's own instruction for
this task ("create the artifact contract now and fill it there"). They are
written as an empty CSR with ``tags_version = null``, which the loader reads
as a declared absence rather than a corrupt artifact.

``primary_author_name`` and ``top_genre`` are read straight off ``books``
rather than joined from ``book_authors``/``book_genres``: the import
denormalizes them precisely so read paths don't need the join, and using the
same columns the book detail page uses keeps a recommendation reason from
naming a different author than the card beside it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from book_recommender.artifacts import LocalArtifactStorage, write_artifact, write_item_metadata
from book_recommender.artifacts.item_metadata import (
    METADATA_FILENAME,
    NO_GENRE_CODE,
    TAGS_VERSION_CONFIG_KEY,
)
from book_recommender.config import ITEM_METADATA
from sqlalchemy import select
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

logger = get_logger("book_app.cli.build_item_metadata")

PREVIEW_SIZE = 5

#: Titles are for diagnostics and reason strings, not display, so a long one
#: can be truncated. The cap keeps a pathological catalog row from dominating
#: the artifact's string blob.
MAX_TITLE_CHARS = 300
MAX_AUTHOR_CHARS = 200


def collect_item_metadata(
    session: Session,
) -> tuple[list[tuple[int, str]], list[str], list[str], list[int], list[str]]:
    """Returns ``(items, titles, authors, genre_codes, genre_vocab)``.

    Ordered by ``book_id`` to match
    ``books_repository.get_active_catalog_identities``, so every family built
    in one pass shares an identical item ordering.
    """
    stmt = (
        select(Book.id, Book.work_id, Book.title, Book.primary_author_name, Book.top_genre)
        .where(Book.catalog_status == CatalogStatus.ACTIVE)
        .order_by(Book.id)
    )

    items: list[tuple[int, str]] = []
    titles: list[str] = []
    authors: list[str] = []
    genre_codes: list[int] = []
    genre_vocab: list[str] = []
    code_by_genre: dict[str, int] = {}

    for book_id, work_id, title, author, genre in session.execute(stmt):
        items.append((book_id, work_id))
        titles.append((title or "")[:MAX_TITLE_CHARS])
        authors.append((author or "")[:MAX_AUTHOR_CHARS])
        if genre is None:
            genre_codes.append(NO_GENRE_CODE)
            continue
        if genre not in code_by_genre:
            code_by_genre[genre] = len(genre_vocab)
            genre_vocab.append(genre)
        genre_codes.append(code_by_genre[genre])

    return items, titles, authors, genre_codes, genre_vocab


def run_build(
    session_factory: sessionmaker[Session], *, artifact_root: Path, dry_run: bool = False
) -> ArtifactBuildReport:
    with session_factory() as session:
        items, titles, authors, genre_codes, genre_vocab = collect_item_metadata(session)
        catalog_version = books_repository.get_catalog_version(session)
        model_version = new_model_version()

        stats: dict[str, int | str] = {
            "items": len(items),
            "distinct_genres": len(genre_vocab),
            "items_without_genre": sum(1 for code in genre_codes if code == NO_GENRE_CODE),
            "items_without_author": sum(1 for author in authors if not author),
            "tags_version": "unset (R5)",
        }
        preview = [
            {
                "book_id": book_id,
                "title": titles[index],
                "author": authors[index],
                "genre": genre_vocab[genre_codes[index]] if genre_codes[index] >= 0 else None,
            }
            for index, (book_id, _) in enumerate(items[:PREVIEW_SIZE])
        ]

        if dry_run or not items:
            return ArtifactBuildReport(
                model_name=ITEM_METADATA.name,
                model_version=model_version,
                catalog_version=catalog_version,
                item_count=len(items),
                dry_run=dry_run,
                stats=stats,
                preview=preview,
            )

        written = write_artifact(
            LocalArtifactStorage(artifact_root),
            ITEM_METADATA,
            model_version=model_version,
            catalog_version=catalog_version,
            items=items,
            payloads={
                METADATA_FILENAME: lambda path: write_item_metadata(
                    path,
                    titles=titles,
                    authors=authors,
                    genre_codes=genre_codes,
                    genre_vocab=genre_vocab,
                )
            },
            config={
                TAGS_VERSION_CONFIG_KEY: None,
                "max_title_chars": MAX_TITLE_CHARS,
                "max_author_chars": MAX_AUTHOR_CHARS,
            },
        )
        register_model_version(session, ITEM_METADATA, written)
        session.commit()

        return ArtifactBuildReport(
            model_name=ITEM_METADATA.name,
            model_version=model_version,
            catalog_version=catalog_version,
            item_count=len(items),
            dry_run=False,
            checksums=written.checksums,
            stale_files=written.stale_files,
            stats=stats,
            preview=preview,
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the compact item-metadata recommender artifact."
    )
    parser.add_argument("--dry-run", action="store_true", help="Collect and report without writing")
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
            dry_run=args.dry_run,
        )
    finally:
        engine.dispose()

    print(report.summary_line())
    for line in report.warning_lines():
        print(line)
    for key, value in report.stats.items():
        print(f"  {key}: {value}")
    for row in report.preview:
        print(f"  #{row['book_id']}: {row['title']!r} — {row['author']!r} [{row['genre']}]")

    logger.info("build_item_metadata_completed", **report.stats, dry_run=report.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
