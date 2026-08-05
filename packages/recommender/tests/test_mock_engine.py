"""MockRecommendationEngine-specific behavior beyond the shared contract
(spec §10.11)."""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest

from book_recommender.contracts.engine import RecommendationEngineRequest
from book_recommender.engines.mock import MockRecommendationEngine
from book_recommender.exceptions import EngineError

POOL = list(range(1, 51))


def test_failure_rate_one_always_raises(
    make_engine_request: Callable[..., RecommendationEngineRequest],
) -> None:
    engine = MockRecommendationEngine(POOL, failure_rate=1.0)
    with pytest.raises(EngineError):
        engine.recommend(make_engine_request())


def test_failure_rate_zero_never_raises(
    make_engine_request: Callable[..., RecommendationEngineRequest],
) -> None:
    engine = MockRecommendationEngine(POOL, failure_rate=0.0)
    for _ in range(20):
        engine.recommend(make_engine_request())  # must not raise


def test_latency_seconds_actually_delays(
    make_engine_request: Callable[..., RecommendationEngineRequest],
) -> None:
    engine = MockRecommendationEngine(POOL, latency_seconds=0.05)
    started = time.monotonic()
    engine.recommend(make_engine_request())
    assert time.monotonic() - started >= 0.05


def test_does_not_merely_return_the_pool_in_order(
    make_engine_request: Callable[..., RecommendationEngineRequest],
) -> None:
    engine = MockRecommendationEngine(POOL)
    result = engine.recommend(make_engine_request(requested_count=5))
    assert [c.book_id for c in result.candidates] != POOL[:5]


def test_different_requests_see_different_orderings(
    make_engine_request: Callable[..., RecommendationEngineRequest],
) -> None:
    engine = MockRecommendationEngine(POOL)
    first = engine.recommend(make_engine_request(requested_count=10))
    second = engine.recommend(make_engine_request(requested_count=10))
    assert [c.book_id for c in first.candidates] != [c.book_id for c in second.candidates]
