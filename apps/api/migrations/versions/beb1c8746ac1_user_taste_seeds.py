"""user taste seeds

Revision ID: beb1c8746ac1
Revises: 4c90a8d2fc36
Create Date: 2026-08-13 12:31:04.882417

Recommender Phase R2 (rec-spec §6, ADR-0019): explicit onboarding taste
seeds as their own domain state.

Deliberately *not* a column on `user_book_states`. That table encodes the
Neutral/Rated/Not-Interested trichotomy with a database-level
mutual-exclusion check constraint, and a seed is orthogonal to all three —
folding it in would mean loosening a constraint that protects a real domain
rule. Storing seeds as ratings or auto-created shelves (the two obvious
shortcuts) would corrupt what a rating and a shelf mean in this product.

No separate index: the composite primary key's leading `user_id` column
already serves "list this user's seeds", which is the only access pattern.

Hand-edited after autogenerate to strip the three phantom index drops
(`ix_books_title_trgm`, `ix_books_primary_author_name_trgm`,
`ix_books_description_fts`) — hand-written expression/opclass indexes from
`43bc30e307a2` that no model declares, so every autogenerate run proposes
deleting them. Applying that would silently destroy the indexes the search
ranking depends on (ADR-0012). Same edit as `4c90a8d2fc36` and
`4a6ac23b959d` before it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "beb1c8746ac1"
down_revision: str | Sequence[str] | None = "4c90a8d2fc36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user_taste_seeds",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "selected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "book_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("user_taste_seeds")
