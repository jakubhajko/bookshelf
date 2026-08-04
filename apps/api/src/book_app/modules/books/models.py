"""Catalog persistence models (spec §8.3-§8.4): books and their taxonomy.

SQLAlchemy models only — no HTTP concerns, no queries (spec §4.2). ``Book``
is the one row per canonical work (spec §5.1); nothing here models a
separate edition entity.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from book_app.core.database import Base
from book_app.shared.enums import CatalogStatus


class Book(Base):
    """One row per canonical work (spec §5.1) — never a work/edition split."""

    __tablename__ = "books"
    __table_args__ = (
        Index("ix_books_catalog_status", "catalog_status"),
        Index("ix_books_top_genre", "top_genre"),
        Index("ix_books_publication_year", "publication_year"),
        Index("ix_books_popularity", "ratings_count", "average_rating"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    work_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    source_book_id: Mapped[str | None] = mapped_column(Text)
    isbn: Mapped[str | None] = mapped_column(Text)
    isbn13: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_image_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_without_series: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    description_source: Mapped[str | None] = mapped_column(Text)
    primary_author_name: Mapped[str | None] = mapped_column(Text)
    top_genre: Mapped[str | None] = mapped_column(Text)
    # Source data only ever gives series *IDs*, never names (see
    # scripts/data_import/adapter.py) — stored as {"source_series_ids": [...]}.
    series_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    average_rating: Mapped[float | None] = mapped_column(Numeric(4, 2))
    ratings_count: Mapped[int | None] = mapped_column(Integer)
    text_reviews_count: Mapped[int | None] = mapped_column(Integer)
    num_pages: Mapped[int | None] = mapped_column(Integer)
    publication_year: Mapped[int | None] = mapped_column(SmallInteger)
    publisher: Mapped[str | None] = mapped_column(Text)
    language_code: Mapped[str | None] = mapped_column(Text)
    format: Mapped[str | None] = mapped_column(Text)
    is_ebook: Mapped[bool | None] = mapped_column(Boolean)
    cover_object_key: Mapped[str | None] = mapped_column(Text)
    cover_source: Mapped[str | None] = mapped_column(Text)
    n_editions: Mapped[int | None] = mapped_column(Integer)
    edition_isbns: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    bx_ratings: Mapped[int | None] = mapped_column(Integer)
    bx_explicit: Mapped[int | None] = mapped_column(Integer)
    catalog_status: Mapped[CatalogStatus] = mapped_column(
        # create_type=False: the "catalog_status" Postgres enum type is
        # created explicitly by migration c8564ab48a09 (extensions and
        # enums), not implicitly by whichever migration first creates a
        # table that references it.
        SQLEnum(CatalogStatus, name="catalog_status", native_enum=True, create_type=False),
        nullable=False,
        default=CatalogStatus.ACTIVE,
    )
    # Adapter-computed completeness signal, not a source column — see
    # scripts/data_import/adapter.py's compute_metadata_quality().
    metadata_quality: Mapped[float | None] = mapped_column(Float)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def has_cover(self) -> bool:
        """Derived, not stored (spec §8.3: "Derive has_cover and has_description")."""
        return self.cover_object_key is not None

    @property
    def has_description(self) -> bool:
        return bool(self.description and self.description.strip())


class Author(Base):
    __tablename__ = "authors"
    # Not explicitly marked UNIQUE in spec §8.4's terse notation, but required
    # for the import to be idempotent (spec §7.4) instead of duplicating an
    # author row on every re-import — see docs/adr/0005.
    __table_args__ = (UniqueConstraint("source_author_id", name="uq_authors_source_author_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_author_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BookAuthor(Base):
    __tablename__ = "book_authors"

    book_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    author_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("authors.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)


class BookGenre(Base):
    __tablename__ = "book_genres"

    book_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    genre_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True
    )
    source_count: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class CatalogShelfTag(Base):
    __tablename__ = "catalog_shelf_tags"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)


class BookCatalogShelfTag(Base):
    __tablename__ = "book_catalog_shelf_tags"

    book_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("catalog_shelf_tags.id", ondelete="CASCADE"), primary_key=True
    )
    source_count: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class BookSourceSimilarity(Base):
    __tablename__ = "book_source_similarities"

    book_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    similar_book_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
