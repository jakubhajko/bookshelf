"""Typed contracts: contexts, requests/results/batches, reason codes.

Nothing in this subpackage does I/O — see ``artifacts/`` for artifact
loading and ``engines/``/``providers/`` for implementations.
"""

from __future__ import annotations

from book_recommender.contracts.context import (
    HomeContext,
    RatingSnapshot,
    RecentInteractionSnapshot,
    SearchContext,
    ShelfContext,
    ShelfSummarySnapshot,
    SimilarBooksContext,
    SurfaceContext,
    UserContext,
)
from book_recommender.contracts.engine import (
    EngineCandidate,
    RecommendationEngine,
    RecommendationEngineRequest,
    RecommendationEngineResult,
)
from book_recommender.contracts.provider import (
    RecommendationBatch,
    RecommendationCandidate,
    RecommendationProvider,
    RecommendationRequest,
)
from book_recommender.contracts.reasons import ReasonCode

__all__ = [
    "EngineCandidate",
    "HomeContext",
    "RatingSnapshot",
    "RecentInteractionSnapshot",
    "RecommendationBatch",
    "RecommendationCandidate",
    "RecommendationEngine",
    "RecommendationEngineRequest",
    "RecommendationEngineResult",
    "RecommendationProvider",
    "RecommendationRequest",
    "ReasonCode",
    "SearchContext",
    "ShelfContext",
    "ShelfSummarySnapshot",
    "SimilarBooksContext",
    "SurfaceContext",
    "UserContext",
]
