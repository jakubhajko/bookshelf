"""Surface-specific diversity reranking (rec-spec §19, ADR-0017)."""

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
from book_recommender.pipeline import DiversityReranker, RerankContext, series_of
from book_recommender.pipeline.fusion import FusedCandidate, SourceContribution
from book_recommender.pipeline.ranking import RankedCandidate
from book_recommender.pipeline.reranking import duplicate_key
from generator_world import build_all, load_content, load_metadata


def candidate(book_id: int, score: float, *, provenance: str = "als") -> RankedCandidate:
    fused = FusedCandidate(
        book_id=book_id,
        fusion_score=score,
        sources=(
            SourceContribution(
                generator=provenance.split(":")[0],
                rank=1,
                raw_score=score,
                contribution=score,
                provenance=provenance,
            ),
        ),
    )
    return RankedCandidate(book_id=book_id, score=score, fused=fused)


def surface(**rerank: float | int) -> SurfaceConfig:
    return SurfaceConfig(
        name="test",
        quotas=(GeneratorQuota(generator="als", rrf_weight=1.0, count=50),),
        ranking=RankingWeights(),
        rerank=RerankConfig(**rerank),  # type: ignore[arg-type]
    )


@pytest.fixture
def storage(tmp_path: Path) -> LocalArtifactStorage:
    return build_all(tmp_path)


class TestSeriesDetection:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Dune Messiah (Dune Chronicles #2)", "dune chronicles"),
            ("The Fellowship of the Ring (The Lord of the Rings, #1)", "the lord of the rings"),
            ("Project Princess (The Princess Diaries, #4.5)", "the princess diaries"),
            ("Dune", None),
            ("Blade Runner", None),
            # Not a series marker: no '#' number.
            ("Something (Illustrated Edition)", None),
        ],
    )
    def test_detects_only_real_series_markers(self, title: str, expected: str | None) -> None:
        """rec-spec §19 says "repeated series where detectable". A loose
        pattern that groups unrelated books is worse than missing some."""
        assert series_of(title) == expected


class TestDuplicateWorkDetection:
    def test_the_live_dune_pair_produces_one_key(self) -> None:
        """The exact case the smoke test found: `#58203 'Dune'` and
        `#67405 'Dune *'` are separate catalog rows for one work."""
        assert duplicate_key("Dune", "Frank Herbert") == duplicate_key("Dune *", "Frank Herbert")

    def test_a_sequel_is_not_the_same_work(self) -> None:
        """The property that makes this usable on Similar Books, where the
        sequels are the correct answer."""
        assert duplicate_key("Dune", "Frank Herbert") != duplicate_key(
            "Dune Messiah (Dune Chronicles #2)", "Frank Herbert"
        )

    def test_the_same_title_by_a_different_author_is_a_different_work(self) -> None:
        assert duplicate_key("Dune", "Frank Herbert") != duplicate_key("Dune", "Someone Else")

    @pytest.mark.parametrize(
        ("title", "author"),
        [("", "Frank Herbert"), ("Dune", ""), ("   ", "  "), ("***", "Frank Herbert")],
    )
    def test_returns_none_when_there_is_nothing_to_compare(self, title: str, author: str) -> None:
        """~2,300 catalog books have no author. A key that collided on
        emptiness would group all of them into one work."""
        assert duplicate_key(title, author) is None

    def test_cosine_alone_could_not_have_caught_the_dune_pair(
        self, storage: LocalArtifactStorage
    ) -> None:
        """Recording the measurement that forced this mechanism to exist.

        On the live artifact, cos('Dune', 'Dune *') = 0.7246 while
        cos('Dune', 'Dune Messiah') = 0.8092 — the duplicate is *less*
        similar than the sequel, because the duplicate row has 69 ratings
        against 16,541 and therefore a much thinner description. Any
        threshold catching the first also catches the second.

        The fixture reproduces the ordering rather than the numbers: 101 and
        109 are in different taste groups, so no threshold separates a
        'duplicate' from a 'sequel' by cosine when the duplicate's text is
        the thinner one.
        """
        embeddings = load_content(storage)
        same_group = embeddings.similarity(101, 102)
        cross_group = embeddings.similarity(101, 109)
        assert same_group is not None and cross_group is not None
        assert same_group > cross_group
        # Identity, unlike cosine, is not a matter of degree.
        assert duplicate_key("First Fantasy", "Alpha Author") == duplicate_key(
            "First Fantasy!", "Alpha Author"
        )


