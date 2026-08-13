"""The generator framework itself: ranks, interleaving and seed policy.

These are the invariants every generator inherits rather than implements,
so a bug here is a bug in all five at once.
"""

from __future__ import annotations

import numpy as np
import pytest

from book_recommender.config import COLLABORATIVE_WEIGHTS_DEFAULT, GeneratorConfig
from book_recommender.contracts.context import (
    HomeContext,
    SearchContext,
    ShelfContext,
    SimilarBooksContext,
)
from book_recommender.generators import (
    GeneratorId,
    GeneratorStatus,
    collect_seeds,
    interleave,
    rank_all,
)
from generator_world import (
    FANTASY,
    ROMANCE,
    SCIFI,
    SHELF_FANTASY,
    SHELF_SCIFI,
    user_context,
)


class TestRankAll:
    def test_ranks_are_one_based_and_dense(self) -> None:
        """ADR-0017 fuses with ``weight / (rrf_k + rank)``. A 0-based or
        gappy rank silently rescales every fusion contribution."""
        candidates = rank_all(
            [(11, 0.9), (22, 0.5), (33, 0.1)],
            generator=GeneratorId.ALS,
            provenance="als",
            limit=10,
        )
        assert [candidate.rank for candidate in candidates] == [1, 2, 3]

    def test_exclusions_do_not_leave_gaps_in_the_rank_sequence(self) -> None:
        """The excluded book must not consume rank 2 and leave a hole — RRF
        would then treat the survivor as weaker than it is."""
        candidates = rank_all(
            [(11, 0.9), (22, 0.5), (33, 0.1)],
            generator=GeneratorId.ALS,
            provenance="als",
            limit=10,
            excluded_book_ids=frozenset({22}),
        )
        assert [(c.book_id, c.rank) for c in candidates] == [(11, 1), (33, 2)]

    def test_duplicate_book_ids_are_dropped(self) -> None:
        """rec-spec §16: a generator must not return the same book twice —
        fusion would count it at two ranks and inflate its fused score."""
        candidates = rank_all(
            [(11, 0.9), (11, 0.5), (22, 0.1)],
            generator=GeneratorId.ITEM_CF,
            provenance="item_cf",
            limit=10,
        )
        assert [candidate.book_id for candidate in candidates] == [11, 22]

    def test_input_order_is_preserved_not_resorted(self) -> None:
        """Callers sort deterministically before calling; re-sorting here
        would override a generator that had a reason for its order."""
        candidates = rank_all(
            [(11, 0.1), (22, 0.9)],
            generator=GeneratorId.POPULARITY,
            provenance="popularity",
            limit=10,
        )
        assert [candidate.book_id for candidate in candidates] == [11, 22]

    def test_limit_truncates(self) -> None:
        candidates = rank_all(
            [(book_id, 1.0) for book_id in range(10)],
            generator=GeneratorId.ALS,
            provenance="als",
            limit=3,
        )
        assert len(candidates) == 3


class TestInterleave:
    def test_each_query_gets_its_best_before_any_gets_its_second(self) -> None:
        """The reason multi-interest profiling exists (rec-spec §12.2). A
        merge by raw score would let the tightest cluster take every slot."""
        candidates = interleave(
            [
                ("interest:a", [(1, 0.99), (2, 0.98), (3, 0.97)]),
                ("interest:b", [(4, 0.50), (5, 0.49)]),
            ],
            generator=GeneratorId.SEMANTIC,
            limit=6,
        )
        assert [candidate.book_id for candidate in candidates] == [1, 4, 2, 5, 3]

    def test_a_book_found_by_two_queries_keeps_its_best_rank_and_records_both(
        self,
    ) -> None:
        """rec-spec §21: provenance is preserved, not discarded."""
        candidates = interleave(
            [
                ("interest:a", [(7, 0.9)]),
                ("interest:b", [(7, 0.8), (8, 0.7)]),
            ],
            generator=GeneratorId.SEMANTIC,
            limit=5,
        )
        assert [candidate.book_id for candidate in candidates] == [7, 8]
        first = candidates[0]
        assert first.provenance == "interest:a"
        assert first.diagnostics["queries"] == 2
        assert first.diagnostics["also_from"] == ("interest:b",)

    def test_query_count_counts_agreement_found_after_the_limit_is_reached(
        self,
    ) -> None:
        """The `queries` count is evidence that two interests agree, and it
        is read by the ranker (rec-spec §18). The full round-robin runs
        before trimming so a surviving book still gets credit for a query
        that reached it late — breaking out of the scan as soon as ``limit``
        candidates existed would undercount exactly the books that survive.

        Here book 9 is found by query ``b`` at position 0 and again by ``a``
        at position 1, which is after the limit's worth of candidates has
        already been collected.
        """
        candidates = interleave(
            [
                ("interest:a", [(1, 0.9), (9, 0.5)]),
                ("interest:b", [(9, 0.4), (2, 0.9)]),
            ],
            generator=GeneratorId.SEMANTIC,
            limit=2,
        )
        assert [candidate.book_id for candidate in candidates] == [1, 9]
        agreed = candidates[1]
        assert agreed.book_id == 9
        assert agreed.diagnostics["queries"] == 2
        assert agreed.diagnostics["also_from"] == ("interest:a",)

    def test_exclusions_apply(self) -> None:
        candidates = interleave(
            [("interest:a", [(1, 0.9), (2, 0.8)])],
            generator=GeneratorId.SEMANTIC,
            limit=5,
            excluded_book_ids=frozenset({1}),
        )
        assert [candidate.book_id for candidate in candidates] == [2]

    def test_empty_input_is_not_an_error(self) -> None:
        assert interleave([], generator=GeneratorId.SEMANTIC, limit=5) == ()


