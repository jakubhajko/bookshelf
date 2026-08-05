"""PopularityRecommendationEngine-specific behavior beyond the shared
contract (spec §10.12)."""

from __future__ import annotations

from collections.abc import Callable

from book_recommender.contracts.engine import RecommendationEngineRequest
from book_recommender.engines.popularity import PopularityRecommendationEngine


def test_preserves_ranking_order(
    make_engine_request: Callable[..., RecommendationEngineRequest],
) -> None:
    ranking = [(10, 99.0), (20, 88.0), (30, 77.0), (40, 66.0)]
    engine = PopularityRecommendationEngine(ranking, model_version="v1")
    result = engine.recommend(make_engine_request(requested_count=10))
    assert [c.book_id for c in result.candidates] == [10, 20, 30, 40]
    assert [c.score for c in result.candidates] == [99.0, 88.0, 77.0, 66.0]


def test_excluding_a_top_item_preserves_relative_order_of_the_rest(
    make_engine_request: Callable[..., RecommendationEngineRequest],
) -> None:
    ranking = [(10, 99.0), (20, 88.0), (30, 77.0)]
    engine = PopularityRecommendationEngine(ranking, model_version="v1")
    result = engine.recommend(
        make_engine_request(requested_count=10, hard_exclusions=frozenset({10}))
    )
    assert [c.book_id for c in result.candidates] == [20, 30]
