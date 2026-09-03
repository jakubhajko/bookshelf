"""Builds the recommendation provider at app startup from configuration
(spec §10.13: "Load once at startup"). Kept out of ``main.py`` to match how
``build_auth_rate_limiter`` is factored out of it too.

Since recommender Phase R3 this module *selects and constructs*; it does not
parse artifact file formats. ADR-0014 moved that into the recommender
package's artifact layer, because five model families would otherwise turn
application wiring into the de facto artifact format registry.
"""

from __future__ import annotations

from collections.abc import Callable

from book_recommender.artifacts import (
    CatalogSnapshot,
    ContentEmbeddings,
    ItemMetadataTable,
    LocalArtifactStorage,
    PopularityArtifact,
    load_als_artifact,
    load_content_artifact,
    load_item_cf_artifact,
    load_item_metadata_artifact,
    load_popularity_artifact,
    load_source_similarity_artifact,
)
from book_recommender.contracts.engine import RecommendationEngine
from book_recommender.contracts.provider import RecommendationProvider
from book_recommender.engines.mock import MockRecommendationEngine
from book_recommender.engines.pipeline import PipelineDependencies, PipelineRecommendationEngine
from book_recommender.engines.popularity import PopularityRecommendationEngine
from book_recommender.exceptions import IncompatibleArtifactError
from book_recommender.generators import (
    AlsCandidateGenerator,
    CandidateGenerator,
    ItemItemCFCandidateGenerator,
    PopularityCandidateGenerator,
    SemanticCandidateGenerator,
    SourceSimilarityCandidateGenerator,
)
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


def _popularity_engine(artifact: PopularityArtifact | None) -> PopularityRecommendationEngine:
    """Missing/corrupt/incompatible artifact degrades to an empty ranking
    rather than failing startup (ADR-0014) — there's nothing further beneath
    popularity to fall back to, so "always technically succeeds, may return
    nothing" is the most graceful option available."""
    if artifact is None:
        return PopularityRecommendationEngine([], model_version="unavailable")
    return PopularityRecommendationEngine(artifact.ranking, model_version=artifact.model_version)


def _load_optional[T](name: str, loader: Callable[[], T], *, mmap_note: str = "") -> T | None:
    """Load one artifact family, degrading to ``None`` rather than raising.

    rec-spec §27's whole failure section in one helper: every artifact is
    optional at startup, a missing one costs the generators and features
    that depend on it, and the reason is logged rather than swallowed. A
    process that refuses to boot because one artifact is stale is strictly
    worse than one that serves popularity while somebody rebuilds it.
    """
    try:
        artifact = loader()
    except IncompatibleArtifactError as exc:
        logger.warning("artifact_unavailable", family=name, error=str(exc))
        return None
    logger.info("artifact_loaded", family=name, note=mmap_note or None)
    return artifact


