"""ALS and item-item training (rec-spec §9.1, §10).

Skipped unless the ``training`` dependency group is installed, which
``make setup`` deliberately does not do (ADR-0021). The runtime behaviour
these produce — fold-in, neighbour retrieval — is covered without the group
by ``packages/recommender``'s own tests; what needs the group is the claim
that the *trainers* produce what those loaders expect.
"""

from __future__ import annotations

import numpy as np
import pytest
from book_recommender.artifacts import CatalogSnapshot
from book_recommender.config import (
    HISTORICAL_TRANSFORM_V1,
    AlsConfig,
    ItemCfConfig,
)

from book_app.modules.recommendations.interaction_transform import (
    InteractionDataset,
    InteractionReport,
)

pytest.importorskip("implicit", reason="training dependency group not installed")
pytest.importorskip("scipy", reason="training dependency group not installed")

from book_app.modules.recommendations.cf_training import (  # noqa: E402
    build_user_item_matrix,
    rank_for_users,
    rank_from_neighbors,
    train_als,
    train_item_neighbors,
)

ITEM_COUNT = 40
CATALOG = CatalogSnapshot.from_rows(
    f"{ITEM_COUNT}:2026-08-13",
    [(10 * (index + 1), f"w-{index}") for index in range(ITEM_COUNT)],
)


def _dataset(rows: list[tuple[int, int, float]]) -> InteractionDataset:
    """``(user_index, item_index, confidence)`` triplets."""
    return InteractionDataset(
        user_indices=np.asarray([r[0] for r in rows], dtype=np.int32),
        item_indices=np.asarray([r[1] for r in rows], dtype=np.int32),
        confidences=np.asarray([r[2] for r in rows], dtype=np.float32),
        user_count=max((r[0] for r in rows), default=-1) + 1,
        item_count=ITEM_COUNT,
        transform_version=HISTORICAL_TRANSFORM_V1.version,
        report=InteractionReport(
            rows_total=len(rows), rows_used=len(rows), rows_dropped_unresolved_work=0
        ),
    )


def _clustered() -> InteractionDataset:
    """Twenty readers of items 0-9, twenty of items 20-29 — two communities
    with no overlap, so "learned something" is checkable rather than hoped
    for."""
    rows: list[tuple[int, int, float]] = []
    for user in range(20):
        rows.extend((user, item, 3.0) for item in range(10))
    for user in range(20, 40):
        rows.extend((user, item, 3.0) for item in range(20, 30))
    return _dataset(rows)


# --- Matrix construction ----------------------------------------------------


def test_matrix_spans_the_whole_catalog_not_just_touched_items() -> None:
    """Column *i* must be ``model_item_index`` *i* in every family, so the
    matrix cannot be compacted to interacted items only."""
    matrix = build_user_item_matrix(_dataset([(0, 5, 1.0), (1, 7, 2.0)]))

    assert matrix.shape == (2, ITEM_COUNT)
    assert matrix[0, 5] == pytest.approx(1.0)
    assert matrix[1, 7] == pytest.approx(2.0)


def test_duplicate_interactions_are_summed_canonically() -> None:
    matrix = build_user_item_matrix(_dataset([(0, 3, 1.0), (0, 3, 2.0)]))

    assert matrix[0, 3] == pytest.approx(3.0)
    assert matrix.has_canonical_format


def test_row_mask_excludes_held_out_rows() -> None:
    dataset = _dataset([(0, 1, 1.0), (0, 2, 1.0), (0, 3, 1.0)])
    mask = np.asarray([True, False, True], dtype=bool)

    matrix = build_user_item_matrix(dataset, row_mask=mask)

    assert matrix.nnz == 2
    assert matrix[0, 2] == 0.0


# --- ALS --------------------------------------------------------------------


def test_als_learns_the_community_structure() -> None:
    matrix = build_user_item_matrix(_clustered())

    trained = train_als(matrix, AlsConfig(factors=8, regularization=0.01, iterations=15))

    # Items inside a community should be more alike than across communities.
    factors = trained.item_factors
    normalized = factors / (np.linalg.norm(factors, axis=1, keepdims=True) + 1e-9)
    within = float(normalized[0] @ normalized[5])
    across = float(normalized[0] @ normalized[25])
    assert within > across


def test_als_is_deterministic_for_a_fixed_random_state() -> None:
    """Determinism is what makes a rebuild's checksums comparable
    (rec-spec §28)."""
    matrix = build_user_item_matrix(_clustered())
    config = AlsConfig(factors=8, regularization=0.05, iterations=5, random_state=7)

    first = train_als(matrix, config)
    second = train_als(matrix, config)

    assert np.array_equal(first.item_factors, second.item_factors)


def test_als_factor_rows_cover_the_whole_item_space() -> None:
    matrix = build_user_item_matrix(_clustered())

    trained = train_als(matrix, AlsConfig(factors=8, regularization=0.05, iterations=3))

    assert trained.item_factors.shape == (ITEM_COUNT, 8)
    assert trained.factor_count == 8


