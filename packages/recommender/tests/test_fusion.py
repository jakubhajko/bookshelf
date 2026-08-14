"""Weighted RRF fusion (rec-spec §17, ADR-0017).

The arithmetic is small enough to check exactly, which is worth doing: every
downstream weight is expressed relative to it, so an off-by-one in the rank
convention would be invisible in the output and wrong everywhere.
"""

from __future__ import annotations

import pytest

from book_recommender.config import (
    HOME_SURFACE,
    SIMILAR_SURFACE,
    GeneratorQuota,
    RankingWeights,
    RerankConfig,
    SurfaceConfig,
)
from book_recommender.generators import Candidate, GeneratorId, GeneratorResult
from book_recommender.pipeline import fuse, rrf_contribution


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


def surface(**weights: float) -> SurfaceConfig:
    """A surface whose only interesting property is its RRF weights."""
    return SurfaceConfig(
        name="test",
        quotas=tuple(
            GeneratorQuota(generator=name, rrf_weight=weight, count=50)
            for name, weight in weights.items()
        ),
        ranking=RankingWeights(),
        rerank=RerankConfig(),
        rrf_k=60,
    )


class TestRrfArithmetic:
    def test_contribution_is_weight_over_k_plus_rank(self) -> None:
        assert rrf_contribution(2.0, 1, rrf_k=60) == pytest.approx(2.0 / 61)
        assert rrf_contribution(2.0, 2, rrf_k=60) == pytest.approx(2.0 / 62)

    def test_ranks_are_one_based(self) -> None:
        """rec-spec §17: "Use 1-based ranks consistently." A 0-based first
        rank would make the top result worth weight/60 instead of weight/61
        — a small error that compounds across every surface weight."""
        fused = fuse([result(GeneratorId.ALS, 11)], surface=surface(als=2.0))
        assert fused[0].fusion_score == pytest.approx(2.0 / 61)

    def test_a_single_source_scores_exactly_its_contribution(self) -> None:
        fused = fuse([result(GeneratorId.ALS, 11, 22)], surface=surface(als=1.0))
        assert [c.book_id for c in fused] == [11, 22]
        assert fused[0].fusion_score == pytest.approx(1.0 / 61)
        assert fused[1].fusion_score == pytest.approx(1.0 / 62)

    def test_contributions_from_several_sources_add(self) -> None:
        fused = fuse(
            [result(GeneratorId.ALS, 11), result(GeneratorId.ITEM_CF, 11)],
            surface=surface(als=2.0, item_cf=1.0),
        )
        assert fused[0].fusion_score == pytest.approx(2.0 / 61 + 1.0 / 61)

    def test_agreement_beats_a_single_strong_rank(self) -> None:
        """The property that makes RRF worth choosing: a book two mechanisms
        agree on outranks a book one mechanism put first."""
        fused = fuse(
            [
                result(GeneratorId.ALS, 11, 22),
                result(GeneratorId.ITEM_CF, 33, 22),
            ],
            surface=surface(als=1.0, item_cf=1.0),
        )
        # 22 is second in both (1/62 + 1/62); 11 is first in one (1/61).
        assert fused[0].book_id == 22
        assert fused[0].agreement == 2


class TestProvenance:
    def test_every_contributing_source_is_preserved(self) -> None:
        """rec-spec §17 requires source, rank, raw score and RRF
        contribution per candidate; ADR-0017 keeps `candidate_sources`
        plural through the pipeline and into persistence."""
        fused = fuse(
            [
                result(GeneratorId.ALS, 11),
                result(GeneratorId.SEMANTIC, 99, 11, provenance="interest:i1"),
            ],
            surface=surface(als=2.0, semantic=2.0),
        )
        candidate = next(c for c in fused if c.book_id == 11)
        assert candidate.agreement == 2
        assert set(candidate.generators) == {"als", "semantic"}

        als = next(s for s in candidate.sources if s.generator == "als")
        semantic = next(s for s in candidate.sources if s.generator == "semantic")
        assert als.rank == 1
        assert semantic.rank == 2
        assert semantic.provenance == "interest:i1"
        assert als.contribution == pytest.approx(2.0 / 61)
        assert semantic.contribution == pytest.approx(2.0 / 62)
        assert candidate.fusion_score == pytest.approx(als.contribution + semantic.contribution)

    def test_sources_are_ordered_by_contribution(self) -> None:
        fused = fuse(
            [result(GeneratorId.ALS, 11), result(GeneratorId.POPULARITY, 11)],
            surface=surface(als=2.0, popularity=0.2),
        )
        assert fused[0].sources[0].generator == "als"

    def test_raw_scores_survive_and_none_is_allowed(self) -> None:
        """The source graph has edge ranks, not weights — `None` is a real
        value here, not a missing one."""
        graph = GeneratorResult(
            generator=GeneratorId.SOURCE_SIMILARITY,
            candidates=(
                Candidate(
                    book_id=11,
                    generator=GeneratorId.SOURCE_SIMILARITY,
                    rank=1,
                    score=None,
                    provenance="source_similarity",
                ),
            ),
        )
        fused = fuse([graph], surface=surface(source_similarity=1.0))
        assert fused[0].sources[0].raw_score is None

    def test_lookup_helpers_report_per_generator_rank_and_score(self) -> None:
        fused = fuse([result(GeneratorId.ALS, 11, 22)], surface=surface(als=1.0, item_cf=1.0))
        candidate = fused[1]
        assert candidate.rank_in("als") == 2
        assert candidate.rank_in("item_cf") is None
        assert candidate.score_in("als") == pytest.approx(0.9)