class TestPenalties:
    def test_repeated_authors_are_spread_out(self, storage: LocalArtifactStorage) -> None:
        """101 and 102 share an author; 109 does not. With a large author
        penalty the third slot must break the run rather than continue it."""
        candidates = [candidate(101, 1.0), candidate(102, 0.9), candidate(109, 0.5)]
        context = RerankContext(
            surface=surface(author_penalty=0.5, series_penalty=0.0),
            metadata=load_metadata(storage),
        )
        order = [
            c.book_id for c in DiversityReranker().rerank(candidates, context=context, limit=3)
        ]
        assert order == [101, 109, 102]

    def test_series_repetition_is_penalized(self, storage: LocalArtifactStorage) -> None:
        """101 and 102 are both 'Alpha Saga'; 103 is not."""
        candidates = [candidate(101, 1.0), candidate(102, 0.9), candidate(103, 0.5)]
        context = RerankContext(
            surface=surface(author_penalty=0.0, series_penalty=0.6),
            metadata=load_metadata(storage),
        )
        order = [
            c.book_id for c in DiversityReranker().rerank(candidates, context=context, limit=3)
        ]
        assert order == [101, 103, 102]

    def test_semantically_near_identical_books_are_suppressed(
        self, storage: LocalArtifactStorage
    ) -> None:
        """The cosine half of duplicate control: two books whose *content*
        is near-identical, such as a reissue whose description was copied.

        Deliberately **not** the 'Dune' / 'Dune *' case — that pair sits at
        0.7246, below its own sequel, so cosine never catches it. Identity
        does, via `duplicate_key`; the two mechanisms cover different
        failures and neither subsumes the other.
        """
        candidates = [candidate(101, 1.0), candidate(102, 0.99), candidate(109, 0.4)]
        context = RerankContext(
            surface=surface(
                near_duplicate_threshold=0.9,
                near_duplicate_penalty=1.0,
                author_penalty=0.0,
                series_penalty=0.0,
            ),
            embeddings=load_content(storage),
        )
        order = [
            c.book_id for c in DiversityReranker().rerank(candidates, context=context, limit=3)
        ]
        assert order == [101, 109, 102]
        demoted = next(
            c
            for c in DiversityReranker().rerank(candidates, context=context, limit=3)
            if c.book_id == 102
        )
        assert any("near-duplicate" in reason for reason in demoted.reasons)

    def test_a_duplicate_of_the_source_book_is_suppressed(
        self, storage: LocalArtifactStorage
    ) -> None:
        """The bug the live smoke test found. The reranker compares against
        what it has *selected*, and the source book is excluded from the
        results, so nothing ever caught a candidate that duplicated it —
        Similar-to-'Dune' returned 'Dune *' at rank 10.

        Here 101 is the reference (the source book) and 102 is given the
        same title and author by the metadata fixture's own key rule, so it
        must be pushed below the unrelated 109.
        """
        candidates = [candidate(102, 1.0), candidate(109, 0.5)]
        context = RerankContext(
            surface=surface(
                near_duplicate_penalty=1.0,
                author_penalty=0.0,
                series_penalty=0.0,
                interest_concentration_penalty=0.0,
                source_concentration_penalty=0.0,
            ),
            metadata=load_metadata(storage),
            reference_book_ids=(102,),
        )
        selected = DiversityReranker().rerank(candidates, context=context, limit=2)
        assert [c.book_id for c in selected] == [109, 102]
        demoted = selected[1]
        assert "duplicate work" in demoted.reasons
        assert demoted.penalty == pytest.approx(1.0)

    def test_reference_books_do_not_trigger_author_or_series_penalties(
        self, storage: LocalArtifactStorage
    ) -> None:
        """rec-spec §19: "do not aggressively suppress same-author items if
        they are genuinely relevant." The Dune sequels share the source
        book's author and series, and on Similar Books they are the answer.
        """
        candidates = [candidate(102, 1.0), candidate(109, 0.9)]
        context = RerankContext(
            surface=surface(author_penalty=0.5, series_penalty=0.5),
            metadata=load_metadata(storage),
            reference_book_ids=(101,),  # same author and series as 102
        )
        selected = DiversityReranker().rerank(candidates, context=context, limit=2)
        assert [c.book_id for c in selected] == [102, 109]
        assert selected[0].penalty == 0.0

    def test_interest_concentration_is_penalized(self) -> None:
        """rec-spec §19: "excessive concentration in one inferred interest"."""
        candidates = [
            candidate(1, 1.0, provenance="interest:i0"),
            candidate(2, 0.9, provenance="interest:i0"),
            candidate(3, 0.5, provenance="interest:i1"),
        ]
        context = RerankContext(surface=surface(interest_concentration_penalty=0.5))
        order = [
            c.book_id for c in DiversityReranker().rerank(candidates, context=context, limit=3)
        ]
        assert order == [1, 3, 2]

    def test_source_concentration_is_penalized(self) -> None:
        """rec-spec §19: "excessive concentration from one candidate
        source". Without it, ALS's Gini of 0.86 (risk #98) reaches the feed
        undiluted."""
        candidates = [
            candidate(1, 1.0, provenance="als"),
            candidate(2, 0.9, provenance="als"),
            candidate(3, 0.5, provenance="semantic"),
        ]
        context = RerankContext(surface=surface(source_concentration_penalty=0.5))
        order = [
            c.book_id for c in DiversityReranker().rerank(candidates, context=context, limit=3)
        ]
        assert order == [1, 3, 2]

    def test_penalties_accumulate_with_each_repetition(self, storage: LocalArtifactStorage) -> None:
        """The third book by an author is penalized more than the second, so
        a long run costs progressively more."""
        candidates = [candidate(105, 1.0), candidate(106, 0.99)]
        context = RerankContext(
            # Only the author penalty is left on, so the assertion below
            # attributes the whole penalty to it rather than to the sum of
            # four defaults.
            surface=surface(
                author_penalty=0.1,
                series_penalty=0.0,
                interest_concentration_penalty=0.0,
                source_concentration_penalty=0.0,
            ),
            metadata=load_metadata(storage),
        )
        selected = DiversityReranker().rerank(candidates, context=context, limit=2)
        assert selected[1].penalty == pytest.approx(0.1)
        assert "author x1" in selected[1].reasons


