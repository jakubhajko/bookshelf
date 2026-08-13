"""Response schemas for the search endpoint (spec §9.6). Never expose ORM
objects directly (spec §4.2).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from book_app.modules.books.schemas import BookUserState
from book_app.modules.interactions.attribution import InteractionSurface


class SearchResultItem(BaseModel):
    """Unlike ``RecommendationBookItem``, this carries ``user_state`` —
    spec §9.6: "Search keeps prior user states visible," so a result can
    legitimately already be rated, Not Interested, or shelved (spec §5.5's
    exclusion rules are a recommendation-surface concept, not a search
    one). The frontend needs this to render spec §12.10's "user-state
    badges" without a second round trip per result.
    """

    book_id: int
    work_id: str
    title: str
    primary_author_name: str | None
    cover_object_key: str | None
    user_state: BookUserState


class SearchResultsResponse(BaseModel):
    items: list[SearchResultItem]
    next_cursor: str | None


class SearchQueryCreateRequest(BaseModel):
    """A *committed* search (rec-spec §4.4). Deliberately has no
    `result_count`: at submit time the caller hasn't seen any results yet,
    and adding a second round trip purely to backfill a number nothing
    currently consumes isn't justified. It's an additive nullable column
    whenever a consumer appears."""

    query_text: str = Field(min_length=1, max_length=200)
    session_id: UUID | None = None
    surface: InteractionSurface | None = None


class SearchQueryResponse(BaseModel):
    """The id is the point: the caller holds it and passes it back as
    `attribution.search_query_id` when the reader opens a result, which is
    what links a search to what it produced (rec-spec §4.4)."""

    id: UUID
    query_text: str
    occurred_at: datetime
