"""User persistence model (spec §8.1). SQLAlchemy model only — no HTTP
concerns, no queries (spec §4.2)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, Uuid, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from book_app.core.database import Base
from book_app.shared.enums import AccountStatus


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Original submitted form, preserved as-is (spec §6.2); uniqueness is
    # enforced on normalized_username, not this column.
    username: Mapped[str] = mapped_column(String(30), nullable=False)
    normalized_username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    account_status: Mapped[AccountStatus] = mapped_column(
        # create_type=False: the "account_status" enum type is created by
        # its own migration alongside this table (see migrations/versions).
        SQLEnum(AccountStatus, name="account_status", native_enum=True, create_type=False),
        nullable=False,
        default=AccountStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
