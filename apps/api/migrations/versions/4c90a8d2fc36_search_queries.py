"""search queries

Revision ID: 4c90a8d2fc36
Revises: b61e97f578c1
Create Date: 2026-08-13 11:35:21.073858

Recommender Phase R1 (rec-spec §4.4, ADR-0015): persist *submitted*
searches so a later book open can be attributed to the search that
produced it.

The only schema change R1 needs. Everything else this phase populates —
`interaction_events`' six attribution columns and
`shelf_books.source_surface` — has existed, correctly typed and indexed,
since Phase 4 (`fc95559d9639`) with no writer; R1 adds the write paths, not
the columns.

Hand-edited after autogenerate, for the reason migration `4a6ac23b959d`'s
docstring already records: autogenerate proposes dropping
`ix_books_title_trgm`, `ix_books_primary_author_name_trgm` and
`ix_books_description_fts` on every run, because those are hand-written
expression/opclass indexes from `43bc30e307a2` that no model declares and
therefore no autogenerate comparison can see. Applying that suggestion
would silently delete the indexes the entire search ranking depends on
(ADR-0012). The three `op.drop_index` calls were removed from `upgrade()`
and their matching `op.create_index` calls from `downgrade()`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c90a8d2fc36"
down_revision: str | Sequence[str] | None = "b61e97f578c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "search_queries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        # No FK on session_id: a browsing session is a frontend-generated
        # correlator (rec-spec §4.1), not a row in any table — same
        # reasoning as interaction_events.session_id.
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("surface", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_queries_session_id", "search_queries", ["session_id"], unique=False)
    op.create_index(
        "ix_search_queries_user_time", "search_queries", ["user_id", "occurred_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_search_queries_user_time", table_name="search_queries")
    op.drop_index("ix_search_queries_session_id", table_name="search_queries")
    op.drop_table("search_queries")
