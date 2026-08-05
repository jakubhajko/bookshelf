"""recommendation persistence

Revision ID: b61e97f578c1
Revises: fc95559d9639
Create Date: 2026-08-05 11:32:00.090491

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
revision: str = "b61e97f578c1"
down_revision: str | Sequence[str] | None = "fc95559d9639"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False: created explicitly below, not implicitly by
# create_table (same pattern as account_status in migration 4a6ac23b959d).
MODEL_VERSION_STATUS = postgresql.ENUM(
    "READY", "ACTIVE", "RETIRED", name="model_version_status", create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""
    MODEL_VERSION_STATUS.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "model_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("catalog_version", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("status", MODEL_VERSION_STATUS, nullable=False),
        sa.Column(
            "manifest",
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
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "recommendation_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("surface", sa.Text(), nullable=False),
        sa.Column("shelf_id", sa.Uuid(), nullable=True),
        sa.Column("source_book_id", sa.BigInteger(), nullable=True),
        sa.Column("search_query_id", sa.Uuid(), nullable=True),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("catalog_version", sa.Text(), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "context_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["shelf_id"], ["shelves.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_book_id"], ["books.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recommendation_requests_expires_at",
        "recommendation_requests",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "recommendation_impressions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column("rank_position", sa.Integer(), nullable=False),
        sa.Column("page_cursor", sa.Text(), nullable=True),
        sa.Column(
            "shown_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["recommendation_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_id", "book_id", name="uq_recommendation_impressions_request_book"
        ),
    )
    op.create_index(
        "ix_recommendation_impressions_request_id",
        "recommendation_impressions",
        ["request_id"],
        unique=False,
    )
    op.create_table(
        "recommendation_results",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column(
            "candidate_sources",
            sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column(
            "reason_context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "diagnostics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["recommendation_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("request_id", "position"),
        sa.UniqueConstraint("request_id", "book_id", name="uq_recommendation_results_request_book"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("recommendation_results")
    op.drop_index(
        "ix_recommendation_impressions_request_id", table_name="recommendation_impressions"
    )
    op.drop_table("recommendation_impressions")
    op.drop_index("ix_recommendation_requests_expires_at", table_name="recommendation_requests")
    op.drop_table("recommendation_requests")
    op.drop_table("model_versions")

    MODEL_VERSION_STATUS.drop(op.get_bind(), checkfirst=True)
