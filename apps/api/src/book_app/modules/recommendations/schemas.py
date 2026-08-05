"""Response schemas for recommendation endpoints (spec §9.5). Never expose
ORM objects directly (spec §4.2).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

# Spec §10.9: "API maps codes to prose." Codes are the stable contract;
# this prose is purely presentational and safe to reword without touching
# anything upstream.
REASON_TEXT: dict[str, str] = {
    "POPULAR_WITH_READERS": "Popular with readers",
    "BASED_ON_HIGH_RATINGS": "Based on your high ratings",
    "SIMILAR_TO_SAVED_BOOKS": "Similar to books you've saved",
    "SIMILAR_TO_SHELF": "Similar to books on this shelf",
    "SIMILAR_TO_CURRENT_BOOK": "Similar to this book",
    "SEMANTIC_QUERY_MATCH": "Matches your search",
    "EXPLORATION": "Something different to explore",
}


class RecommendationBookItem(BaseModel):
    book_id: int
    work_id: str
    title: str
    primary_author_name: str | None
    cover_object_key: str | None
    rank: int
    score: float | None
    reason_code: str
    reason_text: str


class RecommendationPageResponse(BaseModel):
    request_id: UUID
    surface: str
    model_version: str
    items: list[RecommendationBookItem]
    next_cursor: str | None
