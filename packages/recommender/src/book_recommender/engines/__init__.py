"""Synchronous ``RecommendationEngine`` implementations (spec §10.2).

Not one of spec §10.1's four listed top-level directories (``contracts/
providers/ artifacts/ exceptions.py``) — added as a natural sibling to
``providers/`` for the engine implementations the spec explicitly requires
(mock/popularity/pipeline) but doesn't specify a home for. Purely additive:
it doesn't move or replace any of the required four.

``future_pipeline.py`` lived here until R8 as a placeholder that raised on
every call, reserving this seam. R8 filled it, so the placeholder is gone
rather than left as unreachable code that still claims nothing is
implemented.
"""

from __future__ import annotations

from book_recommender.engines.mock import MockRecommendationEngine
from book_recommender.engines.pipeline import (
    PipelineDependencies,
    PipelineRecommendationEngine,
)
from book_recommender.engines.popularity import PopularityRecommendationEngine

__all__ = [
    "MockRecommendationEngine",
    "PipelineDependencies",
    "PipelineRecommendationEngine",
    "PopularityRecommendationEngine",
]
