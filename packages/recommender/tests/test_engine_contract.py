"""Shared contract tests (spec §13.2) — the same behavioral guarantees apply
identically to every engine implementation, not just mock or popularity in
isolation. A future real-pipeline engine should be added to
``ENGINE_FACTORIES`` and inherit this same coverage for free.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from book_recommender.contracts.context import SimilarBooksContext
from book_recommender.contracts.engine import RecommendationEngine, RecommendationEngineRequest
from book_recommender.engines.mock import MockRecommendationEngine
from book_recommender.engines.popularity import PopularityRecommendationEngine

POOL = list(range(1, 51))


def _mock_engine() -> RecommendationEngine:
    return MockRecommendationEngine(POOL)


def _popularity_engine() -> RecommendationEngine:
    ranking = [(book_id, float(1000 - book_id)) for book_id in POOL]
    return PopularityRecommendationEngine(ranking, model_version="test-1")


ENGINE_FACTORIES: dict[str, Callable[[], RecommendationEngine]] = {
    "mock": _mock_engine,
    "popularity": _popularity_engine,
}


@pytest.fixture(params=list(ENGINE_FACTORIES))
def engine(request: pytest.FixtureRequest) -> RecommendationEngine:
    factory: Callable[[], RecommendationEngine] = ENGINE_FACTORIES[request.param]
    return factory()


def test_returns_unique_ids(
    engine: RecommendationEngine, make_engine_request: Callable[..., RecommendationEngineRequest]
) -> None:
    result = engine.recommend(make_engine_request(requested_count=20))
    book_ids = [c.book_id for c in result.candidates]
    assert len(book_ids) == len(set(book_ids))


def test_respects_hard_exclusions(
    engine: RecommendationEngine, make_engine_request: Callable[..., RecommendationEngineRequest]
) -> None:
    excluded = frozenset(POOL[:10])
    result = engine.recommend(make_engine_request(requested_count=20, hard_exclusions=excluded))
    assert not any(c.book_id in excluded for c in result.candidates)


def test_respects_session_exclusions(
    engine: RecommendationEngine, make_engine_request: Callable[..., RecommendationEngineRequest]
) -> None:
    excluded = frozenset(POOL[10:20])
    result = engine.recommend(make_engine_request(requested_count=20, session_exclusions=excluded))
    assert not any(c.book_id in excluded for c in result.candidates)


def test_respects_requested_count(
    engine: RecommendationEngine, make_engine_request: Callable[..., RecommendationEngineRequest]
) -> None:
    result = engine.recommend(make_engine_request(requested_count=5))
    assert len(result.candidates) <= 5


def test_deterministic_for_the_same_request(
    engine: RecommendationEngine, make_engine_request: Callable[..., RecommendationEngineRequest]
) -> None:
    req = make_engine_request(requested_count=10)
    first = engine.recommend(req)
    second = engine.recommend(req)
    assert [c.book_id for c in first.candidates] == [c.book_id for c in second.candidates]


def test_metadata_and_reasons_are_present(
    engine: RecommendationEngine, make_engine_request: Callable[..., RecommendationEngineRequest]
) -> None:
    result = engine.recommend(make_engine_request(requested_count=10))
    assert result.model_name
    assert result.model_version
    assert result.catalog_version
    for candidate in result.candidates:
        assert candidate.reason_code is not None
        assert candidate.candidate_sources


def test_similar_surface_excludes_the_source_book(
    engine: RecommendationEngine, make_engine_request: Callable[..., RecommendationEngineRequest]
) -> None:
    source_book_id = POOL[0]
    result = engine.recommend(
        make_engine_request(
            surface=SimilarBooksContext(source_book_id=source_book_id), requested_count=50
        )
    )
    assert all(c.book_id != source_book_id for c in result.candidates)


@pytest.mark.parametrize(
    "empty_engine",
    [MockRecommendationEngine([]), PopularityRecommendationEngine([], model_version="test-1")],
    ids=["mock", "popularity"],
)
def test_handles_an_empty_candidate_pool(
    empty_engine: RecommendationEngine,
    make_engine_request: Callable[..., RecommendationEngineRequest],
) -> None:
    result = empty_engine.recommend(make_engine_request(requested_count=10))
    assert result.candidates == ()


def test_handles_a_user_with_no_history(
    engine: RecommendationEngine, make_engine_request: Callable[..., RecommendationEngineRequest]
) -> None:
    """A brand-new user (no ratings/shelves/history) must still get results,
    not an error (spec §13.2: "handle empty users/shelves") — the default
    ``UserContext`` from ``make_engine_request`` already has empty ratings/
    shelves/not-interested, so this just confirms that's handled cleanly."""
    result = engine.recommend(make_engine_request(requested_count=10))
    assert len(result.candidates) > 0
