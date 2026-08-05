"""Search persistence: the multi-tier ranking query (spec §9.6). No HTTP
concerns, no commits (spec §4.2) — read-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from book_app.modules.books.models import Book
from book_app.shared.enums import CatalogStatus

# The `%` operator and `similarity()` below rely on pg_trgm's own default
# GUC (`pg_trgm.similarity_threshold`, 0.3) — deliberately not overridden;
# spec doesn't ask for a tunable threshold, and Postgres's own well-known
# default is a reasonable one, verified directly against the real catalog
# (a "harry potter" query correctly ranks the title-prefix "Harry Potter
# and the ..." books ahead of looser matches like "J. K. Rowling: The
# Wizard Behind Harry Potter"). See ADR-0012.


@dataclass(frozen=True)
class SearchResultRow:
    book_id: int
    work_id: str
    title: str
    primary_author_name: str | None
    cover_object_key: str | None
    tier: int
    ratings_count: int | None


def _title_author_combo(query_lower: str) -> Any:
    """Tier 2: spec §9.6's "exact title/author combination" — read as the
    query exactly matching "title author" or "author title" concatenated,
    case-insensitively, covering both natural typing orders (e.g. "dune
    frank herbert" or "frank herbert dune"). Genuinely underspecified;
    documented here and in docs/implementation/plan.md's risk log.
    """
    title_then_author = func.lower(
        func.concat(Book.title, " ", func.coalesce(Book.primary_author_name, ""))
    )
    author_then_title = func.lower(
        func.concat(func.coalesce(Book.primary_author_name, ""), " ", Book.title)
    )
    return or_(title_then_author == query_lower, author_then_title == query_lower)


def _rank_tier(query_raw: str, query_lower: str) -> Any:
    """Spec §9.6's seven-tier ranking (the 7th, popularity, is applied as an
    ORDER BY tiebreak in :func:`search_books`, not here) collapsed into one
    SQL ``CASE`` — the first matching branch wins, so a book that's an
    exact title match is never *also* counted as merely a fuzzy one. ``%``
    and the ``@@`` text-search operator use the trigram/full-text GIN
    indexes from migration ``43bc30e307a2``; a bare ``similarity()`` call
    would not (verified directly — see ADR-0012).
    """
    return case(
        (func.lower(Book.title) == query_lower, 1),
        (_title_author_combo(query_lower), 2),
        (func.lower(Book.title).like(query_lower + "%"), 3),
        (Book.title.op("%")(query_raw), 4),
        (Book.primary_author_name.op("%")(query_raw), 5),
        (
            func.to_tsvector("english", func.coalesce(Book.description, "")).op("@@")(
                func.plainto_tsquery("english", query_raw)
            ),
            6,
        ),
        else_=None,
    )


# NULLS-last-as-lowest approximation for the popularity tiebreak — same
# reasoning/precedent as interactions/repository.py's `_AUTHOR_SORT_KEY`.
_POPULARITY = func.coalesce(Book.ratings_count, -1)


def search_books(
    session: Session, *, query: str, limit: int, cursor: dict[str, Any] | None
) -> list[SearchResultRow]:
    query_raw = query.strip()
    query_lower = query_raw.lower()
    tier = _rank_tier(query_raw, query_lower).label("tier")

    stmt = select(
        Book.id,
        Book.work_id,
        Book.title,
        Book.primary_author_name,
        Book.cover_object_key,
        Book.ratings_count,
        tier,
    ).where(Book.catalog_status == CatalogStatus.ACTIVE, tier.isnot(None))

    if cursor is not None:
        cursor_tier = cursor["tier"]
        cursor_popularity = cursor["popularity"]
        cursor_book_id = cursor["book_id"]
        stmt = stmt.where(
            or_(
                tier > cursor_tier,
                and_(tier == cursor_tier, cursor_popularity > _POPULARITY),
                and_(
                    tier == cursor_tier,
                    cursor_popularity == _POPULARITY,
                    Book.id > cursor_book_id,
                ),
            )
        )

    stmt = stmt.order_by(tier.asc(), _POPULARITY.desc(), Book.id.asc()).limit(limit)

    rows = session.execute(stmt).all()
    return [
        SearchResultRow(
            book_id=row.id,
            work_id=row.work_id,
            title=row.title,
            primary_author_name=row.primary_author_name,
            cover_object_key=row.cover_object_key,
            tier=row.tier,
            ratings_count=row.ratings_count,
        )
        for row in rows
    ]


def cursor_value_for_row(row: SearchResultRow) -> dict[str, Any]:
    """The value to store in the *next* page's cursor — must match what
    ``search_books`` compares the cursor fields against."""
    return {
        "tier": row.tier,
        "popularity": row.ratings_count if row.ratings_count is not None else -1,
        "book_id": row.book_id,
    }
