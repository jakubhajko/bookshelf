"""Synchronous engine protocol (spec §10.2) — the layer a provider calls
internally, off the async event loop (spec §10.3: "blocking work runs
outside the async event loop").
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from book_recommender.contracts.context import SurfaceContext, UserContext
from book_recommender.contracts.reasons import ReasonCode


class RecommendationEngineRequest(BaseModel):
    """Spec §10.6's request fields. Structurally mirrors
    :class:`~book_recommender.contracts.provider.RecommendationRequest` on
    purpose — the two are kept as distinct named types (matching the spec's
    own naming) so a remote provider can later add provider-only fields
    (auth, timeouts) without touching the engine protocol at all."""

    model_config = ConfigDict(frozen=True)

    request_id: UUID
    user_context: UserContext
    surface_context: SurfaceContext
    requested_count: int
    hard_exclusions: frozenset[int]
    session_exclusions: frozenset[int]
    catalog_version: str


class EngineCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    book_id: int
    score: float | None
    candidate_sources: tuple[str, ...]
    reason_code: ReasonCode
    reason_context: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class RecommendationEngineResult(BaseModel):
    """Spec §10.7's result fields. Order is authoritative — ``candidates``
    is already the final ranking; nothing downstream may re-sort it."""

    model_config = ConfigDict(frozen=True)

    model_name: str
    model_version: str
    catalog_version: str
    generated_at: datetime
    candidates: tuple[EngineCandidate, ...]
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class RecommendationEngine(Protocol):
    def recommend(self, request: RecommendationEngineRequest) -> RecommendationEngineResult: ...