class TestSurfacePolicy:
    def test_a_generator_absent_from_the_surface_contributes_nothing(self) -> None:
        """The surface decides who participates, never the generator."""
        fused = fuse(
            [result(GeneratorId.ALS, 11), result(GeneratorId.ITEM_CF, 22)],
            surface=surface(als=1.0),
        )
        assert [c.book_id for c in fused] == [11]

    def test_a_disabled_generator_contributes_nothing(self) -> None:
        """rec-spec §20.3: ALS is absent from Similar Books. The generator
        already reports NOT_APPLICABLE; the surface must not count it even
        if something hands fusion a populated result."""
        fused = fuse(
            [result(GeneratorId.ALS, 11), result(GeneratorId.SEMANTIC, 22)],
            surface=SIMILAR_SURFACE,
        )
        assert [c.book_id for c in fused] == [22]

    def test_surface_weights_change_the_winner(self) -> None:
        """ADR-0017 rejected one shared weight set precisely because per-
        surface weights are the main mechanism by which surfaces differ."""
        results = [result(GeneratorId.ALS, 11), result(GeneratorId.SOURCE_SIMILARITY, 22)]
        als_led = fuse(results, surface=surface(als=2.0, source_similarity=0.5))
        graph_led = fuse(results, surface=surface(als=0.5, source_similarity=3.0))
        assert als_led[0].book_id == 11
        assert graph_led[0].book_id == 22

    def test_the_three_shipped_surfaces_genuinely_differ(self) -> None:
        """ADR-0017: "the surfaces genuinely differ" is a testable property,
        and is tested."""
        from book_recommender.config import SHELF_SURFACE

        weights = {
            surface_config.name: {
                quota.generator: quota.rrf_weight for quota in surface_config.quotas
            }
            for surface_config in (HOME_SURFACE, SHELF_SURFACE, SIMILAR_SURFACE)
        }
        assert weights["home"] != weights["shelf"] != weights["similar"]
        # The specific orderings rec-spec §20 asks for.
        assert weights["similar"]["source_similarity"] > weights["home"]["source_similarity"]
        assert weights["shelf"]["semantic"] > weights["home"]["semantic"]
        assert weights["similar"]["als"] == 0.0
        assert SIMILAR_SURFACE.quota_for("als") is None

    def test_popularity_is_never_the_strongest_source_on_any_surface(self) -> None:
        """rec-spec §15: popularity is a fallback and a small Home source.
        A feed that ranks by popularity with a personalization garnish is
        not personalized, it just looks busy (ADR-0017)."""
        from book_recommender.config import SHELF_SURFACE

        for config in (HOME_SURFACE, SHELF_SURFACE, SIMILAR_SURFACE):
            weights = {q.generator: q.rrf_weight for q in config.quotas}
            assert weights["popularity"] == min(w for w in weights.values() if w > 0)


class TestDeterminismAndDeduplication:
    def test_a_book_appears_once_however_many_generators_found_it(self) -> None:
        fused = fuse(
            [
                result(GeneratorId.ALS, 11),
                result(GeneratorId.ITEM_CF, 11),
                result(GeneratorId.SEMANTIC, 11),
            ],
            surface=surface(als=1.0, item_cf=1.0, semantic=1.0),
        )
        assert len(fused) == 1
        assert fused[0].agreement == 3

    def test_ties_break_on_agreement_before_book_id(self) -> None:
        """RRF produces exact ties routinely — two books at the same rank in
        two equally-weighted generators fuse identically. Consensus is a
        better tiebreak than catalog insertion order."""
        fused = fuse(
            [
                result(GeneratorId.ALS, 50),
                result(GeneratorId.ITEM_CF, 50),
                result(GeneratorId.SEMANTIC, 10),
            ],
            surface=surface(als=1.0, item_cf=1.0, semantic=2.0),
        )
        assert fused[0].fusion_score == pytest.approx(fused[1].fusion_score)
        assert fused[0].book_id == 50  # two sources, despite the higher id
        assert fused[0].agreement == 2

    def test_output_is_identical_across_runs(self) -> None:
        results = [
            result(GeneratorId.ALS, 11, 22, 33),
            result(GeneratorId.SEMANTIC, 33, 44),
        ]
        first = fuse(results, surface=HOME_SURFACE)
        second = fuse(results, surface=HOME_SURFACE)
        assert first == second

    def test_empty_input_is_not_an_error(self) -> None:
        assert fuse([], surface=HOME_SURFACE) == ()
