"""The assembled pipeline engine (rec-spec §16-§21, R8).

The engine is where the phases meet, so these tests are about the seams:
that the surface config actually reaches the generators, that reasons match
the evidence that produced a candidate, that provenance survives into the
result the service persists, and that every degradation in rec-spec §27
still returns books.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from book_recommender.artifacts import LocalArtifactStorage
from book_recommender.contracts.context import (
    HomeContext,
    ShelfContext,
    SimilarBooksContext,
    SurfaceContext,
)
from book_recommender.contracts.engine import RecommendationEngineRequest
from book_recommender.contracts.reasons import ReasonCode
from book_recommender.engines.pipeline import (
    MODEL_NAME,
    PipelineDependencies,
    PipelineRecommendationEngine,
)
from book_recommender.generators import (
    AlsCandidateGenerator,
    CandidateGenerator,
    GeneratorId,
    GeneratorRequest,
    GeneratorResult,
    ItemItemCFCandidateGenerator,
    PopularityCandidateGenerator,
    SemanticCandidateGenerator,
    SourceSimilarityCandidateGenerator,
)
from generator_world import (
    CATALOG,
    FANTASY,
    ROMANCE,
    SHELF_FANTASY,
    SHELF_SCIFI,
    build_all,
    load_als,
    load_content,
    load_item_cf,
    load_metadata,
    load_popularity,
    load_source_graph,
    user_context,
)


@pytest.fixture
def storage(tmp_path: Path) -> LocalArtifactStorage:
    return build_all(tmp_path)


def dependencies(storage: LocalArtifactStorage, **drop: bool) -> PipelineDependencies:
    """Full dependencies, with any family droppable by keyword to exercise
    rec-spec §27's degradation paths."""
    content = None if drop.get("content") else load_content(storage)
    metadata = None if drop.get("metadata") else load_metadata(storage)
    als = None if drop.get("als") else load_als(storage)
    item_cf = None if drop.get("item_cf") else load_item_cf(storage)
    graph = None if drop.get("graph") else load_source_graph(storage)
    popularity = None if drop.get("popularity") else load_popularity(storage)

    generators: tuple[CandidateGenerator, ...] = (
        AlsCandidateGenerator(als),
        ItemItemCFCandidateGenerator(item_cf),
        SemanticCandidateGenerator(content),
        SourceSimilarityCandidateGenerator(graph),
        PopularityCandidateGenerator(None if popularity is None else popularity.ranking),
    )
    return PipelineDependencies(
        generators=generators,
        embeddings=content,
        metadata=metadata,
        popularity=None if popularity is None else dict(popularity.ranking),
        artifact_versions={
            name: "20260813T120000Z"
            for name, artifact in (
                ("content", content),
                ("item_metadata", metadata),
                ("als", als),
                ("item_cf", item_cf),
                ("source_similarity", graph),
                ("popularity", popularity),
            )
            if artifact is not None
        },
    )


def engine(storage: LocalArtifactStorage, **drop: bool) -> PipelineRecommendationEngine:
    return PipelineRecommendationEngine(dependencies(storage, **drop))


def request(
    *,
    surface: SurfaceContext | None = None,
    count: int = 8,
    ratings: list[tuple[int, int]] | None = None,
    saved: list[tuple[int, object]] | None = None,
    taste_seeds: list[int] | None = None,
    not_interested: list[int] | None = None,
    hard_exclusions: frozenset[int] = frozenset(),
    session_exclusions: frozenset[int] = frozenset(),
) -> RecommendationEngineRequest:
    return RecommendationEngineRequest(
        request_id=uuid4(),
        user_context=user_context(
            ratings=ratings or [],
            saved=saved or [],  # type: ignore[arg-type]
            taste_seeds=taste_seeds or [],
            not_interested=not_interested or [],
        ),
        surface_context=surface or HomeContext(),
        requested_count=count,
        hard_exclusions=hard_exclusions,
        session_exclusions=session_exclusions,
        catalog_version=CATALOG.catalog_version,
    )


FANTASY_READER = {"ratings": [(101, 10), (102, 9)], "saved": [(103, SHELF_FANTASY)]}


