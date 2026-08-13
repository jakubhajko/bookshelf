"""Historical-interaction transform (rec-spec §7.2).

The rules under test are correctness rules, not tuning: implicit rows are
positives, low explicit ratings are omitted rather than fed in as negatives,
unresolved works are dropped *and counted*, and historical user ids never
become anything joinable to an application user.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from book_recommender.artifacts import CatalogSnapshot
from book_recommender.config import HISTORICAL_TRANSFORM_V1

from book_app.modules.recommendations.interaction_transform import (
    InteractionDataError,
    build_dataset,
    catalog_items_in_index_order,
    validate_schema,
)

CATALOG = CatalogSnapshot.from_rows("3:2026-08-13", [(10, "w-a"), (20, "w-b"), (30, "w-c")])


def _frame(rows: list[tuple[int, str, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "user_id": pd.array([r[0] for r in rows], dtype="int32"),
            "work_id": pd.array([r[1] for r in rows], dtype="string"),
            "rating": pd.array([r[2] for r in rows], dtype="int8"),
            "is_explicit": pd.array([r[2] != 0 for r in rows], dtype="bool"),
        }
    )


# --- Schema validation ------------------------------------------------------


def test_valid_frame_passes() -> None:
    validate_schema(_frame([(1, "w-a", 0), (1, "w-b", 8)]))


def test_missing_column_is_rejected() -> None:
    frame = _frame([(1, "w-a", 0)]).drop(columns=["is_explicit"])
    with pytest.raises(InteractionDataError, match="missing column"):
        validate_schema(frame)


def test_wrong_dtype_is_rejected() -> None:
    frame = _frame([(1, "w-a", 0)])
    frame["rating"] = frame["rating"].astype("float64")
    with pytest.raises(InteractionDataError, match="must be integer"):
        validate_schema(frame)


def test_out_of_range_rating_is_rejected() -> None:
    frame = _frame([(1, "w-a", 0)])
    frame["rating"] = pd.array([11], dtype="int8")
    with pytest.raises(InteractionDataError, match=r"within \[0, 10\]"):
        validate_schema(frame)


def test_a_row_marked_explicit_with_rating_zero_is_rejected() -> None:
    """Rating 0 is the implicit-positive marker. A row claiming to be an
    explicit 0 makes the transform's central distinction ambiguous."""
    frame = _frame([(1, "w-a", 0)])
    frame["is_explicit"] = pd.array([True], dtype="bool")
    with pytest.raises(InteractionDataError, match="implicit-positive marker"):
        validate_schema(frame)


def test_nulls_are_rejected() -> None:
    frame = _frame([(1, "w-a", 0)])
    frame.loc[0, "work_id"] = None
    with pytest.raises(InteractionDataError, match="nulls"):
        validate_schema(frame)


# --- The transform itself ---------------------------------------------------


def test_implicit_rows_are_positives_not_zeros() -> None:
    """rec-spec §7.2's headline rule: ``rating == 0`` is an implicit
    positive. Dropping it would discard 61% of the real dataset."""
    dataset = build_dataset(_frame([(1, "w-a", 0)]), CATALOG, HISTORICAL_TRANSFORM_V1)

    assert len(dataset) == 1
    assert dataset.confidences[0] == pytest.approx(1.0)


def test_low_explicit_ratings_are_omitted_and_counted() -> None:
    """1–5 is negative evidence, and V1 omits it rather than training on
    negative confidence."""
    rows = [(1, "w-a", rating) for rating in (1, 2, 3, 4, 5)]
    dataset = build_dataset(_frame(rows), CATALOG, HISTORICAL_TRANSFORM_V1)

    assert len(dataset) == 0
    assert dataset.report.rows_dropped_by_rating == {1: 1, 2: 1, 3: 1, 4: 1, 5: 1}


def test_confidence_increases_with_rating() -> None:
    rows = [(1, "w-a", 7), (1, "w-b", 8), (1, "w-c", 10)]
    dataset = build_dataset(_frame(rows), CATALOG, HISTORICAL_TRANSFORM_V1)

    assert list(dataset.confidences) == pytest.approx([2.0, 3.0, 5.0])


