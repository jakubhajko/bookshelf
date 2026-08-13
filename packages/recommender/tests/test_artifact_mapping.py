"""Item mapping and its resolution against the live catalog (ADR-0014).

The behaviour under test is the one that makes a database rebuild safe:
``work_id`` is authoritative, the build-time ``book_id`` is not, and an
artifact that cannot be reconciled with the live catalog must not be served.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from book_recommender.artifacts.mapping import (
    CatalogSnapshot,
    ItemMapping,
    MappingStatus,
    resolve_item_mapping,
)
from book_recommender.artifacts.numeric import save_arrays, string_column_arrays
from book_recommender.exceptions import IncompatibleArtifactError


def _catalog(*rows: tuple[int, str], version: str = "3:2026-08-13T00:00:00") -> CatalogSnapshot:
    return CatalogSnapshot.from_rows(version, list(rows))


def test_mapping_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "mapping.npz"
    mapping = ItemMapping.build([(10, "w-a"), (20, "w-b")])
    mapping.save(path)

    loaded = ItemMapping.load(path, expected_item_count=2)
    assert loaded.work_ids == ("w-a", "w-b")
    assert loaded.book_ids.tolist() == [10, 20]


def test_mapping_length_disagreeing_with_the_manifest_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "mapping.npz"
    ItemMapping.build([(10, "w-a")]).save(path)
    with pytest.raises(IncompatibleArtifactError, match="expected 5"):
        ItemMapping.load(path, expected_item_count=5)


def test_duplicate_work_ids_are_rejected(tmp_path: Path) -> None:
    """Two rows claiming the same durable id make ``model_item_index``
    ambiguous, so resolution could silently pick either."""
    path = tmp_path / "mapping.npz"
    ItemMapping.build([(10, "dup"), (20, "dup")]).save(path)
    with pytest.raises(IncompatibleArtifactError, match="duplicate work_ids"):
        ItemMapping.load(path)


def test_mapping_with_mismatched_column_lengths_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "mapping.npz"
    save_arrays(
        path,
        {
            "book_ids": np.array([1, 2, 3], dtype=np.int64),
            **string_column_arrays("work_ids", ["only-one"]),
        },
    )
    with pytest.raises(IncompatibleArtifactError):
        ItemMapping.load(path)


def test_mapping_missing_its_work_id_column_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "mapping.npz"
    save_arrays(path, {"book_ids": np.array([1, 2], dtype=np.int64)})
    with pytest.raises(IncompatibleArtifactError, match="work_ids_offsets"):
        ItemMapping.load(path)


def test_fully_resolvable_mapping_is_ok() -> None:
    mapping = ItemMapping.build([(1, "w-a"), (2, "w-b")])
    resolution = resolve_item_mapping(mapping, _catalog((1, "w-a"), (2, "w-b")))

    assert resolution.status is MappingStatus.OK
    assert resolution.resolved_count == 2
    assert resolution.book_ids.tolist() == [1, 2]
    assert resolution.reassigned_count == 0


def test_reassigned_book_ids_resolve_through_work_id() -> None:
    """The failure ADR-0014 exists to prevent: after a re-import the same
    autoincrement integers belong to different books. Resolving by
    ``work_id`` must return the *new* ids, not the ones baked into the
    artifact — and must say so.
    """
    mapping = ItemMapping.build([(1, "w-a"), (2, "w-b")])
    reimported = _catalog((77, "w-a"), (88, "w-b"))

    resolution = resolve_item_mapping(mapping, reimported)

    assert resolution.status is MappingStatus.OK
    assert resolution.book_ids.tolist() == [77, 88]
    assert resolution.reassigned_count == 2


def test_a_few_missing_works_degrade_and_are_dropped() -> None:
    mapping = ItemMapping.build([(index, f"w-{index}") for index in range(20)])
    catalog = _catalog(*[(index, f"w-{index}") for index in range(19)])

    resolution = resolve_item_mapping(mapping, catalog)

    assert resolution.status is MappingStatus.DEGRADED
    assert resolution.is_servable
    assert resolution.resolved_count == 19
    assert resolution.unresolved_count == 1
    assert resolution.unresolved_work_ids == ("w-19",)
    assert 19 not in resolution.model_item_indices.tolist()


def test_too_many_missing_works_is_rejected() -> None:
    mapping = ItemMapping.build([(index, f"w-{index}") for index in range(20)])
    catalog = _catalog(*[(index, f"w-{index}") for index in range(10)])

    resolution = resolve_item_mapping(mapping, catalog)

    assert resolution.status is MappingStatus.REJECTED
    assert not resolution.is_servable
    assert resolution.reason is not None
    assert "rebuild the artifact" in resolution.reason


def test_an_entirely_different_catalog_is_rejected() -> None:
    """The incompatible-catalog case: nothing in common, so serving the
    intersection would serve nothing while looking healthy."""
    mapping = ItemMapping.build([(1, "old-a"), (2, "old-b")])
    resolution = resolve_item_mapping(mapping, _catalog((1, "new-a"), (2, "new-b")))
    assert resolution.status is MappingStatus.REJECTED


def test_unresolved_sample_is_bounded() -> None:
    mapping = ItemMapping.build([(index, f"w-{index}") for index in range(1000)])
    catalog = _catalog(*[(index, f"w-{index}") for index in range(920)])

    resolution = resolve_item_mapping(mapping, catalog)

    assert resolution.unresolved_count == 80
    assert len(resolution.unresolved_work_ids) == 20


def test_empty_artifact_is_rejected() -> None:
    resolution = resolve_item_mapping(ItemMapping.build([]), _catalog((1, "w-a")))
    assert resolution.status is MappingStatus.REJECTED
    assert resolution.reason == "artifact contains no items"


def test_index_to_book_id_marks_dropped_items() -> None:
    mapping = ItemMapping.build([(1, "w-a"), (2, "gone"), (3, "w-c")])
    resolution = resolve_item_mapping(
        mapping, _catalog((1, "w-a"), (3, "w-c")), max_unresolved_fraction=0.5
    )

    lookup = resolution.index_to_book_id(3)

    assert lookup.tolist() == [1, -1, 3]
