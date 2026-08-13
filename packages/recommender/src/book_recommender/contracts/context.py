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


class SavedBookSnapshot(BaseModel):
    """One shelf membership (rec-spec §5).

    A book on three shelves produces three of these. Collapsing them — as
    the global ``saved_book_ids`` set necessarily does — throws away the
    two things shelf-aware generators need: *which* shelf expressed the
    interest, and *when*. Both `saved_book_ids` and this exist because they
    answer different questions: eligibility asks "is this saved anywhere?",
    semantic shelf profiling asks "what is on this particular shelf, and
    how recently?"
    """

    model_config = ConfigDict(frozen=True)

    book_id: int
    shelf_id: UUID
    added_at: datetime


class TasteSeedSnapshot(BaseModel):
    """An explicit taste seed (rec-spec §6, ADR-0019).

    Not a rating and not a shelf save — a book the reader said appeals to
    them, typically during onboarding. Generators weight it as strong
    positive evidence, but it never implies the reader has *read* the book,
    which is what a rating means in this product.
    """

    model_config = ConfigDict(frozen=True)

    book_id: int
    source: str
    selected_at: datetime


class RecentInteractionSnapshot(BaseModel):
    """A recent raw event, with the provenance recommender Phase R1 started
    recording (rec-spec §4.3).

    Previously this carried only event type, book and time. The attribution
    fields were being written to `interaction_events` and then dropped on
    the way into the context — so a future session-aware generator could
    not tell an open that came from a recommendation from one that came
    from a search, which is most of what makes session evidence useful.
    Everything beyond the first three fields is optional, because
    attribution is optional (ADR-0015).
    """

    model_config = ConfigDict(frozen=True)

    event_type: str
    book_id: int | None
    occurred_at: datetime
    shelf_id: UUID | None = None
    surface: str | None = None
    session_id: UUID | None = None
    recommendation_request_id: UUID | None = None
    search_query_id: UUID | None = None
    source_book_id: int | None = None
    rank_position: int | None = None


class UserContext(BaseModel):
    """Spec §10.5's field list, extended by recommender Phase R2 (rec-spec
    §5) with per-shelf membership, taste seeds and a real
    ``profile_version``.

    Bounded on every unbounded component — see the application's
    ``context_builder`` for the limits and the order in which each list is
    truncated. An unbounded context is a latency and memory problem that
    only appears for the heaviest users, which is the worst time to find
    it.
    """

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    ratings: tuple[RatingSnapshot, ...]
    #: Every book on any shelf, flattened — kept for eligibility (spec
    #: §5.5), which only ever asks "saved anywhere?". Not redundant with
    #: ``saved_books``; see :class:`SavedBookSnapshot`.
    saved_book_ids: frozenset[int]
    saved_books: tuple[SavedBookSnapshot, ...] = ()
    shelf_ids: tuple[UUID, ...]
    not_interested_book_ids: frozenset[int]
    recent_interactions: tuple[RecentInteractionSnapshot, ...]
    shelf_summaries: tuple[ShelfSummarySnapshot, ...]
    taste_seeds: tuple[TasteSeedSnapshot, ...] = ()
    #: Deterministic fingerprint of the *durable* preference evidence in
    #: this context (rec-spec §5). Equal versions mean equal long-term
    #: profile, which is what makes it usable as a cache key for expensive
    #: derived state such as an ALS fold-in factor
    #: (``(user_id, profile_version, model_version)``, rec-spec §9.2).
    #:
    #: Deliberately *not* invalidated by passive evidence: being shown a
    #: recommendation, or opening a book, leaves it unchanged. Required
    #: rather than optional — a cache key that might be absent is not a
    #: cache key.
    profile_version: str


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
