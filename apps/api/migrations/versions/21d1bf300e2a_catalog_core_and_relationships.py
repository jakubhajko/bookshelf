"""catalog core and relationships

Revision ID: 21d1bf300e2a
Revises: c8564ab48a09
Create Date: 2026-08-04 21:57:12.720252

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "21d1bf300e2a"
down_revision: str | Sequence[str] | None = "c8564ab48a09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False: the "catalog_status" type itself is created by
# migration c8564ab48a09 (extensions and enums) — this table only uses it.
CATALOG_STATUS = postgresql.ENUM(
    "ACTIVE", "HIDDEN", "INVALID", name="catalog_status", create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "authors",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_author_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_author_id", name="uq_authors_source_author_id"),
    )
    op.create_table(
        "books",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("work_id", sa.Text(), nullable=False),
        sa.Column("source_book_id", sa.Text(), nullable=True),
        sa.Column("isbn", sa.Text(), nullable=True),
        sa.Column("isbn13", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_image_url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("title_without_series", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("description_source", sa.Text(), nullable=True),
        sa.Column("primary_author_name", sa.Text(), nullable=True),
        sa.Column("top_genre", sa.Text(), nullable=True),
        sa.Column("series_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("average_rating", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("ratings_count", sa.Integer(), nullable=True),
        sa.Column("text_reviews_count", sa.Integer(), nullable=True),
        sa.Column("num_pages", sa.Integer(), nullable=True),
        sa.Column("publication_year", sa.SmallInteger(), nullable=True),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column("language_code", sa.Text(), nullable=True),
        sa.Column("format", sa.Text(), nullable=True),
        sa.Column("is_ebook", sa.Boolean(), nullable=True),
        sa.Column("cover_object_key", sa.Text(), nullable=True),
        sa.Column("cover_source", sa.Text(), nullable=True),
        sa.Column("n_editions", sa.Integer(), nullable=True),
        sa.Column("edition_isbns", sa.ARRAY(sa.Text()), nullable=True),
        sa.Column("bx_ratings", sa.Integer(), nullable=True),
        sa.Column("bx_explicit", sa.Integer(), nullable=True),
        sa.Column("catalog_status", CATALOG_STATUS, nullable=False),
        sa.Column("metadata_quality", sa.Float(), nullable=True),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("work_id"),
    )
    op.create_index("ix_books_catalog_status", "books", ["catalog_status"], unique=False)
    op.create_index(
        "ix_books_popularity", "books", ["ratings_count", "average_rating"], unique=False
    )
    op.create_index("ix_books_publication_year", "books", ["publication_year"], unique=False)
    op.create_index("ix_books_top_genre", "books", ["top_genre"], unique=False)
    op.create_table(
        "catalog_shelf_tags",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name"),
    )
    op.create_table(
        "genres",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name"),
    )
    op.create_table(
        "book_authors",
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["authors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("book_id", "author_id"),
    )
    op.create_table(
        "book_catalog_shelf_tags",
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column("tag_id", sa.BigInteger(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["catalog_shelf_tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("book_id", "tag_id"),
    )
    op.create_table(
        "book_genres",
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column("genre_id", sa.BigInteger(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["genre_id"], ["genres.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("book_id", "genre_id"),
    )
    op.create_table(
        "book_source_similarities",
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column("similar_book_id", sa.BigInteger(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["similar_book_id"], ["books.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("book_id", "similar_book_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("book_source_similarities")
    op.drop_table("book_genres")
    op.drop_table("book_catalog_shelf_tags")
    op.drop_table("book_authors")
    op.drop_table("genres")
    op.drop_table("catalog_shelf_tags")
    op.drop_index("ix_books_top_genre", table_name="books")
    op.drop_index("ix_books_publication_year", table_name="books")
    op.drop_index("ix_books_popularity", table_name="books")
    op.drop_index("ix_books_catalog_status", table_name="books")
    op.drop_table("books")
    op.drop_table("authors")
