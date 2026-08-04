"""extensions and enums

Revision ID: c8564ab48a09
Revises:
Create Date: 2026-08-04 21:55:51.152980

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.dialects.postgresql import ENUM

# revision identifiers, used by Alembic.
revision: str = "c8564ab48a09"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

catalog_status_enum = ENUM("ACTIVE", "HIDDEN", "INVALID", name="catalog_status")


def upgrade() -> None:
    # Trigram fuzzy title search (spec §8) — created first since later
    # migrations in this phase depend on it being available.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    catalog_status_enum.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    catalog_status_enum.drop(op.get_bind(), checkfirst=True)
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