class TestSeedPolicy:
    def test_similar_books_seeds_only_the_source_book(self) -> None:
        """rec-spec §20.3: the source book is the entire query. The reader's
        own taste must not leak in, or Similar becomes "more books you may
        like"."""
        context = user_context(ratings=[(101, 10), (102, 9)])
        seeds = collect_seeds(context, SimilarBooksContext(source_book_id=500))
        assert [seed.book_id for seed in seeds] == [500]
        assert seeds[0].source == "source_book"

    def test_shelf_seeds_the_target_shelf_not_the_global_profile(self) -> None:
        """rec-spec §20.2: extend the *shelf*, not the reader's whole taste."""
        context = user_context(ratings=[(109, 10)], saved=[(110, SHELF_SCIFI)])
        surface = ShelfContext(
            shelf_id=SHELF_FANTASY,
            shelf_name="Fantasy",
            shelf_description=None,
            shelf_book_ids=frozenset(FANTASY),
        )
        seeds = collect_seeds(context, surface)
        assert {seed.book_id for seed in seeds} == set(FANTASY)
        assert all(seed.source == "target_shelf" for seed in seeds)

    def test_home_uses_the_readers_positive_evidence(self) -> None:
        context = user_context(ratings=[(101, 10)], saved=[(105, SHELF_SCIFI)], taste_seeds=[109])
        seeds = collect_seeds(context, HomeContext())
        assert {seed.book_id for seed in seeds} == {101, 105, 109}

    def test_a_book_with_two_signals_counts_once_at_its_strongest(self) -> None:
        """rec-spec §7.1: "avoid uncontrolled double-counting". A book both
        saved and rated 10/10 is strong evidence once, not two readers."""
        context = user_context(ratings=[(101, 10)], saved=[(101, SHELF_FANTASY)])
        seeds = collect_seeds(context, HomeContext())
        assert len(seeds) == 1
        assert seeds[0].book_id == 101
        assert seeds[0].weight == COLLABORATIVE_WEIGHTS_DEFAULT.rating_9_10
        assert seeds[0].source == "rating"

    @pytest.mark.parametrize("rating", [1, 3, 5, 6])
    def test_neutral_and_negative_ratings_never_seed(self, rating: int) -> None:
        """rec-spec §7.1: 6 is neutral ("omit"), 1-5 is "do not seed". Not
        negative confidence — simply absent (rec-spec §9.2)."""
        context = user_context(ratings=[(101, rating)])
        assert collect_seeds(context, HomeContext()) == ()

    def test_not_interested_books_are_never_seeded(self) -> None:
        """rec-spec §7.1's Not Interested row: "never seed"."""
        context = user_context(
            ratings=[(101, 10)],
            saved=[(101, SHELF_FANTASY)],
            not_interested=[101],
        )
        assert collect_seeds(context, HomeContext()) == ()

    def test_seeds_are_ordered_strongest_first_and_capped(self) -> None:
        """The cap must cost the weakest evidence, not an arbitrary slice."""
        context = user_context(ratings=[(101, 7), (102, 10), (103, 8)])
        config = GeneratorConfig(max_seed_books=2)
        seeds = collect_seeds(context, HomeContext(), config=config)
        assert [seed.book_id for seed in seeds] == [102, 103]

    def test_seed_order_is_deterministic_for_equal_weights(self) -> None:
        """Without the book_id tiebreak, a reader with equally-weighted saves
        would get a different seed set per process and the persisted batch
        would stop being reproducible."""
        saved = [(book_id, SHELF_FANTASY) for book_id in reversed(SCIFI)]
        context = user_context(saved=saved)
        first = collect_seeds(context, HomeContext())
        second = collect_seeds(user_context(saved=list(saved)), HomeContext())
        assert [seed.book_id for seed in first] == sorted(SCIFI)
        assert first == second

    def test_search_surface_falls_back_to_global_evidence(self) -> None:
        """Search has no query understanding yet (rec-spec §7.1 gives it a CF
        weight of 0). Seeding like Home is honest about that; returning
        nothing would pretend the reader has no taste."""
        context = user_context(ratings=[(101, 10)])
        seeds = collect_seeds(context, SearchContext(query="dragons"))
        assert [seed.book_id for seed in seeds] == [101]

    def test_a_reader_with_no_evidence_produces_no_seeds(self) -> None:
        assert collect_seeds(user_context(), HomeContext()) == ()


def test_every_status_and_generator_id_has_a_distinct_value() -> None:
    """These are ``StrEnum``s whose values escape the package — into
    ``candidate_sources`` on persisted rows and into diagnostics. Two members
    sharing a value is a copy-paste bug that silently merges two states, and
    it is invisible at the member level: rec-spec §27 needs "artifact absent"
    and "no evidence" to stay distinguishable all the way out.
    """
    statuses = [status.value for status in GeneratorStatus]
    assert len(set(statuses)) == len(statuses)
    ids = [generator.value for generator in GeneratorId]
    assert len(set(ids)) == len(ids)


def test_group_vectors_are_unit_norm() -> None:
    """The content loader refuses a non-normalized artifact; this keeps the
    fixture honest about matching what serving would accept."""
    from generator_world import group_vectors

    norms = np.linalg.norm(group_vectors(), axis=1)
    assert np.allclose(norms, 1.0, atol=1e-6)


def test_fixture_groups_are_disjoint() -> None:
    assert len(set(FANTASY) | set(SCIFI) | set(ROMANCE)) == 12
