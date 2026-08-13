"""Reading the catalog rows the content builder embeds (rec-spec §11.2).

Separated from the builder CLI and from the encoder so the *text* half of
the content pipeline can be tested without a GPU, a model download, or the
training dependency group — which is most of what can actually go wrong.
Pure SQLAlchemy and the pure text/tag modules; no torch anywhere.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from book_recommender.content.tags import clean_tags, summarize_rejections
from book_recommender.content.text_builder import BookText, build_book_text
from sqlalchemy import select
from sqlalchemy.orm import Session

from book_app.modules.books.models import (
    Book,
    BookCatalogShelfTag,
    BookGenre,
    CatalogShelfTag,
    Genre,
)
from book_app.shared.enums import CatalogStatus

#: Genres kept per book, most-supported first. The catalog's ``top_genre``
#: is a single string; the ``book_genres`` join carries the full ranked set.
MAX_GENRES_PER_BOOK = 3


@dataclass
class ContentSourceReport:
    books: int = 0
    with_description: int = 0
    with_tags: int = 0
    with_genres: int = 0
    raw_tag_links: int = 0
    kept_tag_links: int = 0
    tag_rejections: dict[str, int] = field(default_factory=dict)

    def as_stats(self) -> dict[str, int | str]:
        rejections = ", ".join(
            f"{reason}:{count}" for reason, count in sorted(self.tag_rejections.items())
        )
        return {
            "books": self.books,
            "with_description": self.with_description,
            "with_genres": self.with_genres,
            "with_tags": self.with_tags,
            "raw_tag_links": self.raw_tag_links,
            "kept_tag_links": self.kept_tag_links,
            "tags_rejected_by": rejections or "none",
        }


@dataclass(frozen=True)
class ContentRow:
    """One book's identity, encoder input and the metadata that explains it."""

    book_id: int
    work_id: str
    title: str
    author: str
    genres: tuple[str, ...]
    tags: tuple[str, ...]
    text: BookText


def read_content_rows(
    session: Session, *, limit: int | None = None
) -> tuple[list[ContentRow], ContentSourceReport]:
    """Build the encoder input for every active book, in catalog item order.

    Ordered by ``book_id`` to match
    ``books_repository.get_active_catalog_identities``, so embedding row *i*
    is ``model_item_index`` *i* in every other artifact family (ADR-0014).
    """
    report = ContentSourceReport()
    genres_by_book = _genres_by_book(session)
    tags_by_book, raw_tags = _tags_by_book(session)
    report.raw_tag_links = sum(len(values) for values in raw_tags.values())
    report.tag_rejections = summarize_rejections(
        [tag for values in raw_tags.values() for tag in values]
    )

    rows: list[ContentRow] = []
    for book in _active_books(session, limit=limit):
        genres = genres_by_book.get(book.id, ())[:MAX_GENRES_PER_BOOK]
        tags = tags_by_book.get(book.id, ())
        text = build_book_text(
            title=book.title,
            author=book.primary_author_name,
            genres=genres,
            tags=tags,
            description=book.description,
        )
        rows.append(
            ContentRow(
                book_id=book.id,
                work_id=book.work_id,
                title=book.title,
                author=book.primary_author_name or "",
                genres=tuple(genres),
                tags=tags,
                text=text,
            )
        )
        report.books += 1
        report.with_description += int(text.used_description)
        report.with_genres += int(bool(genres))
        report.with_tags += int(bool(tags))
        report.kept_tag_links += len(tags)

    return rows, report


def _active_books(session: Session, *, limit: int | None) -> Iterator[Book]:
    stmt = (
        select(Book)
        .where(Book.catalog_status == CatalogStatus.ACTIVE)
        .order_by(Book.id)
        .execution_options(yield_per=2000)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    yield from session.scalars(stmt)


def _genres_by_book(session: Session) -> dict[int, tuple[str, ...]]:
    stmt = (
        select(BookGenre.book_id, Genre.name)
        .join(Genre, Genre.id == BookGenre.genre_id)
        .order_by(BookGenre.book_id, BookGenre.position)
    )
    grouped: dict[int, list[str]] = {}
    for book_id, name in session.execute(stmt):
        grouped.setdefault(book_id, []).append(name)
    return {book_id: tuple(names) for book_id, names in grouped.items()}


def _tags_by_book(session: Session) -> tuple[dict[int, tuple[str, ...]], dict[int, list[str]]]:
    """Cleaned tags per book, plus the raw input for the rejection report.

    Ordered by ``source_count`` descending — how many readers used the shelf
    — because ``clean_tags`` caps by input order and rec-spec §11.2 asks for
    "meaningful high-support thematic tags".
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
    return {book_id: clean_tags(names) for book_id, names in raw.items()}, raw


def encoder_texts(rows: Sequence[ContentRow]) -> list[str]:
    return [row.text.text for row in rows]
