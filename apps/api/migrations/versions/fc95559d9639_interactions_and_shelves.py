"""interactions and shelves

Revision ID: fc95559d9639
Revises: 4a6ac23b959d
Create Date: 2026-08-05 01:14:57.928458

Autogenerate also proposed dropping and recreating the three hand-written
trigram/FTS indexes on `books` (migration 43bc30e307a2) — those aren't
represented in any SQLAlchemy model, so the diff against model metadata
reads them as "should be removed." That's a false diff, not an intended
change, and has been stripped from both upgrade() and downgrade() below
(same false-diff pattern noted in migration 4a6ac23b959d).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "fc95559d9639"
down_revision: str | Sequence[str] | None = "4a6ac23b959d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "interaction_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("surface", sa.Text(), nullable=True),
        sa.Column("shelf_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("recommendation_request_id", sa.Uuid(), nullable=True),
        sa.Column("search_query_id", sa.Uuid(), nullable=True),
        sa.Column("source_book_id", sa.BigInteger(), nullable=True),
        sa.Column("rank_position", sa.Integer(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_book_id"], ["books.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_interaction_events_book_time",
        "interaction_events",
        ["book_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_interaction_events_event_time",
        "interaction_events",
        ["event_type", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_interaction_events_request_id",
        "interaction_events",
        ["recommendation_request_id"],
        unique=False,
    )
    op.create_index(
        "ix_interaction_events_search_id",
        "interaction_events",
        ["search_query_id"],
        unique=False,
    )
    op.create_index(
        "ix_interaction_events_user_id", "interaction_events", ["user_id", "id"], unique=False
    )
    op.create_index(
        "ix_interaction_events_user_time",
        "interaction_events",
        ["user_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "shelves",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "normalized_name", name="uq_shelves_user_normalized_name"),
    )
    op.create_table(
        "user_book_states",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column("rating_value", sa.SmallInteger(), nullable=True),
        sa.Column("not_interested", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.CheckConstraint(
            "NOT (rating_value IS NOT NULL AND not_interested)",
            name="ck_user_book_states_mutual_exclusion",
        ),
        sa.CheckConstraint(
            "rating_value IS NULL OR (rating_value BETWEEN 1 AND 10)",
            name="ck_user_book_states_rating_range",
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "book_id"),
    )
    op.create_table(
        "shelf_books",
        sa.Column("shelf_id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_surface", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shelf_id"], ["shelves.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("shelf_id", "book_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("shelf_books")
    op.drop_table("user_book_states")
    op.drop_table("shelves")
    op.drop_index("ix_interaction_events_user_time", table_name="interaction_events")
    op.drop_index("ix_interaction_events_user_id", table_name="interaction_events")
    op.drop_index("ix_interaction_events_search_id", table_name="interaction_events")
    op.drop_index("ix_interaction_events_request_id", table_name="interaction_events")
    op.drop_index("ix_interaction_events_event_time", table_name="interaction_events")
    op.drop_index("ix_interaction_events_book_time", table_name="interaction_events")
    op.drop_table("interaction_events")