class TestSurfaceStrength:
    def test_similar_suppresses_same_author_far_less_than_home(self) -> None:
        """rec-spec §19 for Similar Books: "do not aggressively suppress
        same-author items if they are genuinely relevant." Someone who just
        read *Dune* is not badly served by *Dune Messiah*."""
        assert SIMILAR_SURFACE.rerank.author_penalty < SHELF_SURFACE.rerank.author_penalty
        assert SHELF_SURFACE.rerank.author_penalty < HOME_SURFACE.rerank.author_penalty

    def test_home_has_the_strongest_diversity_policy(self) -> None:
        for weaker in (SHELF_SURFACE, SIMILAR_SURFACE):
            assert (
                HOME_SURFACE.rerank.interest_concentration_penalty
                >= weaker.rerank.interest_concentration_penalty
            )
            assert HOME_SURFACE.rerank.series_penalty >= weaker.rerank.series_penalty

    def test_only_home_reserves_exploration_slots(self) -> None:
        """rec-spec §19 gives exploration to Home alone; Similar Books with
        an exploration allowance would be Similar Books that sometimes
        ignores the book you asked about."""
        assert HOME_SURFACE.rerank.exploration_slots > 0
        assert SHELF_SURFACE.rerank.exploration_slots == 0
        assert SIMILAR_SURFACE.rerank.exploration_slots == 0

    def test_the_same_candidates_order_differently_per_surface(
        self, storage: LocalArtifactStorage
    ) -> None:
        """One reusable pipeline, different typed configuration (rec-spec
        §20) — the surfaces differing is a property, not an intention."""
        # 101 and 102 share an author *and* the 'Alpha Saga' series; 109
        # shares neither, and comes from a different generator so no source
        # or interest penalty applies to it on either surface.
        candidates = [
            candidate(101, 1.0),
            candidate(102, 0.98),
            candidate(109, 0.5, provenance="semantic"),
        ]
        metadata = load_metadata(storage)
        home = DiversityReranker().rerank(
            candidates, context=RerankContext(surface=HOME_SURFACE, metadata=metadata), limit=3
        )
        similar = DiversityReranker().rerank(
            candidates, context=RerankContext(surface=SIMILAR_SURFACE, metadata=metadata), limit=3
        )
        # Home's penalties (0.20 author + 0.30 series + 0.15 interest +
        # 0.10 source = 0.75) sink 102 below a much weaker 109; Similar's
        # (0.05 + 0.08 + 0 + 0.05 = 0.18) leave the run intact, which is
        # rec-spec §19's "do not aggressively suppress same-author items".
        assert [c.book_id for c in home] == [101, 109, 102]
        assert [c.book_id for c in similar] == [101, 102, 109]


