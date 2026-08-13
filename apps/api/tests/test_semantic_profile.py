"""Evidence collection for semantic profiling (rec-spec §7.1, §12).

The inference itself lives in ``book_recommender.profiling`` and is tested
there. What is application-specific — and what this covers — is *which*
signals become positive evidence and how strongly, which is rec-spec §7.1's
signal policy.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import numpy as np
import pytest
from book_recommender.config import SIGNAL_WEIGHTS_DEFAULT, SignalWeights
from book_recommender.contracts.context import (
    RatingSnapshot,
    SavedBookSnapshot,
    TasteSeedSnapshot,
    UserContext,
)

from book_app.modules.recommendations.semantic_profile import (
    build_semantic_profile,
    collect_evidence,
)

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
SHELF_A, SHELF_B = uuid4(), uuid4()
NOW = datetime(2026, 8, 13, tzinfo=UTC)


class FakeEmbeddings:
    def __init__(self, book_ids: list[int]) -> None:
        rng = np.random.default_rng(0)
        self._vectors = {}
        for index, book_id in enumerate(book_ids):
            vector = rng.normal(scale=0.02, size=4)
            vector[index % 2] += 1.0
            self._vectors[book_id] = (vector / np.linalg.norm(vector)).astype(np.float32)

    def vectors_for(self, book_ids: Sequence[int]) -> tuple[np.ndarray, list[int]]:
        rows, resolved = [], []
        for book_id in book_ids:
            vector = self._vectors.get(book_id)
            if vector is not None:
                rows.append(vector)
                resolved.append(book_id)
        if not rows:
            return np.empty((0, 4), dtype=np.float32), []
        return np.vstack(rows), resolved


def _context(
    *,
    ratings: tuple[RatingSnapshot, ...] = (),
    saved: tuple[SavedBookSnapshot, ...] = (),
    seeds: tuple[TasteSeedSnapshot, ...] = (),
    not_interested: frozenset[int] = frozenset(),
) -> UserContext:
    return UserContext(
        user_id=USER_ID,
        ratings=ratings,
        saved_book_ids=frozenset(item.book_id for item in saved),
        saved_books=saved,
        shelf_ids=tuple({item.shelf_id for item in saved}),
        not_interested_book_ids=not_interested,
        recent_interactions=(),
        shelf_summaries=(),
        taste_seeds=seeds,
        profile_version="v1:test",
    )


def _rating(book_id: int, value: int) -> RatingSnapshot:
    return RatingSnapshot(book_id=book_id, rating_value=value, rated_at=NOW)


def _saved(book_id: int, shelf_id: UUID = SHELF_A) -> SavedBookSnapshot:
    return SavedBookSnapshot(book_id=book_id, shelf_id=shelf_id, added_at=NOW)


def _seed(book_id: int) -> TasteSeedSnapshot:
    return TasteSeedSnapshot(book_id=book_id, source="onboarding", selected_at=NOW)


# --- Signal policy ----------------------------------------------------------


def test_high_ratings_outweigh_lukewarm_ones() -> None:
    evidence = collect_evidence(_context(ratings=(_rating(1, 10), _rating(2, 8), _rating(3, 7))))

    weights = {item.book_id: item.weight for item in evidence}
    assert weights[1] > weights[2] > weights[3] > 0


def test_neutral_and_negative_ratings_contribute_nothing() -> None:
    """rec-spec §7.1: 6 is neutral, 1-5 negative. A book a reader disliked
    must not pull their interest centroid toward it."""
    evidence = collect_evidence(
        _context(ratings=tuple(_rating(index, index) for index in range(1, 7)))
    )

    assert evidence == []


def test_saves_and_taste_seeds_are_strong_positives() -> None:
    evidence = collect_evidence(_context(saved=(_saved(1),), seeds=(_seed(2),)))

    sources = {item.book_id: item.source for item in evidence}
    assert sources == {1: "shelf_save", 2: "taste_seed"}
    assert all(item.weight > 0 for item in evidence)


def test_not_interested_books_are_excluded_from_every_signal() -> None:
    """Even when another signal would have introduced them — a reader can
    save a book and later mark it Not Interested."""
    evidence = collect_evidence(
        _context(
            ratings=(_rating(1, 10),),
            saved=(_saved(1),),
            seeds=(_seed(1),),
            not_interested=frozenset({1}),
        )
    )

    assert evidence == []


def test_signal_weights_are_configurable() -> None:
    custom = SignalWeights(taste_seed=99.0)

    evidence = collect_evidence(_context(seeds=(_seed(1),)), weights=custom)

    assert evidence[0].weight == pytest.approx(99.0)


def test_rating_scale_boundaries() -> None:
    weights = SIGNAL_WEIGHTS_DEFAULT
    assert weights.for_rating(10) == weights.for_rating(9)
    assert weights.for_rating(8) > weights.for_rating(7) > 0
    assert weights.for_rating(6) == 0.0
    assert weights.for_rating(1) == 0.0


# --- Profile assembly -------------------------------------------------------


def test_profile_covers_both_interests_and_shelves() -> None:
    saved = (_saved(1, SHELF_A), _saved(2, SHELF_A), _saved(3, SHELF_B))
    context = _context(ratings=(_rating(4, 10), _rating(5, 9)), saved=saved)
    embeddings = FakeEmbeddings([1, 2, 3, 4, 5])

    profile = build_semantic_profile(context, embeddings)

    assert not profile.is_empty
    assert {shelf.shelf_id for shelf in profile.shelves} == {str(SHELF_A), str(SHELF_B)}
    assert profile.interests.evidence_count == 5


def test_a_book_on_two_shelves_appears_in_both_shelf_profiles() -> None:
    saved = (_saved(1, SHELF_A), _saved(1, SHELF_B), _saved(2, SHELF_A))
    profile = build_semantic_profile(_context(saved=saved), FakeEmbeddings([1, 2]))

    members = {shelf.shelf_id: shelf.member_book_ids for shelf in profile.shelves}
    assert 1 in members[str(SHELF_A)]
    assert 1 in members[str(SHELF_B)]


def test_an_empty_context_yields_an_empty_profile() -> None:
    profile = build_semantic_profile(_context(), FakeEmbeddings([]))

    assert profile.is_empty
    assert profile.interests.strategy.value == "none"


def test_a_not_interested_book_is_kept_out_of_shelf_profiles_too() -> None:
    saved = (_saved(1, SHELF_A), _saved(2, SHELF_A))
    context = _context(saved=saved, not_interested=frozenset({1}))

    profile = build_semantic_profile(context, FakeEmbeddings([1, 2]))

    assert profile.shelves[0].member_book_ids == (2,)
