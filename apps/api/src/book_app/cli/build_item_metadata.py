"""CLI: build the compact item-metadata artifact (rec-spec §13, §18, §21).

    uv run --project apps/api python -m book_app.cli.build_item_metadata [options]

or via ``make build-item-metadata``. Exports the per-book fields the ranker,
the reason builder and interest inspection need at inference time, when
PostgreSQL is off-limits (ADR-0014): title, primary author and broad genre.

The cleaned shelf-tag columns were written empty in R3 with
``tags_version = null`` — a declared absence the loader accepts — and are
filled here in R5, now that ``book_recommender.content.tags`` exists. The
contract did not change; only the data did.

``primary_author_name`` and ``top_genre`` are read straight off ``books``
rather than joined from ``book_authors``/``book_genres``: the import
denormalizes them precisely so read paths don't need the join, and using the
same columns the book detail page uses keeps a recommendation reason from
naming a different author than the card beside it.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from book_recommender.artifacts import LocalArtifactStorage, write_artifact, write_item_metadata
from book_recommender.artifacts.item_metadata import (
    METADATA_FILENAME,
    NO_GENRE_CODE,
    TAGS_VERSION_CONFIG_KEY,
)
from book_recommender.config import ITEM_METADATA
from book_recommender.content.tags import TAG_CLEANING_VERSION, clean_tags
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from book_app.core.config import get_settings
from book_app.core.database import create_db_engine, create_session_factory
from book_app.core.logging import configure_logging, get_logger
from book_app.modules.books import repository as books_repository
from book_app.modules.books.models import Book, BookCatalogShelfTag, CatalogShelfTag
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


@dataclass(frozen=True)
class ItemMetadataColumns:
    """Positional columns in ``model_item_index`` order."""

    items: list[tuple[int, str]]
    titles: list[str]
    authors: list[str]
    genre_codes: list[int]
    genre_vocab: list[str]
    tag_indptr: list[int]
    tag_codes: list[int]
    tag_vocab: list[str]


def collect_item_metadata(session: Session) -> ItemMetadataColumns:
    """Read every active book's card fields and cleaned tags.

    Ordered by ``book_id`` to match
    ``books_repository.get_active_catalog_identities``, so every family built
    in one pass shares an identical item ordering.
    """
    stmt = (
        select(Book.id, Book.work_id, Book.title, Book.primary_author_name, Book.top_genre)
        .where(Book.catalog_status == CatalogStatus.ACTIVE)
        .order_by(Book.id)
    )
    tags_by_book = _cleaned_tags_by_book(session)

    items: list[tuple[int, str]] = []
    titles: list[str] = []
    authors: list[str] = []
    genre_codes: list[int] = []
    genre_vocab: list[str] = []
    code_by_genre: dict[str, int] = {}
    tag_indptr: list[int] = [0]
    tag_codes: list[int] = []
    tag_vocab: list[str] = []
    code_by_tag: dict[str, int] = {}

    for book_id, work_id, title, author, genre in session.execute(stmt):
        items.append((book_id, work_id))
        titles.append((title or "")[:MAX_TITLE_CHARS])
        authors.append((author or "")[:MAX_AUTHOR_CHARS])

        if genre is None:
            genre_codes.append(NO_GENRE_CODE)
        else:
            if genre not in code_by_genre:
                code_by_genre[genre] = len(genre_vocab)
                genre_vocab.append(genre)
            genre_codes.append(code_by_genre[genre])

        for tag in tags_by_book.get(book_id, ()):
            if tag not in code_by_tag:
                code_by_tag[tag] = len(tag_vocab)
                tag_vocab.append(tag)
            tag_codes.append(code_by_tag[tag])
        tag_indptr.append(len(tag_codes))

    return ItemMetadataColumns(
        items=items,
        titles=titles,
        authors=authors,
        genre_codes=genre_codes,
        genre_vocab=genre_vocab,
        tag_indptr=tag_indptr,
        tag_codes=tag_codes,
        tag_vocab=tag_vocab,
    )


def _cleaned_tags_by_book(session: Session) -> dict[int, tuple[str, ...]]:
    """Cleaned shelf tags per book, ordered by reader support.

    The same cleaner the content builder uses, so the tags the ranker shows
    are exactly the tags the encoder read (rec-spec §11.2).
    """
    stmt = (
        select(BookCatalogShelfTag.book_id, CatalogShelfTag.name)
        .join(CatalogShelfTag, CatalogShelfTag.id == BookCatalogShelfTag.tag_id)
        .order_by(
            BookCatalogShelfTag.book_id,
            BookCatalogShelfTag.source_count.desc().nullslast(),
            BookCatalogShelfTag.position,
        )
    )
    raw: dict[int, list[str]] = {}
    for book_id, name in session.execute(stmt):
        raw.setdefault(book_id, []).append(name)
    return {book_id: clean_tags(names) for book_id, names in raw.items()}


def run_build(
    session_factory: sessionmaker[Session], *, artifact_root: Path, dry_run: bool = False
) -> ArtifactBuildReport:
    with session_factory() as session:
        columns = collect_item_metadata(session)
        items = columns.items
        genre_codes = columns.genre_codes
        genre_vocab = columns.genre_vocab
        authors = columns.authors
        titles = columns.titles
        catalog_version = books_repository.get_catalog_version(session)
        model_version = new_model_version()

        stats: dict[str, int | str] = {
            "items": len(items),
            "distinct_genres": len(genre_vocab),
            "items_without_genre": sum(1 for code in genre_codes if code == NO_GENRE_CODE),
            "items_without_author": sum(1 for author in authors if not author),
            "distinct_tags": len(columns.tag_vocab),
            "tag_links": len(columns.tag_codes),
            "items_without_tags": sum(
                1
                for index in range(len(items))
                if columns.tag_indptr[index + 1] == columns.tag_indptr[index]
            ),
            "tags_version": TAG_CLEANING_VERSION,
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
                    tag_indptr=columns.tag_indptr,
                    tag_codes=columns.tag_codes,
                    tag_vocab=columns.tag_vocab,
                )
            },
            config={
                TAGS_VERSION_CONFIG_KEY: TAG_CLEANING_VERSION,
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
