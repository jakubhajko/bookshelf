"""Recommendation persistence models (spec §8.10). SQLAlchemy models only —
no HTTP concerns, no queries (spec §4.2).

Class names match table names directly, same convention as every other
module (``Shelf``/``ShelfBook``, ``User``, ...) — including
``RecommendationRequest``, which collides in name (not in meaning) with
``book_recommender.contracts.provider.RecommendationRequest``. Call sites
that need both import the recommender package's version under an alias
rather than rename the ORM model to something inconsistent with the rest of
the codebase.
"""

from __future__ import annotations

import uuid
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
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from book_app.core.database import Base
from book_app.shared.enums import ModelVersionStatus


class ModelVersion(Base):
    """Build-time registry of recommendation artifacts (spec §8.10) — not
    joined by every request (those denormalize model_name/model_version/
    catalog_version onto themselves), an audit/ops record of what's been
    built and which one is active."""

    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    catalog_version: Mapped[str] = mapped_column(Text, nullable=False)
    provider_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ModelVersionStatus] = mapped_column(
        SQLEnum(
            ModelVersionStatus, name="model_version_status", native_enum=True, create_type=False
        ),
        nullable=False,
    )
    manifest: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecommendationRequest(Base):
    """Spec §8.10. Short-lived (bounded by ``expires_at``, spec ADR-0007) —
    unlike ``interaction_events``, FKs here CASCADE rather than preserving
    history, since a request whose shelf/book no longer exists has nothing
    left worth keeping around."""

    __tablename__ = "recommendation_requests"
    __table_args__ = (Index("ix_recommendation_requests_expires_at", "expires_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    surface: Mapped[str] = mapped_column(Text, nullable=False)
    shelf_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("shelves.id", ondelete="CASCADE")
    )
    source_book_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("books.id", ondelete="SET NULL")
    )
    # No FK yet: search_queries doesn't exist until search does (not this
    # phase — matches interaction_events.search_query_id's exact precedent).
    search_query_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    provider_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    catalog_version: Mapped[str] = mapped_column(Text, nullable=False)
    fallback_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    context_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecommendationResult(Base):
    """Spec §8.10. ``PK (request_id, position)`` doubles as the index the
    cursor-paging read pattern needs (spec §9.9: read further positions from
    the same batch)."""

    __tablename__ = "recommendation_results"
    __table_args__ = (
        UniqueConstraint("request_id", "book_id", name="uq_recommendation_results_request_book"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("recommendation_requests.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float | None] = mapped_column(Float)
    candidate_sources: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    # TEXT, not a native enum, despite spec §10.9's list looking closed —
    # same reasoning as interaction_events.event_type (Phase 4): reason
    # codes are the kind of thing a recommendation strategy plausibly grows
    # over time. ReasonCode (book_recommender.contracts.reasons) gives
    # application code the same type safety a DB enum would.
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    reason_context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    diagnostics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class RecommendationImpression(Base):
    """Spec §8.10. "In version one, impression means delivered in a
    successful API response" (spec §8.10) — written at the same time as the
    page that delivered it, never updated afterward."""

    __tablename__ = "recommendation_impressions"
    __table_args__ = (
        UniqueConstraint(
            "request_id", "book_id", name="uq_recommendation_impressions_request_book"
        ),
        Index("ix_recommendation_impressions_request_id", "request_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("recommendation_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    book_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    rank_position: Mapped[int] = mapped_column(Integer, nullable=False)
    page_cursor: Mapped[str | None] = mapped_column(Text)
    shown_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
