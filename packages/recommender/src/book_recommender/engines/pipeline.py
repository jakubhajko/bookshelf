"""The real recommendation pipeline (rec-spec §16-§21, ADR-0017, ADR-0023).

Everything R3-R7 built, assembled behind the `RecommendationEngine`
protocol that has existed since spec §10.2. Five generators produce ranked
lists, weighted RRF unions them, a deterministic ranker scores them and a
surface-specific reranker chooses the final order.

**The order that leaves this method is authoritative.** ADR-0006 and
ADR-0007 make it the persisted batch, and cursor pages replay it rather
than re-inferring; nothing downstream may re-sort (spec §10.7).

Three constraints shape the structure rather than decorating it:

**No database, ever.** The engine holds artifacts loaded once at
construction and reads an immutable request. CLAUDE.md forbids an open
transaction during inference, and there is no session here to open one with.

**Degrade, never fail.** rec-spec §27 lists the cases — a missing ALS
artifact, an empty source graph for a book, a reader with no evidence at
all — and every one of them must still return books. A generator that
raises is isolated and reported, not propagated.

**Reasons must be true.** rec-spec §21: a reason code has to correspond to
evidence that materially contributed. The mapping here reads the dominant
contributing source, so "Popular with readers" appears only when popularity
genuinely produced the candidate.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import numpy.typing as npt

from book_recommender.artifacts.content import ContentEmbeddings
from book_recommender.artifacts.item_metadata import ItemMetadataTable
from book_recommender.config import (
    SURFACES,
    InterestProfileConfig,
    SignalWeights,
    SurfaceConfig,
)
from book_recommender.contracts.context import (
    ShelfContext,
    SimilarBooksContext,
    SurfaceContext,
    UserContext,
)
from book_recommender.contracts.engine import (
    EngineCandidate,
    RecommendationEngineRequest,
    RecommendationEngineResult,
)
from book_recommender.contracts.reasons import ReasonCode
from book_recommender.generators import (
    PROVENANCE_INTEREST,
    PROVENANCE_SHELF,
    PROVENANCE_SOURCE_BOOK,
    PROVENANCE_TARGET_SHELF,
    CandidateGenerator,
    GeneratorId,
    GeneratorRequest,
    GeneratorResult,
    GeneratorStatus,
)
from book_recommender.pipeline import (
    DeterministicRanker,
    DiversityReranker,
    FusedCandidate,
    RankedCandidate,
    Ranker,
    RankingContext,
    RerankContext,
    RerankedCandidate,
    Reranker,
    fuse,
)
from book_recommender.profiling import SemanticProfile, build_semantic_profile
from book_recommender.profiling.interests import InterestProfile

MODEL_NAME = "pipeline"


class _StageTimer:
    """Wall-clock milliseconds per pipeline stage.

    Wall clock rather than CPU time on purpose: the semantic stages page a
    memory-mapped matrix (ADR-0014), and the time a request spends waiting
    for the OS to fault pages in is time the reader waits too.
    """

    def __init__(self) -> None:
        self._stages: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self._stages[name] = (
                self._stages.get(name, 0.0) + (time.perf_counter() - started) * 1000.0
            )

    def as_dict(self) -> dict[str, float]:
        stages = {name: round(value, 2) for name, value in self._stages.items()}
        stages["total"] = round(sum(self._stages.values()), 2)
        return stages


#: Internal ratings at or below this are negative evidence for the ranker
#: (rec-spec §7.1's 1-5 rows). 6 is neutral and contributes to neither side.
_NEGATIVE_RATING_MAX = 5
#: Internal ratings at or above this count as strong positive evidence.
_STRONG_RATING_MIN = 8


@dataclass(frozen=True)
class PipelineDependencies:
    """Artifact-backed state loaded once per process (rec-spec §24).

    Every field except ``generators`` is optional, because rec-spec §27
    requires the pipeline to run without any given artifact. Missing
    embeddings cost the semantic generator, the semantic ranking features
    and cosine duplicate detection; missing metadata costs author, series
    and identity control. Neither stops a batch being produced.
    """

    generators: tuple[CandidateGenerator, ...]
    embeddings: ContentEmbeddings | None = None
    metadata: ItemMetadataTable | None = None
    popularity: Mapping[int, float] | None = None
    #: ``family -> model_version`` for every artifact actually loaded.
    #:
    #: A pipeline batch is produced by six artifacts with six independent
    #: build timestamps, so no single one of them is "the" model version.
    #: Naming any one — popularity's, say — would put a string in
    #: ``recommendation_requests.model_version`` that looks authoritative
    #: and is wrong about five sixths of what produced the batch.
    artifact_versions: Mapping[str, str] = field(default_factory=dict)
    #: Overrides the digest derived from ``artifact_versions``. Only tests
    #: should need this.
    model_version: str | None = None

    def resolved_model_version(self) -> str:
        """A short digest of every contributing artifact version.

        Deterministic and order-independent, so two processes loading the
        same artifacts report the same version, and *any* artifact rebuild
        changes it. The full mapping travels in batch diagnostics, which is
        where somebody debugging a batch will look.
        """
        if self.model_version is not None:
            return self.model_version
        if not self.artifact_versions:
            return "unknown"
        payload = ";".join(
            f"{family}={version}" for family, version in sorted(self.artifact_versions.items())
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()[:12]
        return f"pipeline-{digest}"


@dataclass(frozen=True)
class PipelineTrace:
    """Every stage's output for one request (rec-spec §23.3).

    Returned by :meth:`PipelineRecommendationEngine.run`, which
    :meth:`PipelineRecommendationEngine.recommend` is a thin wrapper around,
    so an evaluation that reads this is reading the served pipeline rather
    than a reconstruction of it.
    """

    surface: SurfaceConfig
    profile: SemanticProfile | None
    #: Application-owned eligibility as the generators saw it.
    exclusions: frozenset[int]
    generator_results: tuple[GeneratorResult, ...]
    fused: tuple[FusedCandidate, ...]
    ranked: tuple[RankedCandidate, ...]
    final: tuple[RerankedCandidate, ...]
    #: Wall-clock milliseconds per stage, plus ``total``.
    stage_ms: Mapping[str, float]

    def result_for(self, generator: str) -> GeneratorResult | None:
        for result in self.generator_results:
            if result.generator.value == generator:
                return result
        return None

    @property
    def quotas(self) -> dict[str, int]:
        """What each participating generator was asked for."""
        return {quota.generator: quota.count for quota in self.surface.quotas if quota.enabled}


class PipelineRecommendationEngine:
    """Generators -> weighted RRF -> deterministic ranking -> reranking."""

    def __init__(
        self,
        dependencies: PipelineDependencies,
        *,
        surfaces: Mapping[str, SurfaceConfig] = SURFACES,
        ranker: Ranker | None = None,
        reranker: Reranker | None = None,
        signal_weights: SignalWeights | None = None,
        profile_config: InterestProfileConfig | None = None,
    ) -> None:
        self._deps = dependencies
        self._surfaces = surfaces
        self._ranker = ranker or DeterministicRanker()
        self._reranker = reranker or DiversityReranker()
        self._signal_weights = signal_weights
        self._profile_config = profile_config

    @property
    def dependencies(self) -> PipelineDependencies:
        """The artifacts this engine was built with.

        Read-only, for offline evaluation that needs the same metadata and
        popularity tables the pipeline used. Returning the frozen dataclass
        rather than the artifacts individually keeps the accessor from
        growing one property per family.
        """
        return self._deps

    def with_surfaces(self, overrides: Mapping[str, SurfaceConfig]) -> PipelineRecommendationEngine:
        """The same engine with some surface configurations replaced.

        Artifacts are shared, not reloaded — the point of this is to vary
        quotas and weights over a fixed artifact set, which is how a sweep
        stays a measurement of the configuration rather than of the loader.
        """
        return PipelineRecommendationEngine(
            self._deps,
            surfaces={**self._surfaces, **overrides},
            ranker=self._ranker,
            reranker=self._reranker,
            signal_weights=self._signal_weights,
            profile_config=self._profile_config,
        )

    def recommend(self, request: RecommendationEngineRequest) -> RecommendationEngineResult:
        trace = self.run(request)
        return RecommendationEngineResult(
            model_name=MODEL_NAME,
            model_version=self._deps.resolved_model_version(),
            catalog_version=request.catalog_version,
            generated_at=datetime.now(UTC),
            candidates=tuple(
                self._to_engine_candidate(entry, request, trace.profile) for entry in trace.final
            ),
            diagnostics=self._diagnostics(trace),
        )

    def run(self, request: RecommendationEngineRequest) -> PipelineTrace:
        """Every stage, with the intermediate state each one produced.

        ``recommend`` is this method plus the shaping of its last stage into
        the engine contract, which is deliberate: rec-spec §23.3 wants
        candidate-source coverage and diversity reported, and CLAUDE.md
        requires inspection tooling to call the same implementation serving
        uses. A diagnostic that re-ran the generators itself would drift
        from the served path on the first surface-config change, and would
        report the drift as a finding.

        The trace holds ranked candidates and their features. It is a
        development and offline-evaluation object, not a response payload —
        rec-spec §17 warns against letting diagnostics become a dump, and
        what reaches persistence is the compact per-candidate provenance in
        ``_candidate_diagnostics``.
        """
        surface_context = request.surface_context
        surface = self._surfaces.get(surface_context.surface, self._surfaces["home"])

        timer = _StageTimer()
        with timer.stage("profile"):
            profile = self._build_profile(request.user_context)
        exclusions = self._exclusions(request)

        with timer.stage("generate"):
            results = self._run_generators(request, surface, exclusions, profile)
        with timer.stage("fuse"):
            fused = fuse(results, surface=surface)

        with timer.stage("rank"):
            ranked = self._ranker.rank(
                fused,
                context=self._ranking_context(request, surface, profile),
            )
        with timer.stage("rerank"):
            final = self._reranker.rerank(
                ranked,
                context=RerankContext(
                    surface=surface,
                    embeddings=self._deps.embeddings,
                    metadata=self._deps.metadata,
                    reference_book_ids=self._reference_books(surface_context),
                ),
                limit=request.requested_count,
            )

        return PipelineTrace(
            surface=surface,
            profile=profile,
            exclusions=exclusions,
            generator_results=tuple(results),
            fused=tuple(fused),
            ranked=tuple(ranked),
            final=tuple(final),
            stage_ms=timer.as_dict(),
        )

    # --- stages -----------------------------------------------------------

    def _build_profile(self, context: UserContext) -> SemanticProfile | None:
        """``None`` when there is no content artifact — not an empty profile.

        The distinction matters downstream: an empty profile means "this
        reader has no semantic interests", while no artifact means "we
        cannot tell", and the semantic generator reports those as
        NO_EVIDENCE and NO_ARTIFACT respectively (ADR-0023).
        """
        embeddings = self._deps.embeddings
        if embeddings is None:
            return None
        kwargs: dict[str, Any] = {}
        if self._signal_weights is not None:
            kwargs["weights"] = self._signal_weights
        if self._profile_config is not None:
            kwargs["config"] = self._profile_config
        return build_semantic_profile(context, embeddings, **kwargs)

    @staticmethod
    def _exclusions(request: RecommendationEngineRequest) -> frozenset[int]:
        """Application-owned eligibility, unioned once.

        CLAUDE.md keeps eligibility rules outside the recommender; what the
        engine does is *apply* what the application resolved. The source
        book is added here rather than by the generators, because "do not
        recommend the book being viewed" is a product rule about this
        surface, not a property of any retrieval mechanism.
        """
        exclusions = set(request.hard_exclusions) | set(request.session_exclusions)
        if isinstance(request.surface_context, SimilarBooksContext):
            exclusions.add(request.surface_context.source_book_id)
        return frozenset(exclusions)

    def _run_generators(
        self,
        request: RecommendationEngineRequest,
        surface: SurfaceConfig,
        exclusions: frozenset[int],
        profile: SemanticProfile | None,
    ) -> list[GeneratorResult]:
        """Run every generator the surface enables, isolating failures.

        rec-spec §16: "A non-essential generator failure should not
        necessarily destroy the whole pipeline if enough other sources and
        popularity fallback remain available." A raising generator becomes a
        FAILED result and the batch continues; the alternative is that one
        corrupt artifact takes down every surface.
        """
        combined = self._combined_profile(profile)
        results: list[GeneratorResult] = []
        for generator in self._deps.generators:
            quota = surface.quota_for(generator.generator_id.value)
            if quota is None:
                continue
            generator_request = GeneratorRequest(
                user_context=request.user_context,
                surface_context=request.surface_context,
                count=quota.count,
                excluded_book_ids=exclusions,
                semantic_profile=combined,
            )
            try:
                results.append(generator.generate(generator_request))
            except Exception as exc:  # noqa: BLE001 - deliberate isolation
                results.append(
                    GeneratorResult(
                        generator=generator.generator_id,
                        status=GeneratorStatus.FAILED,
                        diagnostics={"error": type(exc).__name__},
                    )
                )
        return results

    @staticmethod
    def _combined_profile(profile: SemanticProfile | None) -> InterestProfile | None:
        return None if profile is None else profile.combined()

    def _ranking_context(
        self,
        request: RecommendationEngineRequest,
        surface: SurfaceConfig,
        profile: SemanticProfile | None,
    ) -> RankingContext:
        context = request.user_context
        return RankingContext(
            surface=surface,
            embeddings=self._deps.embeddings,
            metadata=self._deps.metadata,
            popularity=self._deps.popularity,
            query_vectors=self._query_vectors(request.surface_context, profile),
            evidence_book_ids=tuple(
                rating.book_id
                for rating in context.ratings
                if rating.rating_value >= _STRONG_RATING_MIN
            )
            + tuple(seed.book_id for seed in context.taste_seeds),
            # rec-spec §18's "negative semantic similarity / explicit
            # negative evidence": Not Interested, plus books they rated
            # badly. Neither is an exclusion by itself — a low-rated book is
            # already excluded as *known*, but its neighbours are not.
            negative_book_ids=tuple(context.not_interested_book_ids)
            + tuple(
                rating.book_id
                for rating in context.ratings
                if rating.rating_value <= _NEGATIVE_RATING_MAX
            ),
            coherent_genres=self._coherent_genres(request.surface_context),
            coherent_authors=self._coherent_authors(request.surface_context),
        )

    def _query_vectors(
        self, surface_context: SurfaceContext, profile: SemanticProfile | None
    ) -> tuple[npt.NDArray[np.float64], ...]:
        """The profile the surface is ranking *against*.

        Not the same question the generator asked. Retrieval issues one
        query per interest; ranking asks "how relevant is this candidate to
        what this surface is about", which on Similar Books is the source
        book regardless of who retrieved the candidate.
        """
        embeddings = self._deps.embeddings
        if embeddings is None:
            return ()

        if isinstance(surface_context, SimilarBooksContext):
            vector = embeddings.vector_for(surface_context.source_book_id)
            return () if vector is None else (np.asarray(vector, dtype=np.float64),)

        if profile is None:
            return ()

        if isinstance(surface_context, ShelfContext):
            target = str(surface_context.shelf_id)
            return tuple(
                shelf.query_vector for shelf in profile.shelves if shelf.shelf_id == target
            )

        return tuple(cluster.query_vector for cluster in profile.interests.clusters) + tuple(
            shelf.query_vector for shelf in profile.shelves
        )

    def _coherent_genres(self, surface_context: SurfaceContext) -> frozenset[str]:
        metadata = self._deps.metadata
        if metadata is None:
            return frozenset()
        if isinstance(surface_context, SimilarBooksContext):
            row = metadata.get(surface_context.source_book_id)
            return frozenset({row.genre}) if row is not None and row.genre else frozenset()
        if isinstance(surface_context, ShelfContext):
            genres = {
                row.genre
                for book_id in surface_context.shelf_book_ids
                if (row := metadata.get(book_id)) is not None and row.genre
            }
            return frozenset(genres)
        # Home has no single coherent genre — the reader's whole taste is
        # the point — so the feature contributes nothing rather than an
        # arbitrary constant.
        return frozenset()

    def _coherent_authors(self, surface_context: SurfaceContext) -> frozenset[str]:
        metadata = self._deps.metadata
        if metadata is None or not isinstance(surface_context, SimilarBooksContext):
            return frozenset()
        row = metadata.get(surface_context.source_book_id)
        return frozenset({row.author}) if row is not None and row.author else frozenset()

    @staticmethod
    def _reference_books(surface_context: SurfaceContext) -> tuple[int, ...]:
        """Books present but not selectable, for duplicate control.

        On Similar Books this is the source book. Without it the reranker
        has nothing to compare candidates against until it has already
        chosen one, which is how `'Dune *'` reached rank 10 (ADR-0024).
        """
        if isinstance(surface_context, SimilarBooksContext):
            return (surface_context.source_book_id,)
        return ()

    # --- output -----------------------------------------------------------

    def _to_engine_candidate(
        self,
        entry: RerankedCandidate,
        request: RecommendationEngineRequest,
        profile: SemanticProfile | None,
    ) -> EngineCandidate:
        fused = entry.ranked.fused
        sources = tuple(dict.fromkeys(source.generator for source in fused.sources))
        return EngineCandidate(
            book_id=entry.book_id,
            score=entry.score,
            # ADR-0017: `candidate_sources` stays plural through the
            # pipeline and into persistence.
            candidate_sources=sources,
            reason_code=self._reason_for(entry, request),
            reason_context=self._reason_context(entry),
            diagnostics=self._candidate_diagnostics(entry, fused),
        )

    def _reason_for(
        self, entry: RerankedCandidate, request: RecommendationEngineRequest
    ) -> ReasonCode:
        """rec-spec §21: the reason must match evidence that materially
        contributed, not whichever string is convenient.

        Read from the *dominant* contributing source — the one with the
        largest RRF contribution — because that is the one that actually put
        this book in the batch.
        """
        if entry.exploration:
            return ReasonCode.EXPLORATION

        sources = entry.ranked.fused.sources
        if not sources:
            return ReasonCode.POPULAR_WITH_READERS

        dominant = sources[0]
        provenance = dominant.provenance
        surface_context = request.surface_context

        if isinstance(surface_context, SimilarBooksContext):
            # Everything on this surface is derived from the source book:
            # the graph's edges, item-CF's neighbours of it, and semantic's
            # nearest neighbours. Popularity is the one exception.
            if dominant.generator == GeneratorId.POPULARITY.value:
                return ReasonCode.POPULAR_WITH_READERS
            return ReasonCode.SIMILAR_TO_CURRENT_BOOK

        if provenance.startswith((PROVENANCE_TARGET_SHELF, PROVENANCE_SHELF)):
            return ReasonCode.SIMILAR_TO_SHELF
        if isinstance(surface_context, ShelfContext):
            return ReasonCode.SIMILAR_TO_SHELF
        if provenance == PROVENANCE_SOURCE_BOOK:
            return ReasonCode.SIMILAR_TO_CURRENT_BOOK
        if provenance.startswith(PROVENANCE_INTEREST):
            return ReasonCode.SEMANTIC_QUERY_MATCH
        if dominant.generator == GeneratorId.POPULARITY.value:
            return ReasonCode.POPULAR_WITH_READERS

        # ALS and item-CF on Home are driven by the reader's own seed books.
        # Which claim is true depends on what that evidence actually was, so
        # it is read from the context rather than assumed.
        return self._collaborative_reason(request.user_context)

    @staticmethod
    def _collaborative_reason(context: UserContext) -> ReasonCode:
        strong_ratings = sum(
            1 for rating in context.ratings if rating.rating_value >= _STRONG_RATING_MIN
        )
        if strong_ratings and strong_ratings >= len(context.saved_books):
            return ReasonCode.BASED_ON_HIGH_RATINGS
        if context.saved_books:
            return ReasonCode.SIMILAR_TO_SAVED_BOOKS
        if strong_ratings:
            return ReasonCode.BASED_ON_HIGH_RATINGS
        # Seeded but unrated and unshelved — a taste-seed-only reader
        # (ADR-0019). None of the "because you saved/rated" claims is true.
        return ReasonCode.SEMANTIC_QUERY_MATCH

    @staticmethod
    def _reason_context(entry: RerankedCandidate) -> dict[str, Any]:
        """Small, structured and free of user data (CLAUDE.md).

        Enough for the API to render honest prose and for a developer to
        audit the reason, without becoming the diagnostics dump the spec
        warns about.
        """
        sources = entry.ranked.fused.sources
        context: dict[str, Any] = {}
        if sources:
            context["source"] = sources[0].generator
            if sources[0].provenance != sources[0].generator:
                context["via"] = sources[0].provenance
        if len(sources) > 1:
            context["agreeing_sources"] = len(sources)
        return context

    @staticmethod
    def _candidate_diagnostics(entry: RerankedCandidate, fused: FusedCandidate) -> dict[str, Any]:
        """Compact per-candidate provenance (rec-spec §17, ADR-0017).

        Every contributing source with its rank, raw score and RRF
        contribution — which rec-spec §17 requires be preserved — kept small
        enough to sit on all 60 rows of a batch. No vectors, no feature
        dump: the full ranking breakdown stays in memory for development
        rather than being written per row.
        """
        diagnostics: dict[str, Any] = {
            "fusion_score": round(fused.fusion_score, 6),
            "sources": [
                {
                    "generator": source.generator,
                    "rank": source.rank,
                    "score": None if source.raw_score is None else round(source.raw_score, 6),
                    "rrf": round(source.contribution, 6),
                }
                for source in fused.sources
            ],
        }
        if entry.penalty:
            diagnostics["rerank_penalty"] = round(entry.penalty, 4)
            diagnostics["rerank_reasons"] = list(entry.reasons)
        return diagnostics

    def _diagnostics(self, trace: PipelineTrace) -> dict[str, Any]:
        """Batch-level diagnostics. Counts and statuses only — no book
        titles, no user identifiers, no vectors."""
        profile = trace.profile
        return {
            "surface": trace.surface.name,
            # rec-spec §24 wants inference kept "comfortably inside the
            # existing timeout", which is a claim about production rather
            # than about a profiling script. Five `perf_counter` reads per
            # request is the cheapest way to make it checkable on a real
            # worker under real load (risk #125).
            "stage_ms": dict(trace.stage_ms),
            "generators": {
                result.generator.value: {
                    "status": str(result.status),
                    "candidates": len(result.candidates),
                }
                for result in trace.generator_results
            },
            "fused_candidates": len(trace.fused),
            "multi_source_candidates": sum(1 for c in trace.fused if c.agreement > 1),
            "profile_strategy": ("absent" if profile is None else str(profile.interests.strategy)),
            "interests": 0 if profile is None else len(profile.interests.clusters),
            "shelf_profiles": 0 if profile is None else len(profile.shelves),
            # The versions the digest in `model_version` stands for.
            "artifact_versions": dict(self._deps.artifact_versions),
        }
