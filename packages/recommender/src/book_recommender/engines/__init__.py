"""Synchronous ``RecommendationEngine`` implementations (spec §10.2).

Not one of spec §10.1's four listed top-level directories (``contracts/
providers/ artifacts/ exceptions.py``) — added as a natural sibling to
``providers/`` for the engine implementations the spec explicitly requires
(mock/popularity/future-pipeline) but doesn't specify a home for. Purely
additive: it doesn't move or replace any of the required four.
"""

from __future__ import annotations

from book_recommender.engines.future_pipeline import FuturePipelineRecommendationEngine
from book_recommender.engines.mock import MockRecommendationEngine
from book_recommender.engines.popularity import PopularityRecommendationEngine

__all__ = [
    "FuturePipelineRecommendationEngine",
    "MockRecommendationEngine",
    "PopularityRecommendationEngine",
]
