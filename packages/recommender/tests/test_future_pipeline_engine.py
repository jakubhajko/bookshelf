"""FuturePipelineRecommendationEngine is a placeholder — confirms it fails
clearly rather than returning fabricated results (spec §10.2)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from book_recommender.contracts.engine import RecommendationEngineRequest
from book_recommender.engines.future_pipeline import FuturePipelineRecommendationEngine
from book_recommender.exceptions import EngineError


def test_future_pipeline_always_raises(
    make_engine_request: Callable[..., RecommendationEngineRequest],
) -> None:
    engine = FuturePipelineRecommendationEngine()
    with pytest.raises(EngineError):
        engine.recommend(make_engine_request())