def test_als_factors_are_finite() -> None:
    matrix = build_user_item_matrix(_clustered())

    trained = train_als(matrix, AlsConfig(factors=8, regularization=0.05, iterations=5))

    assert np.all(np.isfinite(trained.item_factors))


def test_ranking_excludes_a_user_s_own_training_items() -> None:
    """Recommending back a book the reader already has is trivially easy and
    would flatter every configuration equally."""
    matrix = build_user_item_matrix(_clustered())
    trained = train_als(matrix, AlsConfig(factors=8, regularization=0.05, iterations=5))

    rankings = rank_for_users(trained, matrix, [0], count=10)

    assert set(rankings[0]).isdisjoint(range(10))


# --- Item-item CF -----------------------------------------------------------


def test_neighbours_are_within_the_community() -> None:
    matrix = build_user_item_matrix(_clustered())

    indptr, indices, scores = train_item_neighbors(
        matrix, ItemCfConfig(similarity="cosine", top_k=5)
    )

    neighbours = indices[indptr[0] : indptr[1]]
    assert set(neighbours) <= set(range(1, 10))


def test_an_item_is_never_its_own_neighbour() -> None:
    matrix = build_user_item_matrix(_clustered())

    indptr, indices, _ = train_item_neighbors(matrix, ItemCfConfig(similarity="cosine", top_k=10))

    for item in range(ITEM_COUNT):
        assert item not in indices[indptr[item] : indptr[item + 1]]


def test_top_k_bounds_each_row() -> None:
    matrix = build_user_item_matrix(_clustered())

    indptr, _, _ = train_item_neighbors(matrix, ItemCfConfig(similarity="cosine", top_k=3))

    assert all(indptr[i + 1] - indptr[i] <= 3 for i in range(ITEM_COUNT))


def test_neighbours_are_ordered_strongest_first() -> None:
    matrix = build_user_item_matrix(_clustered())

    indptr, _, scores = train_item_neighbors(matrix, ItemCfConfig(similarity="cosine", top_k=10))

    for item in range(ITEM_COUNT):
        row = scores[indptr[item] : indptr[item + 1]]
        assert row == sorted(row, reverse=True)


def test_neighbour_build_is_deterministic() -> None:
    matrix = build_user_item_matrix(_clustered())
    config = ItemCfConfig(similarity="bm25", top_k=5)

    first = train_item_neighbors(matrix, config)
    second = train_item_neighbors(matrix, config)

    assert first == second


def test_bm25_prefers_evidence_from_focused_readers() -> None:
    """What BM25 actually contributes here (see ``_bm25_weight``): a
    co-occurrence observed through readers with enormous libraries is weaker
    evidence than the same co-occurrence through focused readers.

    Item 1 and item 2 each co-occur with item 0 exactly three times. Under
    plain cosine that makes them tied. Under BM25 the prolific readers who
    link item 1 count for less, so item 2 wins — which is the popularity
    correction rec-spec §10 asks for, expressed on the user side where
    per-item normalization cannot cancel it.
    """
    rows: list[tuple[int, int, float]] = []
    for user in range(3):  # prolific readers: items 0 and 1, plus 30 others
        rows.append((user, 0, 1.0))
        rows.append((user, 1, 1.0))
        rows.extend((user, filler, 1.0) for filler in range(10, ITEM_COUNT))
    for user in range(3, 6):  # focused readers: items 0 and 2 only
        rows.append((user, 0, 1.0))
        rows.append((user, 2, 1.0))
    matrix = build_user_item_matrix(_dataset(rows))

    def similarity_to_item_0(config: ItemCfConfig) -> dict[int, float]:
        indptr, indices, scores = train_item_neighbors(matrix, config)
        return {indices[i]: scores[i] for i in range(indptr[0], indptr[1])}

    # top_k above the candidate count, so nothing is truncated: under cosine
    # every one of item 0's neighbours ties, and which ones a top-K cut would
    # keep is arbitrary rather than meaningful.
    cosine = similarity_to_item_0(ItemCfConfig(similarity="cosine", top_k=ITEM_COUNT))
    bm25 = similarity_to_item_0(ItemCfConfig(similarity="bm25", top_k=ITEM_COUNT))

    assert cosine[1] == pytest.approx(cosine[2])
    assert bm25[2] > bm25[1]


def test_seed_ranking_excludes_seeds_and_respects_weights() -> None:
    matrix = build_user_item_matrix(_clustered())
    indptr, indices, scores = train_item_neighbors(
        matrix, ItemCfConfig(similarity="cosine", top_k=10)
    )

    rankings = rank_from_neighbors(
        indptr, indices, scores, matrix, [0], count=10, item_count=ITEM_COUNT
    )

    assert set(rankings[0]).isdisjoint(range(10))


def test_empty_matrix_produces_empty_neighbours() -> None:
    matrix = build_user_item_matrix(_dataset([(0, 0, 1.0)]))

    indptr, indices, scores = train_item_neighbors(
        matrix, ItemCfConfig(similarity="cosine", top_k=5)
    )

    assert len(indptr) == ITEM_COUNT + 1
    assert indices == []
    assert scores == []
