"""Builds the recommendation provider at app startup from configuration
(spec §10.13: "Load once at startup"). Kept out of ``main.py`` to match how
``build_auth_rate_limiter`` is factored out of it too.

Since recommender Phase R3 this module *selects and constructs*; it does not
parse artifact file formats. ADR-0014 moved that into the recommender
package's artifact layer, because five model families would otherwise turn
application wiring into the de facto artifact format registry.
"""

from __future__ import annotations

from book_recommender.artifacts import (
    CatalogSnapshot,
    LocalArtifactStorage,
    load_popularity_artifact,
)
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
    build_artifact_storage,
    read_catalog_snapshot,
)

logger = get_logger("book_app.recommendations.wiring")

MOCK_CANDIDATE_POOL_SIZE = 2000


def _load_popularity_engine(
    storage: LocalArtifactStorage, catalog: CatalogSnapshot
) -> PopularityRecommendationEngine:
    """Missing/corrupt/incompatible artifact degrades to an empty ranking
    rather than failing startup (ADR-0014) — there's nothing further beneath
    popularity to fall back to, so "always technically succeeds, may return
    nothing" is the most graceful option available."""
    try:
        artifact = load_popularity_artifact(storage, catalog=catalog)
    except IncompatibleArtifactError as exc:
        logger.warning("popularity_artifact_unavailable", error=str(exc))
        return PopularityRecommendationEngine([], model_version="unavailable")

    logger.info("popularity_artifact_loaded", **artifact.bundle.diagnostics())
    return PopularityRecommendationEngine(artifact.ranking, model_version=artifact.model_version)


def build_recommendation_provider(
    settings: Settings, session_factory: sessionmaker[Session]
) -> RecommendationProvider:
    """Spec §10.10's fallback chain always names popularity as the
    fallback, regardless of the configured primary — except when the
    primary already *is* popularity, where retrying the same engine as its
    own fallback can't help (see ``FallbackProvider``'s own docstring).

    The one database read here is the catalog identity table every artifact
    resolves against. It happens once, at construction, and the session is
    closed before any engine exists — inference itself stays database-free
    (ADR-0007, ADR-0014).
    """
    storage = build_artifact_storage(settings.artifact_storage_local_path)
    with session_factory() as session:
        catalog = read_catalog_snapshot(session)
        mock_pool = (
            books_repository.get_active_book_ids(session, limit=MOCK_CANDIDATE_POOL_SIZE)
            if settings.recommendation_provider == "mock"
            else []
        )

    if settings.recommendation_provider == "popularity":
        return InProcessProvider(_load_popularity_engine(storage, catalog))

    primary_engine: RecommendationEngine
    if settings.recommendation_provider == "mock":
        primary_engine = MockRecommendationEngine(mock_pool)
    else:
        primary_engine = FuturePipelineRecommendationEngine()

    fallback_engine = _load_popularity_engine(storage, catalog)
    return FallbackProvider(InProcessProvider(primary_engine), InProcessProvider(fallback_engine))
