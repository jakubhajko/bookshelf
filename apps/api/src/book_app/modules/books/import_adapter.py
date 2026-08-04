"""Dataset adapter: books.parquet rows -> canonical typed records.

This is the *only* code allowed to know raw Parquet column names and their
quirks (spec §7.4, ADR-0005). Everything downstream (repository, CLI) works
with :class:`CanonicalBook` only.

Quirks handled here, discovered by inspecting the actual data during
Phase 2 planning (see docs/implementation/plan.md):

- ``authors``/``author_ids``/``author_roles`` and ``genres``/``genre_counts``
  and ``shelves``/``shelf_counts`` are parallel arrays (verified: zero
  length mismatches across all 92,526 rows) ordered by descending count;
  position below is that array index.
- ``primary_author`` is already the source's own "best" author pick (blank
  when no author has a plain/blank role) — passed through as-is rather than
  re-derived.
- ``series`` gives only opaque source series *IDs*, never names.
- ``similar_books`` mixes two conventions: most values match this dataset's
  ``book_id`` (edition-level) space, a smaller number match ``work_id``
  directly, and roughly two-thirds resolve to neither (edges pointing
  outside our 92,526-row catalog). The adapter emits the raw references;
  resolving them against both ID spaces and dropping dangling edges is the
  repository's job (it needs the full id map, which the adapter doesn't
  have).
- Exactly one row has ``work_id == ""`` in the current dataset — rejected
  here, not upserted.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

REQUIRED_BOOKS_COLUMNS = frozenset(
    {
        "work_id",
        "book_id",
        "isbn",
        "isbn13",
        "url",
        "image_url",
        "title",
        "title_without_series",
        "description",
        "description_source",
        "authors",
        "author_ids",
        "author_roles",
        "primary_author",
        "genres",
        "genre_counts",
        "top_genre",
        "similar_books",
        "series",
        "average_rating",
        "ratings_count",
        "text_reviews_count",
        "num_pages",
        "publication_year",
        "publisher",
        "language_code",
        "format",
        "is_ebook",
        "cover_file",
        "cover_source",
        "n_editions",
        "edition_isbns",
        "bx_ratings",
        "bx_explicit",
    }
)


class CanonicalAuthorRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_author_id: str
    name: str
    role: str | None
    position: int


class CanonicalGenreRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    source_count: int | None
    position: int


class CanonicalShelfTagRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    source_count: int | None
    position: int


class CanonicalSimilarityRef(BaseModel):
    """Not yet resolved to an internal book id — see module docstring."""

    model_config = ConfigDict(frozen=True)

    source_ref: str
    rank: int


class CanonicalBook(BaseModel):
    model_config = ConfigDict(frozen=True)

    work_id: str
    source_book_id: str | None
    isbn: str | None
    isbn13: str | None
    source_url: str | None
    source_image_url: str | None
    title: str
    title_without_series: str | None
    description: str | None
    description_source: str | None
    primary_author_name: str | None
    top_genre: str | None
    series_source_ids: list[str]
    average_rating: float | None
    ratings_count: int | None
    text_reviews_count: int | None
    num_pages: int | None
    publication_year: int | None
    publisher: str | None
    language_code: str | None
    format: str | None
    is_ebook: bool | None
    cover_object_key: str | None
    cover_source: str | None
    n_editions: int | None
    edition_isbns: list[str]
    bx_ratings: int | None
    bx_explicit: int | None
    metadata_quality: float
    authors: list[CanonicalAuthorRef]
    genres: list[CanonicalGenreRef]
    shelf_tags: list[CanonicalShelfTagRef]
    similarities: list[CanonicalSimilarityRef]


class RejectedRow(BaseModel):
    """A source row that failed validation and was not converted (spec §7.4: "validated")."""

    model_config = ConfigDict(frozen=True)

    row_index: int
    work_id: str
    reasons: list[str]


def _is_missing(value: Any) -> bool:
    """True for None, float NaN, and pandas' nullable-dtype NA markers.

    ``ratings_count``/``text_reviews_count``/``num_pages``/``publication_year``
    are pandas nullable ``Int32`` and ``is_ebook`` is nullable ``boolean`` —
    both use ``pd.NA`` for missing values, not float ``NaN``. A plain
    ``isinstance(value, float) and math.isnan(value)`` check misses those
    (and ``int(pd.NA)`` raises), so this uses ``pd.isna`` uniformly instead.

    Only used by the scalar cleaners below. ``pd.isna`` returns an *array*
    of booleans for array-like input, so this must never be called with the
    array/list-typed columns (authors, genres, similar_books, ...) —
    :func:`_clean_list` has its own, array-safe check.
    """
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _clean_str(value: Any) -> str | None:
    if value is None or _is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def _clean_int(value: Any) -> int | None:
    if value is None or _is_missing(value):
        return None
    return int(value)


def _clean_float(value: Any) -> float | None:
    if value is None or _is_missing(value):
        return None
    return float(value)


def _clean_bool(value: Any) -> bool | None:
    if value is None or _is_missing(value):
        return None
    return bool(value)


def _clean_list(value: Any) -> list[str]:
    """Array-typed columns (authors, genres, similar_books, ...) use an empty
    array for "no items," never ``pd.NA`` — so only ``None`` needs handling
    here, not :func:`_is_missing` (which would break on a multi-element
    array's ambiguous truth value).
    """
    if value is None or isinstance(value, float):  # float only reachable via NaN here
        return []
    return [str(item) for item in value if item is not None and str(item).strip()]


def compute_metadata_quality(
    *,
    has_description: bool,
    has_cover: bool,
    has_primary_author: bool,
    has_genre: bool,
    has_publication_year: bool,
) -> float:
    """Adapter-computed completeness signal, not a source column.

    Not specified by the dataset contract (spec §7.1) — a simple, documented,
    equal-weight fraction of five completeness signals. Reversible: nothing
    downstream depends on the exact formula, only that higher is "more
    complete."
    """
    signals = [has_description, has_cover, has_primary_author, has_genre, has_publication_year]
    return round(sum(signals) / len(signals), 4)


def _row_to_canonical(row: pd.Series, row_index: int) -> tuple[CanonicalBook | None, list[str]]:
    reasons: list[str] = []

    work_id = _clean_str(row["work_id"])
    if not work_id:
        reasons.append("empty or missing work_id")

    title = _clean_str(row["title"])
    if not title:
        reasons.append("empty or missing title")

    if reasons:
        return None, reasons

    assert work_id is not None
    assert title is not None

    authors = [
        CanonicalAuthorRef(
            source_author_id=str(author_id),
            name=str(name),
            role=_clean_str(role),
            position=position,
        )
        for position, (name, author_id, role) in enumerate(
            zip(row["authors"], row["author_ids"], row["author_roles"], strict=True)
        )
    ]
    genres = [
        CanonicalGenreRef(name=str(name), source_count=_clean_int(count), position=position)
        for position, (name, count) in enumerate(
            zip(row["genres"], row["genre_counts"], strict=True)
        )
    ]
    shelf_tags = [
        CanonicalShelfTagRef(name=str(name), source_count=_clean_int(count), position=position)
        for position, (name, count) in enumerate(
            zip(row["shelves"], row["shelf_counts"], strict=True)
        )
    ]
    similarities = [
        CanonicalSimilarityRef(source_ref=str(ref), rank=position)
        for position, ref in enumerate(row["similar_books"])
    ]

    description = _clean_str(row["description"])
    cover_object_key = _clean_str(row["cover_file"])
    primary_author_name = _clean_str(row["primary_author"])
    top_genre = _clean_str(row["top_genre"])
    publication_year = _clean_int(row["publication_year"])

    metadata_quality = compute_metadata_quality(
        has_description=description is not None,
        has_cover=cover_object_key is not None,
        has_primary_author=primary_author_name is not None,
        has_genre=top_genre is not None,
        has_publication_year=publication_year is not None,
    )

    book = CanonicalBook(
        work_id=work_id,
        source_book_id=_clean_str(row["book_id"]),
        isbn=_clean_str(row["isbn"]),
        isbn13=_clean_str(row["isbn13"]),
        source_url=_clean_str(row["url"]),
        source_image_url=_clean_str(row["image_url"]),
        title=title,
        title_without_series=_clean_str(row["title_without_series"]),
        description=description,
        description_source=_clean_str(row["description_source"]),
        primary_author_name=primary_author_name,
        top_genre=top_genre,
        series_source_ids=_clean_list(row["series"]),
        average_rating=_clean_float(row["average_rating"]),
        ratings_count=_clean_int(row["ratings_count"]),
        text_reviews_count=_clean_int(row["text_reviews_count"]),
        num_pages=_clean_int(row["num_pages"]),
        publication_year=publication_year,
        publisher=_clean_str(row["publisher"]),
        language_code=_clean_str(row["language_code"]),
        format=_clean_str(row["format"]),
        is_ebook=_clean_bool(row["is_ebook"]),
        cover_object_key=cover_object_key,
        cover_source=_clean_str(row["cover_source"]),
        n_editions=_clean_int(row["n_editions"]),
        edition_isbns=_clean_list(row["edition_isbns"]),
        bx_ratings=_clean_int(row["bx_ratings"]),
        bx_explicit=_clean_int(row["bx_explicit"]),
        metadata_quality=metadata_quality,
        authors=authors,
        genres=genres,
        shelf_tags=shelf_tags,
        similarities=similarities,
    )
    return book, []


def read_canonical_books(parquet_path: Path) -> Iterator[CanonicalBook | RejectedRow]:
    """Stream ``books.parquet`` as canonical records, independent of row order (spec §7.4).

    Yields either a validated :class:`CanonicalBook` or a :class:`RejectedRow`
    describing why that row was skipped — never raises on a single bad row.
    """
    df = pd.read_parquet(parquet_path)
    missing_columns = REQUIRED_BOOKS_COLUMNS - set(df.columns)
    if missing_columns:
        raise ValueError(f"books.parquet is missing expected columns: {sorted(missing_columns)}")

    # Positional row number for error reporting, not the DataFrame's index
    # label — avoids depending on the index being a default RangeIndex.
    for position, (_, row) in enumerate(df.iterrows()):
        book, reasons = _row_to_canonical(row, position)
        if book is not None:
            yield book
        else:
            yield RejectedRow(
                row_index=position,
                work_id=_clean_str(row["work_id"]) or "",
                reasons=reasons,
            )
