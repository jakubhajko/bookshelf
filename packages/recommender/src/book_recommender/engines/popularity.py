"""Popularity engine (spec §10.12) — serves an already-computed ranking.

The score computation itself (from ``bx_ratings``/``bx_explicit``/ratings
count/average rating/support adjustment) happens in the CLI that builds the
artifact, not here — this package has no database access (spec §10.1). This
engine's only job is to filter exclusions and return a page of an already
-ordered ranking; a fallback and baseline, not the final recommender (spec
§10.12).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from book_recommender.contracts.context import SimilarBooksContext
from book_recommender.contracts.engine import (
    EngineCandidate,
    RecommendationEngineRequest,
    RecommendationEngineResult,
)
from book_recommender.contracts.reasons import ReasonCode

MODEL_NAME = "popularity"


class PopularityRecommendationEngine:
    def __init__(self, ranking: Sequence[tuple[int, float]], *, model_version: str) -> None:
        """``ranking`` must already be sorted, most-popular first — this
        engine trusts and preserves that order (spec §10.7: order is
        authoritative), it doesn't re-sort."""
        self._ranking = tuple(ranking)
        self._model_version = model_version

    def recommend(self, request: RecommendationEngineRequest) -> RecommendationEngineResult:
        surface = request.surface_context
        excluded = set(request.hard_exclusions) | set(request.session_exclusions)
        if isinstance(surface, SimilarBooksContext):
            excluded.add(surface.source_book_id)

        candidates = tuple(
            EngineCandidate(
                book_id=book_id,
                score=score,
                candidate_sources=("popularity",),
                # POPULAR_WITH_READERS regardless of surface: honest about
                # what this engine actually does (raw popularity), never
                # claims a similarity signal it doesn't have.
                reason_code=ReasonCode.POPULAR_WITH_READERS,
                diagnostics={},
            )
            for book_id, score in self._ranking
            if book_id not in excluded
        )[: request.requested_count]

        return RecommendationEngineResult(
            model_name=MODEL_NAME,
            model_version=self._model_version,
            catalog_version=request.catalog_version,
            generated_at=datetime.now(UTC),
            candidates=candidates,
            diagnostics={"ranking_size": len(self._ranking)},
        )
