"""Submitted-search persistence (rec-spec §4.4, ADR-0015). SQLAlchemy
models only — no HTTP concerns, no queries (spec §4.2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from book_app.core.database import Base


class SearchQuery(Base):
    """One *submitted* search — never a debounced autocomplete request.

    rec-spec §4.4 is explicit that only meaningful committed searches are
    logged: recording every keystroke's worth of suggestions would store
    query prefixes rather than intent, and bury the real signal under an
    order of magnitude more noise. The frontend calls this on submit only;
    the suggestions dropdown calls `GET /search/books` and writes nothing.

    Append-only, like `interaction_events` — a search happened, and
    nothing later makes that untrue.
    """

    __tablename__ = "search_queries"
    __table_args__ = (
        Index("ix_search_queries_user_time", "user_id", "occurred_at"),
        Index("ix_search_queries_session_id", "session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # No FK, matching `interaction_events.session_id`: this is a
    # frontend-generated browsing-session correlator (rec-spec §4.1), not a
    # row in any table.
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    #: Which surface submitted it. Free-form-ish but validated at the API
    #: edge against `InteractionSurface`, same as event attribution.
    surface: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