class TestContract:
    def test_returns_a_well_formed_result(self, storage: LocalArtifactStorage) -> None:
        result = engine(storage).recommend(request(**FANTASY_READER))  # type: ignore[arg-type]
        assert result.model_name == MODEL_NAME
        # A digest over every contributing artifact version, not any one
        # artifact's — six artifacts build a batch and no single timestamp
        # describes it.
        assert result.model_version.startswith("pipeline-")
        assert result.diagnostics["artifact_versions"]
        assert result.catalog_version == CATALOG.catalog_version
        assert result.candidates

    def test_respects_the_requested_count(self, storage: LocalArtifactStorage) -> None:
        result = engine(storage).recommend(request(count=3, **FANTASY_READER))  # type: ignore[arg-type]
        assert len(result.candidates) <= 3

    def test_never_returns_a_book_twice(self, storage: LocalArtifactStorage) -> None:
        result = engine(storage).recommend(request(count=12, **FANTASY_READER))  # type: ignore[arg-type]
        ids = [c.book_id for c in result.candidates]
        assert len(ids) == len(set(ids))

    def test_honours_hard_and_session_exclusions(self, storage: LocalArtifactStorage) -> None:
        """Application-owned eligibility (CLAUDE.md) — the engine applies
        what the application resolved, both kinds, without distinguishing
        them."""
        excluded = frozenset({104, 105})
        session = frozenset({109})
        result = engine(storage).recommend(
            request(
                count=12,
                hard_exclusions=excluded,
                session_exclusions=session,
                **FANTASY_READER,  # type: ignore[arg-type]
            )
        )
        ids = {c.book_id for c in result.candidates}
        assert not (ids & (excluded | session))

    def test_the_source_book_is_never_recommended_on_similar(
        self, storage: LocalArtifactStorage
    ) -> None:
        """A product rule about the surface, not a property of any
        retrieval mechanism — so the engine applies it, not the generators."""
        result = engine(storage).recommend(
            request(surface=SimilarBooksContext(source_book_id=101), count=12)
        )
        assert 101 not in {c.book_id for c in result.candidates}

    def test_is_deterministic(self, storage: LocalArtifactStorage) -> None:
        """ADR-0006/0007: this order is persisted and replayed by cursor
        pages, so a non-deterministic engine makes a batch unreproducible."""
        pipeline = engine(storage)
        payload = request(count=10, **FANTASY_READER)  # type: ignore[arg-type]
        first = pipeline.recommend(payload)
        second = pipeline.recommend(payload)
        assert [c.book_id for c in first.candidates] == [c.book_id for c in second.candidates]
        assert [c.score for c in first.candidates] == [c.score for c in second.candidates]


class TestSurfacesDiffer:
    def test_a_fantasy_reader_gets_fantasy_on_home(self, storage: LocalArtifactStorage) -> None:
        result = engine(storage).recommend(request(count=4, **FANTASY_READER))  # type: ignore[arg-type]
        assert 104 in {c.book_id for c in result.candidates}

    def test_shelf_follows_the_target_shelf_not_the_global_profile(
        self, storage: LocalArtifactStorage
    ) -> None:
        """rec-spec §20.2. The reader's taste is romance; the shelf is
        sci-fi. The shelf must win, or shelf discovery is Home with extra
        steps."""
        result = engine(storage).recommend(
            request(
                surface=ShelfContext(
                    shelf_id=SHELF_SCIFI,
                    shelf_name="Sci-fi",
                    shelf_description=None,
                    shelf_book_ids=frozenset({105, 106}),
                ),
                count=2,
                ratings=[(109, 10), (110, 10)],
            )
        )
        # Only 107 and 108 remain in the sci-fi group once the shelf's own
        # books are excluded, so a request for two must be exactly those.
        assert {c.book_id for c in result.candidates} == {107, 108}

    def test_similar_follows_the_source_book(self, storage: LocalArtifactStorage) -> None:
        result = engine(storage).recommend(
            request(
                surface=SimilarBooksContext(source_book_id=109),
                count=3,
                ratings=[(101, 10)],  # global taste is fantasy
            )
        )
        assert {c.book_id for c in result.candidates} <= set(ROMANCE)

    def test_als_is_absent_from_similar(self, storage: LocalArtifactStorage) -> None:
        """rec-spec §20.3: no global personalization on this surface."""
        result = engine(storage).recommend(
            request(surface=SimilarBooksContext(source_book_id=101), **FANTASY_READER)  # type: ignore[arg-type]
        )
        assert GeneratorId.ALS.value not in result.diagnostics["generators"]


