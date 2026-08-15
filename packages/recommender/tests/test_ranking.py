"""The deterministic V1 ranker (rec-spec §18, ADR-0017)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from book_recommender.artifacts import LocalArtifactStorage
from book_recommender.config import (
    HOME_SURFACE,
    SHELF_SURFACE,
    SIMILAR_SURFACE,
    GeneratorQuota,
    RankingWeights,
    RerankConfig,
    SurfaceConfig,
)
from book_recommender.generators import Candidate, GeneratorId, GeneratorResult
from book_recommender.pipeline import DeterministicRanker, RankingContext, fuse
from generator_world import (
    FANTASY,
    ROMANCE,
    build_all,
    load_content,
    load_item_cf,
    load_metadata,
    load_popularity,
)


@pytest.fixture
def storage(tmp_path: Path) -> LocalArtifactStorage:
    return build_all(tmp_path)


def result(
    generator: GeneratorId, *book_ids: int, provenance: str | None = None
) -> GeneratorResult:
    return GeneratorResult(
        generator=generator,
        candidates=tuple(
            Candidate(
                book_id=book_id,
                generator=generator,
                rank=index + 1,
                score=1.0 - 0.1 * index,
                provenance=provenance or generator.value,
            )
            for index, book_id in enumerate(book_ids)
        ),
    )


def only(feature: str, weight: float = 1.0) -> SurfaceConfig:
    """A surface that scores exactly one feature, so a test can attribute
    an ordering to that feature rather than to the sum of eight."""
    zeros = {
        "fusion": 0.0,
        "agreement": 0.0,
        "semantic_relevance": 0.0,
        "collaborative_relevance": 0.0,
        "popularity_prior": 0.0,
        "evidence_affinity": 0.0,
        "surface_coherence": 0.0,
        "negative_evidence": 0.0,
    }
    zeros[feature] = weight
    return SurfaceConfig(
        name="test",
        quotas=(
            GeneratorQuota(generator="als", rrf_weight=1.0, count=10),
            GeneratorQuota(generator="item_cf", rrf_weight=1.0, count=10),
            GeneratorQuota(generator="semantic", rrf_weight=1.0, count=10),
            GeneratorQuota(generator="popularity", rrf_weight=1.0, count=10),
        ),
        ranking=RankingWeights(**zeros),
        rerank=RerankConfig(),
    )


def axis(index: int) -> np.ndarray:
    vector = np.zeros(8)
    vector[index] = 1.0
    return vector


class TestWeightPolicy:
    @pytest.mark.parametrize("config", [HOME_SURFACE, SHELF_SURFACE, SIMILAR_SURFACE])
    def test_popularity_is_never_the_dominant_feature(self, config: SurfaceConfig) -> None:
        """rec-spec §18's one hard prohibition: "Do not use raw popularity as
        the dominant personalization score." Asserted rather than inspected,
        because it is the sort of thing a tuning pass erodes by accident."""
        weights = config.ranking
        personalization = max(
            weights.fusion,
            weights.semantic_relevance,
            weights.collaborative_relevance,
            weights.evidence_affinity,
        )
        assert weights.popularity_prior < personalization

    @pytest.mark.parametrize("config", [HOME_SURFACE, SHELF_SURFACE, SIMILAR_SURFACE])
    def test_negative_evidence_can_outweigh_the_popularity_prior(
        self, config: SurfaceConfig
    ) -> None:
        """A book resembling something the reader rejected must not be
        rescued by being popular."""
        assert config.ranking.negative_evidence > config.ranking.popularity_prior


class TestFeatures:
    def test_agreement_orders_candidates_when_nothing_else_does(
        self, storage: LocalArtifactStorage
    ) -> None:
        fused = fuse(
            [
                result(GeneratorId.ALS, 101),
                result(GeneratorId.ITEM_CF, 101),
                result(GeneratorId.SEMANTIC, 102),
            ],
            surface=only("agreement"),
        )
        ranked = DeterministicRanker().rank(
            fused, context=RankingContext(surface=only("agreement"))
        )
        assert ranked[0].book_id == 101
        assert ranked[0].features["agreement"] > ranked[1].features["agreement"]

    def test_semantic_relevance_takes_the_best_interest_not_the_mean(
        self, storage: LocalArtifactStorage
    ) -> None:
        """A book strongly matching one of four interests is a good
        recommendation. Averaging across queries would punish it for being
        unrelated to the other three — which is how multi-interest profiling
        gets quietly undone at the ranking stage.
        """
        config = only("semantic_relevance")
        fused = fuse([result(GeneratorId.SEMANTIC, 101, 109)], surface=config)
        context = RankingContext(
            surface=config,
            embeddings=load_content(storage),
            # Two interests: fantasy (axis 0) and romance (axis 2).
            query_vectors=(axis(0), axis(2)),
        )
        ranked = DeterministicRanker().rank(fused, context=context)
        # Each book matches its own group's query at ~0.86 (the fixture's
        # within-group ceiling), so both score high on their best query.
        assert all(candidate.features["semantic_relevance"] > 0.8 for candidate in ranked)

    def test_negative_evidence_is_subtracted(self, storage: LocalArtifactStorage) -> None:
        """rec-spec §18's "negative semantic similarity / explicit negative
        evidence". A book resembling what the reader rejected must fall."""
        config = only("negative_evidence")
        fused = fuse([result(GeneratorId.SEMANTIC, 101, 109)], surface=config)
        context = RankingContext(
            surface=config,
            embeddings=load_content(storage),
            negative_book_ids=(102,),  # a fantasy book they said no to
        )
        ranked = DeterministicRanker().rank(fused, context=context)
        assert ranked[0].book_id == 109  # romance survives
        assert ranked[-1].book_id == 101  # fantasy, like the rejected book
        assert ranked[-1].score < 0

    def test_evidence_affinity_rewards_resemblance_to_strong_positives(
        self, storage: LocalArtifactStorage
    ) -> None:
        config = only("evidence_affinity")
        fused = fuse([result(GeneratorId.SEMANTIC, 101, 109)], surface=config)
        context = RankingContext(
            surface=config,
            embeddings=load_content(storage),
            evidence_book_ids=(110,),  # a romance book they loved
        )
        ranked = DeterministicRanker().rank(fused, context=context)
        assert ranked[0].book_id == 109

    def test_collaborative_relevance_comes_from_rank_not_score(
        self, storage: LocalArtifactStorage
    ) -> None:
        """An ALS dot product and an item-CF similarity are not comparable,
        but "third of a hundred and fiftieth" means the same in both."""
        config = only("collaborative_relevance")
        fused = fuse([result(GeneratorId.ALS, 101, 102, 103)], surface=config)
        ranked = DeterministicRanker().rank(fused, context=RankingContext(surface=config))
        values = [candidate.features["collaborative_relevance"] for candidate in ranked]
        assert values == sorted(values, reverse=True)
        assert ranked[0].book_id == 101

    def test_semantic_only_candidates_have_no_collaborative_relevance(
        self, storage: LocalArtifactStorage
    ) -> None:
        config = only("collaborative_relevance")
        fused = fuse([result(GeneratorId.SEMANTIC, 101)], surface=config)
        ranked = DeterministicRanker().rank(fused, context=RankingContext(surface=config))
        assert ranked[0].features["collaborative_relevance"] == 0.0

    def test_surface_coherence_reads_genre_and_author(self, storage: LocalArtifactStorage) -> None:
        """rec-spec §14 forbids mixing same-author/genre into the source
        similarity *generator*, and explicitly allows them as ranking
        features. This is where they belong.

        101 matches both the coherent genre and the coherent author, 103
        the genre only (Beta Author), 109 neither.
        """
        config = only("surface_coherence")
        fused = fuse([result(GeneratorId.SEMANTIC, 101, 103, 109)], surface=config)
        context = RankingContext(
            surface=config,
            metadata=load_metadata(storage),
            coherent_genres=frozenset({"fantasy"}),
            coherent_authors=frozenset({"Alpha Author"}),
        )
        ranked = DeterministicRanker().rank(fused, context=context)
        scores = {c.book_id: c.features["surface_coherence"] for c in ranked}
        assert scores == {101: 1.0, 103: 0.5, 109: 0.0}
        assert ranked[0].book_id == 101

    def test_coherence_is_zero_when_the_surface_declares_none(
        self, storage: LocalArtifactStorage
    ) -> None:
        """Home has no single coherent genre or author — the reader's whole
        taste is the point — so the feature must contribute nothing rather
        than an arbitrary constant."""
        config = only("surface_coherence")
        fused = fuse([result(GeneratorId.SEMANTIC, 101)], surface=config)
        context = RankingContext(surface=config, metadata=load_metadata(storage))
        ranked = DeterministicRanker().rank(fused, context=context)
        assert ranked[0].features["surface_coherence"] == 0.0

    def test_popularity_is_normalized_within_the_candidate_set(
        self, storage: LocalArtifactStorage
    ) -> None:
        """Normalizing against the whole catalog would make this feature
        nearly constant — every retrieved candidate is already far above the
        catalog median — and a constant feature cannot break a tie, which is
        the only job rec-spec §18 leaves it."""
        config = only("popularity_prior")
        ranking = dict(load_popularity(storage).ranking)
        fused = fuse([result(GeneratorId.POPULARITY, 112, 101)], surface=config)
        context = RankingContext(surface=config, popularity=ranking)
        ranked = DeterministicRanker().rank(fused, context=context)
        values = sorted(c.features["popularity_prior"] for c in ranked)
        assert values == [0.0, 1.0]
        assert ranked[0].book_id == 101  # the fixture's most popular


