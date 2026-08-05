"""Response schemas for the search endpoint (spec §9.6). Never expose ORM
objects directly (spec §4.2).
"""

from __future__ import annotations

from pydantic import BaseModel

from book_app.modules.books.schemas import BookUserState


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
