"""Typed contexts the application sends into a provider/engine (spec §10.4-§10.5).

Immutable (``frozen=True``) throughout — a context is a snapshot built once
by the application before ending its DB read transaction (spec §11), never
mutated afterward. No FastAPI or ORM imports anywhere in this package (spec
§10.1) — these are plain Pydantic models the application builds from its own
repositories and hands over as data, not live objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RatingSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    book_id: int
    rating_value: int  # internal 1-10 scale (spec §5.2), not the public half-star float
    rated_at: datetime


class ShelfSummarySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    shelf_id: UUID
    name: str
    book_count: int


class RecentInteractionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: str
    book_id: int | None
    occurred_at: datetime


class UserContext(BaseModel):
    """Spec §10.5's exact field list. ``profile_version`` is an optional
    opaque tag a future derived-profile pipeline can set; no producer sets
    it yet."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    ratings: tuple[RatingSnapshot, ...]
    saved_book_ids: frozenset[int]
    shelf_ids: tuple[UUID, ...]
    not_interested_book_ids: frozenset[int]
    recent_interactions: tuple[RecentInteractionSnapshot, ...]
    shelf_summaries: tuple[ShelfSummarySnapshot, ...]
    profile_version: str | None = None


class HomeContext(BaseModel):
    """No fields beyond the discriminator — everything Home needs is
    already in ``UserContext`` (spec §10.4: "avoid unrelated nullable
    fields in one context object")."""

    model_config = ConfigDict(frozen=True)

    surface: Literal["home"] = "home"


class ShelfContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    surface: Literal["shelf"] = "shelf"
    shelf_id: UUID
    shelf_name: str
    shelf_description: str | None
    shelf_book_ids: frozenset[int]


class SimilarBooksContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    surface: Literal["similar"] = "similar"
    source_book_id: int


class SearchContext(BaseModel):
    """No producer yet — search itself is a later phase (spec §9.6 isn't in
    Phase 5's own bullet list, APP_SPECIFICATION.md §18). Defined now because
    spec §10.4 specifies the discriminated union as part of the contract
    itself, and spec §10.11 requires the mock engine to "support every
    surface", not just the ones with a live route today."""

    model_config = ConfigDict(frozen=True)

    surface: Literal["search"] = "search"
    query: str


SurfaceContext = Annotated[
    HomeContext | ShelfContext | SimilarBooksContext | SearchContext,
    Field(discriminator="surface"),
]