def test_neutral_rating_is_excluded_by_default_and_included_on_request() -> None:
    """rec-spec §7.2 leaves rating 6 to evaluation, so both variants must
    work and be distinguishable by transform version."""
    rows = [(1, "w-a", 6), (1, "w-b", 8)]

    without = build_dataset(_frame(rows), CATALOG, HISTORICAL_TRANSFORM_V1)
    with_neutral = build_dataset(_frame(rows), CATALOG, HISTORICAL_TRANSFORM_V1.with_neutral(True))

    assert len(without) == 1
    assert without.report.rows_dropped_by_rating == {6: 1}
    assert len(with_neutral) == 2
    assert without.transform_version != with_neutral.transform_version
    assert with_neutral.transform_version.endswith("with-neutral")


def test_alpha_scales_every_confidence() -> None:
    scaled = HISTORICAL_TRANSFORM_V1.__class__(
        version="scaled",
        implicit_confidence=HISTORICAL_TRANSFORM_V1.implicit_confidence,
        explicit_confidence=HISTORICAL_TRANSFORM_V1.explicit_confidence,
        include_neutral=False,
        alpha=10.0,
    )
    dataset = build_dataset(_frame([(1, "w-a", 0), (1, "w-b", 8)]), CATALOG, scaled)

    assert list(dataset.confidences) == pytest.approx([10.0, 30.0])


def test_unresolved_works_are_dropped_and_reported() -> None:
    rows = [(1, "w-a", 8), (1, "gone-1", 8), (2, "gone-2", 0)]
    dataset = build_dataset(_frame(rows), CATALOG, HISTORICAL_TRANSFORM_V1)

    assert len(dataset) == 1
    report = dataset.report
    assert report.rows_dropped_unresolved_work == 2
    assert report.works_unresolved == 2
    assert set(report.unresolved_work_sample) == {"gone-1", "gone-2"}
    assert report.works_resolved == 1


def test_item_indices_are_catalog_order_not_dataset_order() -> None:
    """Every family shares one ``model_item_index`` space. If this dataset
    numbered items by first appearance, an ALS factor row would refer to a
    different book than the popularity score at the same index."""
    # w-c appears first here, but it is book_id 30 — index 2 in the catalog.
    dataset = build_dataset(
        _frame([(1, "w-c", 8), (1, "w-a", 8)]), CATALOG, HISTORICAL_TRANSFORM_V1
    )

    assert sorted(dataset.item_indices) == [0, 2]
    assert catalog_items_in_index_order(CATALOG) == [(10, "w-a"), (20, "w-b"), (30, "w-c")]


def test_user_indices_are_dense_and_local_to_the_dataset() -> None:
    """Historical user ids are opaque row groupings. They are remapped to a
    dense training space and never leave the transform in a form that could
    be joined to an application user (rec-spec §7.2)."""
    rows = [(276727, "w-a", 8), (999999, "w-b", 8), (276727, "w-c", 0)]
    dataset = build_dataset(_frame(rows), CATALOG, HISTORICAL_TRANSFORM_V1)

    assert sorted(set(dataset.user_indices)) == [0, 1]
    assert dataset.user_count == 2
    # The original integers appear nowhere in the dataset the trainers see.
    assert not hasattr(dataset, "user_ids")
    assert 276727 not in set(dataset.user_indices.tolist())


def test_item_count_is_the_whole_catalog_not_just_interacted_items() -> None:
    """The matrix has to span the shared item space, or item factor rows
    would not line up with ``model_item_index``."""
    dataset = build_dataset(_frame([(1, "w-a", 8)]), CATALOG, HISTORICAL_TRANSFORM_V1)

    assert dataset.item_count == 3
    assert dataset.report.items_used == 1


def test_report_totals_reconcile() -> None:
    rows = [(1, "w-a", 8), (1, "w-b", 3), (2, "gone", 8), (2, "w-c", 0)]
    dataset = build_dataset(_frame(rows), CATALOG, HISTORICAL_TRANSFORM_V1)
    report = dataset.report

    accounted = (
        report.rows_used
        + report.rows_dropped_unresolved_work
        + sum(report.rows_dropped_by_rating.values())
    )
    assert accounted == report.rows_total == 4


def test_empty_input_produces_an_empty_dataset_not_a_crash() -> None:
    dataset = build_dataset(_frame([]), CATALOG, HISTORICAL_TRANSFORM_V1)

    assert len(dataset) == 0
    assert dataset.user_count == 0
    assert dataset.item_count == 3
    assert np.asarray(dataset.item_indices).size == 0