class TestReasonsAreTrue:
    def test_popularity_only_candidates_say_popular(self, storage: LocalArtifactStorage) -> None:
        """rec-spec §21: "Popular with readers" only for genuine popularity
        provenance. With no artifacts but popularity, that is all there is."""
        result = engine(storage, content=True, als=True, item_cf=True, graph=True).recommend(
            request(count=5)
        )
        assert result.candidates
        assert all(c.reason_code is ReasonCode.POPULAR_WITH_READERS for c in result.candidates)

    def test_similar_books_candidates_say_similar_to_this_book(
        self, storage: LocalArtifactStorage
    ) -> None:
        result = engine(storage, popularity=True).recommend(
            request(surface=SimilarBooksContext(source_book_id=109), count=3)
        )
        assert result.candidates
        assert all(c.reason_code is ReasonCode.SIMILAR_TO_CURRENT_BOOK for c in result.candidates)

    def test_shelf_candidates_say_similar_to_shelf(self, storage: LocalArtifactStorage) -> None:
        result = engine(storage, popularity=True).recommend(
            request(
                surface=ShelfContext(
                    shelf_id=SHELF_SCIFI,
                    shelf_name="Sci-fi",
                    shelf_description=None,
                    shelf_book_ids=frozenset({105, 106}),
                ),
                count=2,
                saved=[(105, SHELF_SCIFI), (106, SHELF_SCIFI)],
            )
        )
        assert result.candidates
        assert all(c.reason_code is ReasonCode.SIMILAR_TO_SHELF for c in result.candidates)

    def test_a_rating_led_reader_is_told_it_was_their_ratings(
        self, storage: LocalArtifactStorage
    ) -> None:
        """The claim has to match the evidence: this reader has ratings and
        no shelves, so "because you saved" would be false.

        EXPLORATION is admissible alongside it — Home reserves slots for
        candidates outside the reader's represented interests, and
        "something new" is its own honest claim (rec-spec §15).
        """
        result = engine(storage, content=True, popularity=True).recommend(
            request(count=6, ratings=[(101, 10), (102, 9)])
        )
        assert result.candidates
        reasons = {c.reason_code for c in result.candidates}
        assert ReasonCode.BASED_ON_HIGH_RATINGS in reasons
        assert reasons <= {ReasonCode.BASED_ON_HIGH_RATINGS, ReasonCode.EXPLORATION}

    def test_a_shelf_led_reader_is_told_it_was_their_shelves(
        self, storage: LocalArtifactStorage
    ) -> None:
        result = engine(storage, content=True, popularity=True).recommend(
            request(
                count=4,
                saved=[(101, SHELF_FANTASY), (102, SHELF_FANTASY), (103, SHELF_FANTASY)],
            )
        )
        assert result.candidates
        reasons = {c.reason_code for c in result.candidates}
        assert ReasonCode.SIMILAR_TO_SAVED_BOOKS in reasons
        assert reasons <= {ReasonCode.SIMILAR_TO_SAVED_BOOKS, ReasonCode.EXPLORATION}

    def test_a_seed_only_reader_is_not_told_they_rated_or_saved_anything(
        self, storage: LocalArtifactStorage
    ) -> None:
        """ADR-0019: taste seeds are not fake ratings and not fake shelf
        saves. Claiming either to a reader who has done neither is exactly
        the untruthful reason rec-spec §21 forbids."""
        result = engine(storage, content=True, popularity=True).recommend(
            request(count=4, taste_seeds=[101, 102])
        )
        assert result.candidates
        reasons = {c.reason_code for c in result.candidates}
        assert ReasonCode.BASED_ON_HIGH_RATINGS not in reasons
        assert ReasonCode.SIMILAR_TO_SAVED_BOOKS not in reasons


class TestProvenance:
    def test_candidate_sources_stay_plural(self, storage: LocalArtifactStorage) -> None:
        """ADR-0017: `candidate_sources` stays plural through the pipeline
        and into persistence."""
        result = engine(storage).recommend(request(count=12, **FANTASY_READER))  # type: ignore[arg-type]
        assert any(len(c.candidate_sources) > 1 for c in result.candidates)
        for candidate in result.candidates:
            assert candidate.candidate_sources
            assert len(set(candidate.candidate_sources)) == len(candidate.candidate_sources)

    def test_per_source_rank_score_and_contribution_are_preserved(
        self, storage: LocalArtifactStorage
    ) -> None:
        """rec-spec §17's four required fields per contributing source."""
        result = engine(storage).recommend(request(count=6, **FANTASY_READER))  # type: ignore[arg-type]
        sources = result.candidates[0].diagnostics["sources"]
        assert sources
        for source in sources:
            assert set(source) == {"generator", "rank", "score", "rrf"}
            assert source["rank"] >= 1

    def test_diagnostics_carry_no_vectors_or_user_data(self, storage: LocalArtifactStorage) -> None:
        """CLAUDE.md: diagnostics must not become an accidental
        sensitive-data dump."""
        result = engine(storage).recommend(request(count=6, **FANTASY_READER))  # type: ignore[arg-type]
        payload = repr(result.diagnostics) + repr([c.diagnostics for c in result.candidates])
        assert "array" not in payload
        assert "ndarray" not in payload
        # No user identity, and no catalog prose that would make this a
        # place personal reading history could leak from.
        user_id = str(request(**FANTASY_READER).user_context.user_id)  # type: ignore[arg-type]
        assert user_id not in payload
        assert "title" not in payload

    def test_batch_diagnostics_report_every_generator_status(
        self, storage: LocalArtifactStorage
    ) -> None:
        result = engine(storage, als=True).recommend(request(count=6, **FANTASY_READER))  # type: ignore[arg-type]
        generators = result.diagnostics["generators"]
        assert generators[GeneratorId.ALS.value]["status"] == "no_artifact"
        assert generators[GeneratorId.SEMANTIC.value]["status"] == "ok"


