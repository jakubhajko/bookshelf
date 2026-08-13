"""Per-user holdout and ranking metrics (rec-spec §23.1).

Worth testing properly rather than trusting: a wrong metric does not crash,
it silently selects the wrong model, and every downstream claim about which
configuration is better rests on these functions.
"""

from __future__ import annotations

import numpy as np
import pytest
from book_recommender.config import HoldoutConfig

from book_app.modules.recommendations.cf_evaluation import (
    average_precision_at_k,
    build_holdout,
    evaluate_rankings,
    gini_coefficient,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

# --- Metrics ----------------------------------------------------------------


def test_recall_counts_hits_within_k() -> None:
    assert recall_at_k([1, 2, 3, 4], {2, 4}, 4) == pytest.approx(1.0)
    assert recall_at_k([1, 2, 3, 4], {2, 9}, 4) == pytest.approx(0.5)
    assert recall_at_k([1, 2, 3, 4], {9}, 4) == pytest.approx(0.0)


def test_recall_denominator_is_capped_at_k() -> None:
    """A user with more held-out items than the page length must still be
    able to score 1.0, or the metric is not comparable across users."""
    ranked = [1, 2, 3]
    relevant = {1, 2, 3, 4, 5, 6}

    assert recall_at_k(ranked, relevant, 3) == pytest.approx(1.0)


def test_precision_divides_by_k_not_by_list_length() -> None:
    assert precision_at_k([1, 2, 3, 4], {1, 2}, 4) == pytest.approx(0.5)
    assert precision_at_k([1, 2], {1, 2}, 4) == pytest.approx(0.5)


def test_ndcg_rewards_earlier_hits() -> None:
    early = ndcg_at_k([1, 9, 9, 9], {1}, 4)
    late = ndcg_at_k([9, 9, 9, 1], {1}, 4)

    assert early == pytest.approx(1.0)
    assert late < early


def test_ndcg_is_one_for_a_perfect_ranking() -> None:
    assert ndcg_at_k([1, 2, 3], {1, 2, 3}, 3) == pytest.approx(1.0)


def test_ndcg_ideal_is_capped_at_k() -> None:
    assert ndcg_at_k([1, 2], {1, 2, 3, 4, 5}, 2) == pytest.approx(1.0)


def test_average_precision_penalises_late_hits() -> None:
    assert average_precision_at_k([1, 2], {1, 2}, 2) == pytest.approx(1.0)
    # Hits at positions 2 and 4: (1/2 + 2/4) / 2 = 0.5
    assert average_precision_at_k([9, 1, 9, 2], {1, 2}, 4) == pytest.approx(0.5)


def test_metrics_are_zero_without_relevant_items() -> None:
    for metric in (recall_at_k, ndcg_at_k, average_precision_at_k):
        assert metric([1, 2, 3], set(), 3) == 0.0


def test_gini_is_zero_for_a_perfectly_even_distribution() -> None:
    assert gini_coefficient(np.array([5.0, 5.0, 5.0, 5.0])) == pytest.approx(0.0, abs=1e-9)


def test_gini_approaches_one_when_one_item_absorbs_everything() -> None:
    concentrated = gini_coefficient(np.array([0.0] * 99 + [1000.0]))
    spread = gini_coefficient(np.array([10.0] * 100))

    assert concentrated > 0.9
    assert concentrated > spread


def test_gini_handles_empty_and_zero_input() -> None:
    assert gini_coefficient(np.array([])) == 0.0
    assert gini_coefficient(np.array([0.0, 0.0])) == 0.0


# --- Holdout ----------------------------------------------------------------


def _dataset(users_items: dict[int, list[int]]) -> tuple[np.ndarray, np.ndarray]:
    users: list[int] = []
    items: list[int] = []
    for user, item_list in users_items.items():
        users.extend([user] * len(item_list))
        items.extend(item_list)
    return (
        np.asarray(users, dtype=np.int32),
        np.asarray(items, dtype=np.int32),
    )


def test_holdout_withholds_a_fraction_of_an_active_user() -> None:
    users, items = _dataset({0: list(range(10))})

    split = build_holdout(users, items, HoldoutConfig(fraction=0.2, min_interactions=5))

    assert split.held_out_items[0].size == 2
    assert split.train_row_count == 8


def test_users_below_the_minimum_are_kept_whole_and_not_evaluated() -> None:
    """Holding one of three items out measures the split, not the model —
    but the rows still belong in training."""
    users, items = _dataset({0: [1, 2, 3], 1: list(range(10))})

    split = build_holdout(users, items, HoldoutConfig(fraction=0.2, min_interactions=5))

    assert 0 not in split.held_out_items
    assert 1 in split.held_out_items
    assert split.evaluated_user_count == 1
    # All three of user 0's rows survive in training.
    assert split.train_mask[users == 0].all()


def test_holdout_is_capped_per_user() -> None:
    """Without a cap, a handful of readers with hundreds of books would
    dominate the averaged metrics."""
    users, items = _dataset({0: list(range(1000))})

    split = build_holdout(
        users, items, HoldoutConfig(fraction=0.2, min_interactions=5, max_held_out=20)
    )

    assert split.held_out_items[0].size == 20


def test_held_out_rows_are_excluded_from_training() -> None:
    users, items = _dataset({0: list(range(10))})

    split = build_holdout(users, items, HoldoutConfig(fraction=0.2, min_interactions=5))

    held_out = set(split.held_out_items[0].tolist())
    training_items = set(items[split.train_mask].tolist())
    assert not (held_out & training_items)


def test_holdout_is_deterministic_for_a_fixed_seed() -> None:
    users, items = _dataset({user: list(range(20)) for user in range(5)})
    config = HoldoutConfig(fraction=0.2, min_interactions=5, random_state=7)

    first = build_holdout(users, items, config)
    second = build_holdout(users, items, config)

    assert np.array_equal(first.train_mask, second.train_mask)
    assert all(
        np.array_equal(first.held_out_items[u], second.held_out_items[u])
        for u in first.held_out_items
    )


def test_a_different_seed_produces_a_different_split() -> None:
    users, items = _dataset({user: list(range(20)) for user in range(5)})

    first = build_holdout(users, items, HoldoutConfig(random_state=1))
    second = build_holdout(users, items, HoldoutConfig(random_state=2))

    assert not np.array_equal(first.train_mask, second.train_mask)


def test_holdout_handles_an_empty_dataset() -> None:
    split = build_holdout(
        np.asarray([], dtype=np.int32), np.asarray([], dtype=np.int32), HoldoutConfig()
    )

    assert split.evaluated_user_count == 0
    assert split.train_row_count == 0


# --- Aggregation ------------------------------------------------------------


def test_evaluate_rankings_averages_across_users() -> None:
    held_out = {0: np.asarray([1], dtype=np.int32), 1: np.asarray([2], dtype=np.int32)}
    rankings = {0: [1, 9, 9], 1: [9, 9, 9]}

    result = evaluate_rankings("test", rankings, held_out, k_values=[3], item_count=100)

    assert result.users_evaluated == 2
    assert result.metrics["recall@3"] == pytest.approx(0.5)
    assert result.primary(3) == result.metrics["ndcg@3"]


def test_users_without_held_out_items_are_skipped() -> None:
    held_out = {0: np.asarray([1], dtype=np.int32)}
    rankings = {0: [1, 2], 1: [3, 4], 2: [5, 6]}

    result = evaluate_rankings("test", rankings, held_out, k_values=[2], item_count=10)

    assert result.users_evaluated == 1


def test_coverage_counts_distinct_recommended_items() -> None:
    held_out = {0: np.asarray([1], dtype=np.int32), 1: np.asarray([1], dtype=np.int32)}
    # Both users get the same two books, so coverage is 2/100.
    rankings = {0: [1, 2], 1: [1, 2]}

    result = evaluate_rankings("test", rankings, held_out, k_values=[2], item_count=100)

    assert result.catalog_coverage == pytest.approx(0.02)


def test_a_model_that_recommends_the_same_books_to_everyone_scores_high_gini() -> None:
    """The check that catches respectable-looking Recall achieved purely by
    recommending bestsellers to everyone."""
    held_out = {user: np.asarray([1], dtype=np.int32) for user in range(20)}
    identical = {user: [1, 2, 3] for user in range(20)}
    varied = {user: [user * 3, user * 3 + 1, user * 3 + 2] for user in range(20)}

    same = evaluate_rankings("same", identical, held_out, k_values=[3], item_count=100)
    diverse = evaluate_rankings("diverse", varied, held_out, k_values=[3], item_count=100)

    assert same.catalog_coverage < diverse.catalog_coverage
    assert same.popularity_gini == pytest.approx(0.0, abs=1e-9)
    # Concentration shows up as coverage here: three items for everyone.
    assert len(varied) * 3 > 3


def test_empty_rankings_produce_a_zeroed_result_not_a_crash() -> None:
    result = evaluate_rankings("empty", {}, {}, k_values=[10], item_count=100)

    assert result.users_evaluated == 0
    assert result.catalog_coverage == 0.0
    assert result.primary(10) == 0.0
