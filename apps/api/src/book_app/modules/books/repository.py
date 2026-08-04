"""Catalog persistence: batched upserts. No commits (spec §4.2) — the CLI
caller owns the transaction. No HTTP concerns.

Two-pass design, driven by the CLI:

1. :func:`upsert_books_batch` + :func:`sync_authors_batch` +
   :func:`sync_genres_batch` + :func:`sync_shelf_tags_batch` run per batch
   while streaming the source file.
2. :func:`resolve_similarities` + :func:`replace_book_similarities_batch`
   run afterward, once the *complete* work_id/source_book_id -> internal id
   map exists — ``book_source_similarities`` is self-referential
   (``similar_book_id`` points at another row in the same table we're still
   populating), so it can't be resolved mid-stream.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from book_app.modules.books.import_adapter import (
    CanonicalBook,
    CanonicalSimilarityRef,
)
from book_app.modules.books.models import (
    Author,
    Book,
    BookAuthor,
    BookCatalogShelfTag,
    BookGenre,
    BookSourceSimilarity,
    CatalogShelfTag,
    Genre,
)
from book_app.shared.enums import CatalogStatus
from book_app.shared.text import normalize_for_uniqueness

_BOOK_UPDATE_COLUMNS = [
    c.name
    for c in Book.__table__.columns
    if c.name not in ("id", "work_id", "created_at", "updated_at")
]


def _book_values(book: CanonicalBook) -> dict[str, Any]:
    series_data = {"source_series_ids": book.series_source_ids} if book.series_source_ids else None
    return {
        "work_id": book.work_id,
        "source_book_id": book.source_book_id,
        "isbn": book.isbn,
        "isbn13": book.isbn13,
        "source_url": book.source_url,
        "source_image_url": book.source_image_url,
        "title": book.title,
        "title_without_series": book.title_without_series,
        "description": book.description,
        "description_source": book.description_source,
        "primary_author_name": book.primary_author_name,
        "top_genre": book.top_genre,
        "series_data": series_data,
        "average_rating": book.average_rating,
        "ratings_count": book.ratings_count,
        "text_reviews_count": book.text_reviews_count,
        "num_pages": book.num_pages,
        "publication_year": book.publication_year,
        "publisher": book.publisher,
        "language_code": book.language_code,
        "format": book.format,
        "is_ebook": book.is_ebook,
        "cover_object_key": book.cover_object_key,
        "cover_source": book.cover_source,
        "n_editions": book.n_editions,
        "edition_isbns": book.edition_isbns or None,
        "bx_ratings": book.bx_ratings,
        "bx_explicit": book.bx_explicit,
        "catalog_status": CatalogStatus.ACTIVE,
        "metadata_quality": book.metadata_quality,
        "source_metadata": {},
    }


def upsert_books_batch(session: Session, books: Sequence[CanonicalBook]) -> dict[str, int]:
    """Upsert by work_id (spec §7.4). Returns work_id -> internal id for this batch."""
    if not books:
        return {}

    insert_stmt = pg_insert(Book).values([_book_values(b) for b in books])
    update_columns: dict[str, Any] = {
        name: getattr(insert_stmt.excluded, name) for name in _BOOK_UPDATE_COLUMNS
    }
    update_columns["updated_at"] = func.now()
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=[Book.work_id], set_=update_columns
    ).returning(Book.id, Book.work_id)

    result = session.execute(upsert_stmt)
    return {row.work_id: row.id for row in result}


def sync_authors_batch(
    session: Session, books: Sequence[CanonicalBook], book_ids: dict[str, int]
) -> None:
    distinct_authors = {a.source_author_id: a for b in books for a in b.authors}
    author_ids: dict[str, int] = {}
    if distinct_authors:
        values = [
            {
                "source_author_id": a.source_author_id,
                "name": a.name,
                "normalized_name": normalize_for_uniqueness(a.name),
            }
            for a in distinct_authors.values()
        ]
        insert_stmt = pg_insert(Author).values(values)
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[Author.source_author_id],
            set_={
                "name": insert_stmt.excluded.name,
                "normalized_name": insert_stmt.excluded.normalized_name,
            },
        ).returning(Author.id, Author.source_author_id)
        author_ids = {row.source_author_id: row.id for row in session.execute(upsert_stmt)}

    target_book_ids = [book_ids[b.work_id] for b in books]
    session.execute(delete(BookAuthor).where(BookAuthor.book_id.in_(target_book_ids)))

    # A source book can credit the same author twice (e.g. under two roles);
    # book_authors' PK is (book_id, author_id), so keep only the first
    # (lowest-position, i.e. most prominent) listing — verified against the
    # full dataset: 229/92,526 books have this (see docs/implementation/plan.md).
    rows_by_key: dict[tuple[int, int], dict[str, Any]] = {}
    for b in books:
        for a in b.authors:
            key = (book_ids[b.work_id], author_ids[a.source_author_id])
            rows_by_key.setdefault(
                key,
                {"book_id": key[0], "author_id": key[1], "role": a.role, "position": a.position},
            )
    if rows_by_key:
        session.execute(insert(BookAuthor), list(rows_by_key.values()))


def sync_genres_batch(
    session: Session, books: Sequence[CanonicalBook], book_ids: dict[str, int]
) -> None:
    distinct_genres = {normalize_for_uniqueness(g.name): g.name for b in books for g in b.genres}
    genre_ids: dict[str, int] = {}
    if distinct_genres:
        values = [
            {"name": name, "normalized_name": normalized}
            for normalized, name in distinct_genres.items()
        ]
        insert_stmt = pg_insert(Genre).values(values)
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[Genre.normalized_name], set_={"name": insert_stmt.excluded.name}
        ).returning(Genre.id, Genre.normalized_name)
        genre_ids = {row.normalized_name: row.id for row in session.execute(upsert_stmt)}

    target_book_ids = [book_ids[b.work_id] for b in books]
    session.execute(delete(BookGenre).where(BookGenre.book_id.in_(target_book_ids)))

    # Same dedup as sync_authors_batch — never observed for genres in the
    # full dataset, but cheap insurance against the same bug class.
    rows_by_key: dict[tuple[int, int], dict[str, Any]] = {}
    for b in books:
        for g in b.genres:
            key = (book_ids[b.work_id], genre_ids[normalize_for_uniqueness(g.name)])
            rows_by_key.setdefault(
                key,
                {
                    "book_id": key[0],
                    "genre_id": key[1],
                    "source_count": g.source_count,
                    "position": g.position,
                },
            )
    if rows_by_key:
        session.execute(insert(BookGenre), list(rows_by_key.values()))


def sync_shelf_tags_batch(
    session: Session, books: Sequence[CanonicalBook], book_ids: dict[str, int]
) -> None:
    distinct_tags = {normalize_for_uniqueness(t.name): t.name for b in books for t in b.shelf_tags}
    tag_ids: dict[str, int] = {}
    if distinct_tags:
        values = [
            {"name": name, "normalized_name": normalized}
            for normalized, name in distinct_tags.items()
        ]
        insert_stmt = pg_insert(CatalogShelfTag).values(values)
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[CatalogShelfTag.normalized_name],
            set_={"name": insert_stmt.excluded.name},
        ).returning(CatalogShelfTag.id, CatalogShelfTag.normalized_name)
        tag_ids = {row.normalized_name: row.id for row in session.execute(upsert_stmt)}

    target_book_ids = [book_ids[b.work_id] for b in books]
    session.execute(
        delete(BookCatalogShelfTag).where(BookCatalogShelfTag.book_id.in_(target_book_ids))
    )

    # Same dedup as sync_authors_batch — 36/92,526 books repeat a shelf tag.
    rows_by_key: dict[tuple[int, int], dict[str, Any]] = {}
    for b in books:
        for t in b.shelf_tags:
            key = (book_ids[b.work_id], tag_ids[normalize_for_uniqueness(t.name)])
            rows_by_key.setdefault(
                key,
                {
                    "book_id": key[0],
                    "tag_id": key[1],
                    "source_count": t.source_count,
                    "position": t.position,
                },
            )
    if rows_by_key:
        session.execute(insert(BookCatalogShelfTag), list(rows_by_key.values()))


def resolve_similarities(
    similarities: Sequence[CanonicalSimilarityRef],
    book_id: int,
    work_id_to_id: dict[str, int],
    source_book_id_to_id: dict[str, int],
) -> list[dict[str, Any]]:
    """Resolve raw source references against both id spaces; drop dangling/self edges.

    See ``import_adapter``'s module docstring for why both spaces are tried.
    Keeps the first (lowest-rank / most-similar) occurrence on duplicates.
    """
    resolved: dict[int, int] = {}
    for sim in similarities:
        target_id = work_id_to_id.get(sim.source_ref)
        if target_id is None:
            target_id = source_book_id_to_id.get(sim.source_ref)
        if target_id is None or target_id == book_id:
            continue
        resolved.setdefault(target_id, sim.rank)

    return [
        {"book_id": book_id, "similar_book_id": target_id, "rank": rank, "source": "goodreads"}
        for target_id, rank in resolved.items()
    ]


def replace_book_similarities_batch(
    session: Session, book_ids: Sequence[int], rows: Sequence[dict[str, Any]]
) -> None:
    if not book_ids:
        return
    session.execute(delete(BookSourceSimilarity).where(BookSourceSimilarity.book_id.in_(book_ids)))
    if rows:
        session.execute(insert(BookSourceSimilarity), rows)
