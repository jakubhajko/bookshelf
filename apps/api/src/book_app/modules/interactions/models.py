"""Interaction persistence models (spec §8.5, §8.9). SQLAlchemy models only
— no HTTP concerns, no queries (spec §4.2).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from book_app.core.database import Base


class UserBookState(Base):
    """Neutral / Rated / Not-Interested (spec §5.2) — never both at once."""

    __tablename__ = "user_book_states"
    __table_args__ = (
        CheckConstraint(
            "rating_value IS NULL OR (rating_value BETWEEN 1 AND 10)",
            name="ck_user_book_states_rating_range",
        ),
        CheckConstraint(
            "NOT (rating_value IS NOT NULL AND not_interested)",
            name="ck_user_book_states_mutual_exclusion",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    book_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    rating_value: Mapped[int | None] = mapped_column(SmallInteger)
    not_interested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class InteractionEvent(Base):
    """Append-only (spec §8.9) — nothing in this module ever updates or
    deletes a row here, only inserts."""

    __tablename__ = "interaction_events"
    __table_args__ = (
        Index("ix_interaction_events_user_id", "user_id", "id"),
        Index("ix_interaction_events_user_time", "user_id", "occurred_at"),
        Index("ix_interaction_events_book_time", "book_id", "occurred_at"),
        Index("ix_interaction_events_event_time", "event_type", "occurred_at"),
        Index("ix_interaction_events_request_id", "recommendation_request_id"),
        Index("ix_interaction_events_search_id", "search_query_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SET NULL, not CASCADE: books are never actually deleted in this app
    # (catalog_status covers that), but if one ever is, the historical event
    # should outlive it.
    book_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("books.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    surface: Mapped[str | None] = mapped_column(Text)
    # No FK for shelf_id: spec §5.4 requires deleting a shelf to leave
    # historical events intact, which a CASCADE would violate and a SET
    # NULL would still lose (which shelf it *was* is exactly what a
    # historical event needs to keep). Same reasoning, plus the referenced
    # tables not existing yet, for recommendation_request_id/search_query_id
    # (both Phase 5+).
    shelf_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    recommendation_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    search_query_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    source_book_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("books.id", ondelete="SET NULL")
    )
    rank_position: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
