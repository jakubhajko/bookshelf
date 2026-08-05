"""Provider-layer tests: in-process wrapping (spec §10.3) and the
primary/fallback chain (spec §10.10). Plain ``asyncio.run`` rather than a
``pytest-asyncio`` dependency — a handful of async tests doesn't justify
adding a plugin.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from book_recommender.contracts.provider import (
    RecommendationBatch,
    RecommendationCandidate,
    RecommendationRequest,
)
from book_recommender.contracts.reasons import ReasonCode
from book_recommender.engines.mock import MockRecommendationEngine
from book_recommender.engines.popularity import PopularityRecommendationEngine
from book_recommender.exceptions import EngineError, ProviderError
from book_recommender.providers.fallback import FallbackProvider
from book_recommender.providers.in_process import InProcessProvider

POOL = list(range(1, 21))


class _AlwaysFailsProvider:
    async def recommend(self, request: RecommendationRequest) -> RecommendationBatch:
        raise EngineError("boom")


class _ReturnsInvalidProvider:
    """Returns a batch that includes an excluded book_id — the kind of
    result the fallback layer's own sanity check must catch."""

    async def recommend(self, request: RecommendationRequest) -> RecommendationBatch:
        excluded_id = next(iter(request.hard_exclusions), 999)
        return RecommendationBatch(
            provider_name="broken",
            model_name="broken",
            model_version="1",
            catalog_version=request.catalog_version,
            generated_at=datetime.now(UTC),
            candidates=(
                RecommendationCandidate(
                    book_id=excluded_id,
                    score=1.0,
                    candidate_sources=("broken",),
                    reason_code=ReasonCode.EXPLORATION,
                ),
            ),
        )


def _popularity_provider() -> InProcessProvider:
    engine = PopularityRecommendationEngine([(b, float(b)) for b in POOL], model_version="v1")
    return InProcessProvider(engine)


def test_in_process_provider_wraps_engine_result(
    make_provider_request: Callable[..., RecommendationRequest],
) -> None:
    provider = InProcessProvider(MockRecommendationEngine(POOL))
    batch = asyncio.run(provider.recommend(make_provider_request(requested_count=5)))
    assert batch.provider_name == "in_process"
    assert batch.fallback_used is False
    assert len(batch.candidates) <= 5


def test_fallback_provider_uses_primary_when_it_succeeds(
    make_provider_request: Callable[..., RecommendationRequest],
) -> None:
    primary = InProcessProvider(MockRecommendationEngine(POOL))
    provider = FallbackProvider(primary, _popularity_provider())
    batch = asyncio.run(provider.recommend(make_provider_request()))
    assert batch.fallback_used is False
    assert batch.model_name == "mock"


def test_fallback_provider_falls_back_when_primary_fails(
    make_provider_request: Callable[..., RecommendationRequest],
) -> None:
    provider = FallbackProvider(_AlwaysFailsProvider(), _popularity_provider())
    batch = asyncio.run(provider.recommend(make_provider_request()))
    assert batch.fallback_used is True
    assert batch.model_name == "popularity"
    assert "primary_error" in batch.diagnostics


def test_fallback_provider_raises_when_both_fail(
    make_provider_request: Callable[..., RecommendationRequest],
) -> None:
    provider = FallbackProvider(_AlwaysFailsProvider(), _AlwaysFailsProvider())
    with pytest.raises(ProviderError):
        asyncio.run(provider.recommend(make_provider_request()))


def test_fallback_provider_treats_an_invalid_primary_batch_as_a_failure(
    make_provider_request: Callable[..., RecommendationRequest],
) -> None:
    excluded = frozenset({7})
    provider = FallbackProvider(_ReturnsInvalidProvider(), _popularity_provider())
    batch = asyncio.run(provider.recommend(make_provider_request(hard_exclusions=excluded)))
    assert batch.fallback_used is True
