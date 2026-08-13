"""Response schemas for interactions endpoints (spec §9.4). Never expose
ORM objects directly (spec §4.2) — built explicitly in api.py, not via
``from_attributes``, since the public rating is a converted value
(``rating_value`` -> half-star float), not a plain attribute copy.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from book_app.modules.interactions.attribution import TasteSeedSource


class RatedBookItem(BaseModel):
    book_id: int
    work_id: str
    title: str
    primary_author_name: str | None
    cover_object_key: str | None
    rating: float
    rated_at: datetime


class TasteSeedItem(BaseModel):
    """A seeded book with enough catalog data to render as a card, so the
    onboarding UI can show the current selection without a round trip per
    book. Carries no `user_state`: a seed says nothing about whether the
    book is rated or shelved (ADR-0019), and implying otherwise here is
    exactly the conflation the separate table exists to prevent."""

    book_id: int
    work_id: str
    title: str
    primary_author_name: str | None
    cover_object_key: str | None
    source: str
    selected_at: datetime


class TasteSeedsResponse(BaseModel):
    items: list[TasteSeedItem]


class TasteSeedsSyncRequest(BaseModel):
    """The complete desired set, not a delta (rec-spec §6) — onboarding is
    a multi-select confirmed once, and full-replace makes retries
    idempotent.

    `max_length` is a denial-of-service bound, not a product rule:
    rec-spec §6 asks onboarding to *encourage* roughly 3-10 selections
    while explicitly not hard-blocking completion below that, so there is
    no minimum here and an empty list (clear all seeds) is valid.
    """

    book_ids: list[int] = Field(default_factory=list, max_length=100)
    source: TasteSeedSource = TasteSeedSource.ONBOARDING
