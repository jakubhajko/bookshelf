"""Builds the recommendation provider at app startup from configuration
(spec §10.13: "Load once at startup"). Kept out of ``main.py`` to match how
``build_auth_rate_limiter`` is factored out of it too.
"""

from __future__ import annotations

import json

from book_recommender.artifacts import LocalArtifactStorage
from book_recommender.contracts.engine import RecommendationEngine
from book_recommender.contracts.provider import RecommendationProvider
from book_recommender.engines.future_pipeline import FuturePipelineRecommendationEngine
from book_recommender.engines.mock import MockRecommendationEngine
from book_recommender.engines.popularity import PopularityRecommendationEngine
from book_recommender.exceptions import IncompatibleArtifactError
from book_recommender.providers.fallback import FallbackProvider
from book_recommender.providers.in_process import InProcessProvider
from sqlalchemy.orm import Session, sessionmaker

from book_app.core.config import Settings
from book_app.core.logging import get_logger
from book_app.modules.books import repository as books_repository
from book_app.modules.recommendations.artifact_paths import (
    POPULARITY_ARTIFACT_DIR,
    resolve_artifact_root,
)

logger = get_logger("book_app.recommendations.wiring")

MOCK_CANDIDATE_POOL_SIZE = 2000


def _load_popularity_engine(settings: Settings) -> PopularityRecommendationEngine:
    """Missing/corrupt artifact degrades to an empty ranking rather than
    failing startup (spec §10.13: "reject incompatible mappings and
    activate fallback") — there's nothing further beneath popularity to
    fall back to, so "always technically succeeds, may return nothing" is
    the most graceful option available."""
    storage = LocalArtifactStorage(resolve_artifact_root(settings.artifact_storage_local_path))
    try:
        manifest = storage.load_manifest(POPULARITY_ARTIFACT_DIR)
        scores_path = storage.resolve(POPULARITY_ARTIFACT_DIR, "scores.json")
        scores: list[float] = json.loads(scores_path.read_text())["scores"]
        ranking = [(item.book_id, scores[item.model_item_index]) for item in manifest.item_mapping]
    except (IncompatibleArtifactError, KeyError, IndexError, ValueError) as exc:
        logger.warning("popularity_artifact_unavailable", error=str(exc))
        return PopularityRecommendationEngine([], model_version="unavailable")

    logger.info(
        "popularity_artifact_loaded",
        item_count=len(ranking),
        model_version=manifest.model_version,
    )
    return PopularityRecommendationEngine(ranking, model_version=manifest.model_version)


def _load_mock_engine(session_factory: sessionmaker[Session]) -> MockRecommendationEngine:
    with session_factory() as session:
        pool = books_repository.get_active_book_ids(session, limit=MOCK_CANDIDATE_POOL_SIZE)
    return MockRecommendationEngine(pool)


def build_recommendation_provider(
    settings: Settings, session_factory: sessionmaker[Session]
) -> RecommendationProvider:
    """Spec §10.10's fallback chain always names popularity as the
    fallback, regardless of the configured primary — except when the
    primary already *is* popularity, where retrying the same engine as its
    own fallback can't help (see ``FallbackProvider``'s own docstring)."""
    if settings.recommendation_provider == "popularity":
        return InProcessProvider(_load_popularity_engine(settings))

    primary_engine: RecommendationEngine
    if settings.recommendation_provider == "mock":
        primary_engine = _load_mock_engine(session_factory)
    else:
        primary_engine = FuturePipelineRecommendationEngine()

    fallback_engine = _load_popularity_engine(settings)
    return FallbackProvider(InProcessProvider(primary_engine), InProcessProvider(fallback_engine))