def build_pipeline_engine(
    storage: LocalArtifactStorage,
    catalog: CatalogSnapshot,
    popularity: PopularityArtifact | None,
    *,
    withheld_families: frozenset[str] = frozenset(),
) -> PipelineRecommendationEngine:
    """Load every artifact family once and assemble the five generators.

    Public because the ``evaluate_recommender`` CLI builds the engine the
    same way serving does. A diagnostic that assembled its own generator
    tuple would measure a pipeline nobody is served (CLAUDE.md).

    ``withheld_families`` skips loading the named families, which is how
    that CLI's degradation section models rec-spec §27 without moving files
    around. Withholding is exactly what a missing, stale or corrupt artifact
    reduces to here — ``_load_optional`` returns ``None`` for all three — so
    the simulated failure and the real one take the same code path.

    Per-worker memory is the binding constraint here, not latency (plan.md
    §5n): all six families cost ~1.0-1.2 GB resident, of which the content
    matrix is ~427 MB for a 181 MB file because the loader holds the raw
    read alive while indexing it into its final form. ``mmap=True`` removes
    exactly one of those copies at no load-time cost, so serving takes it —
    the array is read once per request and paged from the OS cache, which
    is what mmap is for.
    """

    def load[T](family: str, loader: Callable[[], T], *, mmap_note: str = "") -> T | None:
        if family in withheld_families:
            logger.info("artifact_withheld", family=family)
            return None
        return _load_optional(family, loader, mmap_note=mmap_note)

    content: ContentEmbeddings | None = load(
        "content",
        lambda: load_content_artifact(storage, catalog=catalog, mmap=True),
        mmap_note="mmap",
    )
    metadata: ItemMetadataTable | None = load(
        "item_metadata", lambda: load_item_metadata_artifact(storage, catalog=catalog)
    )
    als = load(
        "als", lambda: load_als_artifact(storage, catalog=catalog, mmap=True), mmap_note="mmap"
    )
    item_cf = load("item_cf", lambda: load_item_cf_artifact(storage, catalog=catalog))
    graph = load(
        "source_similarity", lambda: load_source_similarity_artifact(storage, catalog=catalog)
    )

    generators: tuple[CandidateGenerator, ...] = (
        AlsCandidateGenerator(als),
        ItemItemCFCandidateGenerator(item_cf),
        SemanticCandidateGenerator(content),
        SourceSimilarityCandidateGenerator(graph),
        PopularityCandidateGenerator(
            None if popularity is None else popularity.ranking,
            model_version="" if popularity is None else popularity.model_version,
        ),
    )

    # A generator constructed with ``None`` reports NO_ARTIFACT rather than
    # being absent, which is what keeps rec-spec §27's degradation visible
    # in batch diagnostics instead of looking like an empty result.
    available = [
        name
        for name, artifact in (
            ("content", content),
            ("item_metadata", metadata),
            ("als", als),
            ("item_cf", item_cf),
            ("source_similarity", graph),
            ("popularity", popularity),
        )
        if artifact is not None
    ]
    logger.info("pipeline_engine_built", artifacts=available, generators=len(generators))

    # Read through the shared bundle rather than a per-class property:
    # ItemMetadataTable and SourceSimilarityGraph carry the manifest but do
    # not expose a `model_version` shortcut the way the others do.
    versions = {
        name: artifact.bundle.manifest.model_version
        for name, artifact in (
            ("content", content),
            ("item_metadata", metadata),
            ("als", als),
            ("item_cf", item_cf),
            ("source_similarity", graph),
            ("popularity", popularity),
        )
        if artifact is not None
    }

    return PipelineRecommendationEngine(
        PipelineDependencies(
            generators=generators,
            embeddings=content,
            metadata=metadata,
            popularity=None if popularity is None else dict(popularity.ranking),
            artifact_versions=versions,
        )
    )


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
    storage = build_artifact_storage(settings)

    def _load_popularity_artifact(
        artifact_storage: LocalArtifactStorage,
    ) -> PopularityArtifact | None:
        try:
            artifact = load_popularity_artifact(artifact_storage, catalog=catalog)
        except IncompatibleArtifactError as exc:
            logger.warning("popularity_artifact_unavailable", error=str(exc))
            return None
        logger.info("popularity_artifact_loaded", **artifact.bundle.diagnostics())
        return artifact

    with session_factory() as session:
        catalog = read_catalog_snapshot(session)
        mock_pool = (
            books_repository.get_active_book_ids(session, limit=MOCK_CANDIDATE_POOL_SIZE)
            if settings.recommendation_provider == "mock"
            else []
        )

    if settings.recommendation_provider == "popularity":
        return InProcessProvider(_popularity_engine(_load_popularity_artifact(storage)))

    popularity_artifact = _load_popularity_artifact(storage)

    primary_engine: RecommendationEngine
    if settings.recommendation_provider == "mock":
        primary_engine = MockRecommendationEngine(mock_pool)
    else:
        primary_engine = build_pipeline_engine(storage, catalog, popularity_artifact)

    # Spec §10.10's chain is unchanged by R8: the pipeline is the primary,
    # and standalone popularity is still behind it. The pipeline degrades
    # internally for a missing artifact (rec-spec §27), so this fallback is
    # for the case it cannot handle itself — an unexpected raise or a
    # provider timeout.
    fallback_engine = _popularity_engine(popularity_artifact)
    return FallbackProvider(InProcessProvider(primary_engine), InProcessProvider(fallback_engine))