class TestExploration:
    def test_reserved_slots_go_to_an_unrepresented_interest(self) -> None:
        """rec-spec §15: exploration is a reranking policy, never "show more
        bestsellers". The reserved slot goes to an interest nothing selected
        has covered, even though a stronger candidate is available."""
        candidates = [
            candidate(1, 1.0, provenance="interest:i0"),
            candidate(2, 0.9, provenance="interest:i0"),
            candidate(3, 0.1, provenance="interest:i1"),
        ]
        context = RerankContext(
            surface=surface(
                exploration_slots=1,
                interest_concentration_penalty=0.0,
                source_concentration_penalty=0.0,
            )
        )
        selected = DiversityReranker().rerank(candidates, context=context, limit=2)
        assert [c.book_id for c in selected] == [1, 3]
        assert selected[1].exploration is True

    def test_exploration_does_not_fire_when_nothing_is_selected_yet(self) -> None:
        candidates = [candidate(1, 1.0, provenance="interest:i0")]
        context = RerankContext(surface=surface(exploration_slots=1))
        selected = DiversityReranker().rerank(candidates, context=context, limit=1)
        assert selected[0].exploration is False


class TestContractAndDegradation:
    def test_positions_are_one_based_and_dense(self, storage: LocalArtifactStorage) -> None:
        candidates = [
            candidate(book_id, 1.0 - 0.1 * i) for i, book_id in enumerate((101, 105, 109))
        ]
        selected = DiversityReranker().rerank(
            candidates, context=RerankContext(surface=HOME_SURFACE), limit=3
        )
        assert [c.position for c in selected] == [1, 2, 3]

    def test_the_limit_is_respected(self) -> None:
        candidates = [candidate(book_id, 1.0) for book_id in range(20)]
        selected = DiversityReranker().rerank(
            candidates, context=RerankContext(surface=HOME_SURFACE), limit=5
        )
        assert len(selected) == 5

    def test_no_book_is_selected_twice(self, storage: LocalArtifactStorage) -> None:
        candidates = [candidate(book_id, 1.0) for book_id in (101, 102, 103, 104)]
        selected = DiversityReranker().rerank(
            candidates,
            context=RerankContext(surface=HOME_SURFACE, metadata=load_metadata(storage)),
            limit=4,
        )
        ids = [c.book_id for c in selected]
        assert len(ids) == len(set(ids))

    def test_missing_artifacts_cost_penalties_not_the_request(self) -> None:
        """rec-spec §27: without embeddings there is no near-duplicate
        detection and without metadata no author control, but the interest
        and source penalties keep working from provenance alone."""
        candidates = [candidate(1, 1.0), candidate(2, 0.9)]
        selected = DiversityReranker().rerank(
            candidates, context=RerankContext(surface=HOME_SURFACE), limit=2
        )
        assert [c.book_id for c in selected] == [1, 2]

    def test_output_is_identical_across_runs(self, storage: LocalArtifactStorage) -> None:
        candidates = [candidate(book_id, 1.0) for book_id in (101, 102, 105, 109, 110)]
        context = RerankContext(
            surface=HOME_SURFACE,
            metadata=load_metadata(storage),
            embeddings=load_content(storage),
        )
        reranker = DiversityReranker()
        first = reranker.rerank(candidates, context=context, limit=5)
        second = reranker.rerank(candidates, context=context, limit=5)
        assert [c.book_id for c in first] == [c.book_id for c in second]

    def test_equal_scores_still_produce_a_stable_order(self) -> None:
        """Every candidate identical is the worst case for a greedy loop:
        without a deterministic pick the persisted batch would differ per
        process."""
        candidates = [candidate(book_id, 1.0) for book_id in (5, 3, 9, 1)]
        reranker = DiversityReranker()
        context = RerankContext(surface=HOME_SURFACE)
        runs = {
            tuple(c.book_id for c in reranker.rerank(candidates, context=context, limit=4))
            for _ in range(5)
        }
        assert len(runs) == 1

    def test_empty_input_is_not_an_error(self) -> None:
        assert (
            DiversityReranker().rerank([], context=RerankContext(surface=HOME_SURFACE), limit=5)
            == ()
        )

    def test_reasons_are_compact_strings_not_a_blob(self, storage: LocalArtifactStorage) -> None:
        """ADR-0017 warns against a diagnostics blob on all 60 rows."""
        candidates = [candidate(101, 1.0), candidate(102, 0.9)]
        selected = DiversityReranker().rerank(
            candidates,
            context=RerankContext(surface=HOME_SURFACE, metadata=load_metadata(storage)),
            limit=2,
        )
        for entry in selected:
            assert all(isinstance(reason, str) and len(reason) < 40 for reason in entry.reasons)
            assert isinstance(entry.penalty, float)
            assert "array" not in repr(entry.reasons)


def test_numpy_is_not_leaked_into_scores() -> None:
    selected = DiversityReranker().rerank(
        [candidate(1, 1.0)], context=RerankContext(surface=HOME_SURFACE), limit=1
    )
    assert not isinstance(selected[0].score, np.ndarray)
