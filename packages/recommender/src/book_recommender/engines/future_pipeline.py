"""Placeholder for the real recommendation pipeline (spec §10.2: "future
pipeline adapter placeholder"). Exists so ``recommendation_provider``
configuration can name it today without implying it works — selecting it
raises clearly rather than silently returning nothing or fabricated data.
Building the real pipeline is explicitly out of scope (spec §2: "do not
implement the final recommendation funnel"); this only reserves the seam.
"""

from __future__ import annotations

from book_recommender.contracts.engine import (
    RecommendationEngineRequest,
    RecommendationEngineResult,
)
from book_recommender.exceptions import EngineError

MODEL_NAME = "future_pipeline"


class FuturePipelineRecommendationEngine:
    """Conforms to :class:`~book_recommender.contracts.engine.RecommendationEngine`
    so it can be wired in exactly like mock/popularity once a real pipeline
    exists — no route, service, or protocol change needed then."""

    def recommend(self, request: RecommendationEngineRequest) -> RecommendationEngineResult:
        raise EngineError(
            "future_pipeline is a placeholder — no real recommendation model is implemented yet"
        )