class TestDegradation:
    @pytest.mark.parametrize(
        "missing", ["content", "als", "item_cf", "graph", "metadata", "popularity"]
    )
    def test_any_single_missing_artifact_still_produces_a_batch(
        self, storage: LocalArtifactStorage, missing: str
    ) -> None:
        """rec-spec §27, one family at a time."""
        result = engine(storage, **{missing: True}).recommend(
            request(count=5, **FANTASY_READER)  # type: ignore[arg-type]
        )
        assert result.candidates

    def test_with_no_artifacts_at_all_the_engine_still_answers(
        self, storage: LocalArtifactStorage
    ) -> None:
        """Empty, but not an exception — the provider's own popularity
        fallback is what covers this, and it can only do so if the engine
        returns rather than raises."""
        result = engine(
            storage,
            content=True,
            als=True,
            item_cf=True,
            graph=True,
            metadata=True,
            popularity=True,
        ).recommend(request(count=5, **FANTASY_READER))  # type: ignore[arg-type]
        assert result.candidates == ()
        assert result.diagnostics["fused_candidates"] == 0

    def test_a_reader_with_no_evidence_still_gets_books(
        self, storage: LocalArtifactStorage
    ) -> None:
        """Cold start. Popularity is the only generator that can speak for
        a reader who has done nothing."""
        result = engine(storage).recommend(request(count=5))
        assert len(result.candidates) == 5
        assert result.diagnostics["profile_strategy"] == "none"

    def test_a_raising_generator_is_isolated(self, storage: LocalArtifactStorage) -> None:
        """rec-spec §16: "A non-essential generator failure should not
        necessarily destroy the whole pipeline." One corrupt artifact must
        not take down every surface."""

        class Exploding:
            @property
            def generator_id(self) -> GeneratorId:
                return GeneratorId.ALS

            def generate(self, request: GeneratorRequest) -> GeneratorResult:
                raise RuntimeError("boom")

        deps = dependencies(storage)
        broken = PipelineDependencies(
            generators=(Exploding(),)
            + tuple(g for g in deps.generators if g.generator_id is not GeneratorId.ALS),
            embeddings=deps.embeddings,
            metadata=deps.metadata,
            popularity=deps.popularity,
        )
        result = PipelineRecommendationEngine(broken).recommend(
            request(count=5, **FANTASY_READER)  # type: ignore[arg-type]
        )
        assert result.candidates
        assert result.diagnostics["generators"][GeneratorId.ALS.value]["status"] == "failed"

    def test_not_interested_books_never_appear(self, storage: LocalArtifactStorage) -> None:
        """rec-spec §7.1's hard exclusion. The application resolves it into
        `hard_exclusions`; this checks the engine honours it end to end."""
        result = engine(storage).recommend(
            request(
                count=12,
                ratings=[(101, 10)],
                not_interested=[104],
                hard_exclusions=frozenset({104}),
            )
        )
        assert 104 not in {c.book_id for c in result.candidates}


def test_fantasy_group_is_what_the_fixture_says() -> None:
    assert set(FANTASY) == {101, 102, 103, 104}


class TestModelVersion:
    def test_is_stable_and_order_independent(self) -> None:
        left = PipelineDependencies(generators=(), artifact_versions={"als": "a", "content": "b"})
        right = PipelineDependencies(generators=(), artifact_versions={"content": "b", "als": "a"})
        assert left.resolved_model_version() == right.resolved_model_version()

    def test_changes_when_any_artifact_is_rebuilt(self) -> None:
        """The point of the digest: a rebuilt artifact must be visible in
        the persisted batch, or two incomparable batches look identical."""
        before = PipelineDependencies(
            generators=(), artifact_versions={"als": "a", "content": "b"}
        ).resolved_model_version()
        after = PipelineDependencies(
            generators=(), artifact_versions={"als": "a", "content": "c"}
        ).resolved_model_version()
        assert before != after

    def test_reports_unknown_when_nothing_loaded(self) -> None:
        assert PipelineDependencies(generators=()).resolved_model_version() == "unknown"
