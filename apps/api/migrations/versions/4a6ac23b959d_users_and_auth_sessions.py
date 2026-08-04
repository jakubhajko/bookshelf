"""users and auth sessions

Revision ID: 4a6ac23b959d
Revises: 43bc30e307a2
Create Date: 2026-08-05 00:21:55.327676

Autogenerate also proposed dropping and recreating the three hand-written
trigram/FTS indexes on `books` (migration 43bc30e307a2) — those aren't
represented in any SQLAlchemy model, so the diff against model metadata
reads them as "should be removed." That's a false diff, not an intended
change, and has been stripped from both upgrade() and downgrade() below.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4a6ac23b959d"
down_revision: str | Sequence[str] | None = "43bc30e307a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False: created explicitly below, not implicitly by create_table
# (see docs/adr — same pattern as catalog_status in migration 21d1bf300e2a).
ACCOUNT_STATUS = postgresql.ENUM(
    "ACTIVE", "DISABLED", "PENDING_DELETION", name="account_status", create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""
    ACCOUNT_STATUS.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=30), nullable=False),
        sa.Column("normalized_username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("account_status", ACCOUNT_STATUS, nullable=False),
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
        sa.UniqueConstraint("normalized_username"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_token_hash", sa.Text(), nullable=False),
        sa.Column("csrf_token_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "client_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("refresh_token_hash"),
    )
    op.create_index("ix_auth_sessions_expiry", "auth_sessions", ["expires_at"], unique=False)
    op.create_index(
        "ix_auth_sessions_user_revoked_expiry",
        "auth_sessions",
        ["user_id", "revoked_at", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_auth_sessions_user_revoked_expiry", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_expiry", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")

    ACCOUNT_STATUS.drop(op.get_bind(), checkfirst=True)
