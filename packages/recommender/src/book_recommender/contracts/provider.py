"""Asynchronous provider protocol (spec §10.3) — the layer the application
calls directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from book_recommender.contracts.context import SurfaceContext, UserContext
from book_recommender.contracts.reasons import ReasonCode


class RecommendationRequest(BaseModel):
    """See :class:`~book_recommender.contracts.engine.RecommendationEngineRequest`
    for why this is a distinct type from the engine-level request rather than
    a shared alias."""

    model_config = ConfigDict(frozen=True)

    request_id: UUID
    user_context: UserContext
    surface_context: SurfaceContext
    requested_count: int
    hard_exclusions: frozenset[int]
    session_exclusions: frozenset[int]
    catalog_version: str


class RecommendationCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    book_id: int
    score: float | None
    candidate_sources: tuple[str, ...]
    reason_code: ReasonCode
    reason_context: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class RecommendationBatch(BaseModel):
    """Spec §10.7's batch fields, plus ``provider_name``/``fallback_used`` —
    both provider-level facts an engine has no way to know about itself
    (whether *it* is being invoked as someone else's fallback isn't
    information the engine has), needed verbatim by
    ``recommendation_requests`` (spec §8.10)."""

    model_config = ConfigDict(frozen=True)

    provider_name: str
    model_name: str
    model_version: str
    catalog_version: str
    generated_at: datetime
    candidates: tuple[RecommendationCandidate, ...]
    fallback_used: bool = False
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class RecommendationProvider(Protocol):
    async def recommend(self, request: RecommendationRequest) -> RecommendationBatch: ...
