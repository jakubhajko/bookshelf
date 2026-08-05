"""In-process provider (spec §10.3) — wraps a synchronous engine, running it
off the event loop (spec §10.3: "blocking work runs outside the async event
loop") via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio

from book_recommender.contracts.engine import RecommendationEngine, RecommendationEngineRequest
from book_recommender.contracts.provider import (
    RecommendationBatch,
    RecommendationCandidate,
    RecommendationRequest,
)

PROVIDER_NAME = "in_process"


class InProcessProvider:
    def __init__(self, engine: RecommendationEngine) -> None:
        self._engine = engine

    async def recommend(self, request: RecommendationRequest) -> RecommendationBatch:
        engine_request = RecommendationEngineRequest(
            request_id=request.request_id,
            user_context=request.user_context,
            surface_context=request.surface_context,
            requested_count=request.requested_count,
            hard_exclusions=request.hard_exclusions,
            session_exclusions=request.session_exclusions,
            catalog_version=request.catalog_version,
        )
        result = await asyncio.to_thread(self._engine.recommend, engine_request)

        candidates = tuple(
            RecommendationCandidate(
                book_id=c.book_id,
                score=c.score,
                candidate_sources=c.candidate_sources,
                reason_code=c.reason_code,
                reason_context=c.reason_context,
                diagnostics=c.diagnostics,
            )
            for c in result.candidates
        )
        return RecommendationBatch(
            provider_name=PROVIDER_NAME,
            model_name=result.model_name,
            model_version=result.model_version,
            catalog_version=result.catalog_version,
            generated_at=result.generated_at,
            candidates=candidates,
            fallback_used=False,
            diagnostics=result.diagnostics,
        )
