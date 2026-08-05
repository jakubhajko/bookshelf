"""Response schemas for interactions endpoints (spec §9.4). Never expose
ORM objects directly (spec §4.2) — built explicitly in api.py, not via
``from_attributes``, since the public rating is a converted value
(``rating_value`` -> half-star float), not a plain attribute copy.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RatedBookItem(BaseModel):
    book_id: int
    work_id: str
    title: str
    primary_author_name: str | None
    cover_object_key: str | None
    rating: float
    rated_at: datetime