class TestDegradationAndDeterminism:
    def test_missing_artifacts_cost_features_not_the_request(self) -> None:
        """rec-spec §27: a missing content artifact removes the semantic
        features and leaves the rest working."""
        config = HOME_SURFACE
        fused = fuse([result(GeneratorId.ALS, 101, 102)], surface=config)
        ranked = DeterministicRanker().rank(fused, context=RankingContext(surface=config))
        assert len(ranked) == 2
        assert all(c.features["semantic_relevance"] == 0.0 for c in ranked)
        assert all(c.features["popularity_prior"] == 0.0 for c in ranked)

    def test_a_book_with_no_embedding_scores_zero_not_an_error(
        self, storage: LocalArtifactStorage
    ) -> None:
        """Risk #108: books added since the last content build."""
        config = only("semantic_relevance")
        fused = fuse([result(GeneratorId.SEMANTIC, 9999, 101)], surface=config)
        context = RankingContext(
            surface=config, embeddings=load_content(storage), query_vectors=(axis(0),)
        )
        ranked = DeterministicRanker().rank(fused, context=context)
        unembedded = next(c for c in ranked if c.book_id == 9999)
        assert unembedded.features["semantic_relevance"] == 0.0

    def test_output_is_identical_across_runs(self, storage: LocalArtifactStorage) -> None:
        """ADR-0017: final order must be deterministic for a fixed request,
        profile, artifact set and configuration, or the persisted batch is
        unreproducible and every offline evaluation unstable."""
        fused = fuse(
            [result(GeneratorId.ALS, *FANTASY), result(GeneratorId.SEMANTIC, *ROMANCE)],
            surface=HOME_SURFACE,
        )
        context = RankingContext(
            surface=HOME_SURFACE,
            embeddings=load_content(storage),
            query_vectors=(axis(0),),
            popularity=dict(load_popularity(storage).ranking),
        )
        ranker = DeterministicRanker()
        assert ranker.rank(fused, context=context) == ranker.rank(fused, context=context)

    def test_features_are_inspectable(self, storage: LocalArtifactStorage) -> None:
        (
            """rec-spec §18: "Keep the scoring breakdown inspectable in
        diagnostics for development/evaluation."""
            ""
        )
        fused = fuse([result(GeneratorId.ALS, 101)], surface=HOME_SURFACE)
        ranked = DeterministicRanker().rank(fused, context=RankingContext(surface=HOME_SURFACE))
        assert set(ranked[0].features) == {
            "fusion",
            "agreement",
            "semantic_relevance",
            "collaborative_relevance",
            "popularity_prior",
            "evidence_affinity",
            "surface_coherence",
            "negative_evidence",
        }

    def test_diagnostics_carry_no_vectors(self, storage: LocalArtifactStorage) -> None:
        fused = fuse([result(GeneratorId.SEMANTIC, 101)], surface=HOME_SURFACE)
        context = RankingContext(
            surface=HOME_SURFACE, embeddings=load_content(storage), query_vectors=(axis(0),)
        )
        ranked = DeterministicRanker().rank(fused, context=context)
        payload = repr(ranked[0].features)
        assert "array" not in payload and "ndarray" not in payload

    def test_empty_input_is_not_an_error(self) -> None:
        assert DeterministicRanker().rank([], context=RankingContext(surface=HOME_SURFACE)) == ()

    def test_item_cf_artifact_is_available_to_the_fixture(
        self, storage: LocalArtifactStorage
    ) -> None:
        assert load_item_cf(storage).item_count == 12
