"""Item-item CF artifact and seed-based retrieval (rec-spec §10)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from book_recommender.artifacts import (
    CatalogSnapshot,
    LocalArtifactStorage,
    load_item_cf_artifact,
    write_artifact,
    write_item_cf_neighbors,
)
from book_recommender.artifacts.item_cf import NEIGHBORS_FILENAME
from book_recommender.artifacts.numeric import save_arrays
from book_recommender.config import ITEM_CF
from book_recommender.exceptions import IncompatibleArtifactError

ITEM_COUNT = 20
ITEMS = [(10 * (index + 1), f"w-{index}") for index in range(ITEM_COUNT)]
CATALOG = CatalogSnapshot.from_rows(f"{ITEM_COUNT}:2026-08-13", ITEMS)


@pytest.fixture
def storage(tmp_path: Path) -> LocalArtifactStorage:
    return LocalArtifactStorage(tmp_path)


def _csr(
    rows: dict[int, list[tuple[int, float]]],
) -> tuple[list[int], list[int], list[float]]:
    """``{source_index: [(neighbor_index, score), ...]}`` → CSR columns."""
    indptr = [0]
    indices: list[int] = []
    scores: list[float] = []
    for index in range(ITEM_COUNT):
        for neighbor, score in rows.get(index, []):
            indices.append(neighbor)
            scores.append(score)
        indptr.append(len(indices))
    return indptr, indices, scores


def _write(
    storage: LocalArtifactStorage,
    rows: dict[int, list[tuple[int, float]]],
    *,
    config: dict[str, object] | None = None,
) -> None:
    indptr, indices, scores = _csr(rows)
    write_artifact(
        storage,
        ITEM_CF,
        model_version="20260813T120000Z",
        catalog_version=CATALOG.catalog_version,
        items=ITEMS,
        payloads={
            NEIGHBORS_FILENAME: lambda path: write_item_cf_neighbors(
                path, indptr=indptr, neighbor_indices=indices, scores=scores
            )
        },
        config=config or {"similarity": "bm25", "top_k": 100},  # type: ignore[arg-type]
    )


# --- Loading ----------------------------------------------------------------


def test_neighbours_round_trip_strongest_first(storage: LocalArtifactStorage) -> None:
    _write(storage, {0: [(1, 0.9), (2, 0.5)], 3: [(0, 0.7)]})

    artifact = load_item_cf_artifact(storage, catalog=CATALOG)

    # Scores round-trip through float32 storage, so compare approximately.
    assert [n.book_id for n in artifact.neighbors(10)] == [20, 30]
    assert [n.score for n in artifact.neighbors(10)] == pytest.approx([0.9, 0.5])
    assert artifact.neighbors(20) == ()
    assert artifact.has_neighbors(10)
    assert not artifact.has_neighbors(20)
    assert artifact.similarity == "bm25"
    assert artifact.top_k == 100
    assert artifact.edge_count == 3


def test_neighbour_limit_truncates_the_weakest(storage: LocalArtifactStorage) -> None:
    _write(storage, {0: [(1, 0.9), (2, 0.5), (3, 0.1)]})

    artifact = load_item_cf_artifact(storage, catalog=CATALOG)

    assert [n.book_id for n in artifact.neighbors(10, limit=2)] == [20, 30]


def test_edges_into_a_departed_book_are_dropped(storage: LocalArtifactStorage) -> None:
    _write(storage, {0: [(1, 0.9), (2, 0.5)], 3: [(2, 0.7)]})
    thinned = CatalogSnapshot.from_rows("19:2026-09-01", [row for row in ITEMS if row[1] != "w-2"])

    artifact = load_item_cf_artifact(storage, catalog=thinned)

    live = set(thinned.work_id_to_book_id.values())
    assert [n.book_id for n in artifact.neighbors(10)] == [20]
    assert artifact.neighbors(40) == ()
    for book_id in live:
        assert {n.book_id for n in artifact.neighbors(book_id)} <= live


def test_a_neighbour_outside_the_item_space_is_rejected(
    storage: LocalArtifactStorage,
) -> None:
    _write(storage, {0: [(1, 0.9)]})
    indptr = [0] + [1] * ITEM_COUNT
    save_arrays(
        storage.resolve(ITEM_CF.directory, NEIGHBORS_FILENAME),
        {
            "indptr": np.asarray(indptr, dtype=np.int64),
            "neighbor_indices": np.asarray([999], dtype=np.int32),
            "scores": np.asarray([0.5], dtype=np.float32),
        },
    )
    manifest = storage.load_manifest(ITEM_CF.directory)
    storage.save_manifest(ITEM_CF.directory, manifest.model_copy(update={"files": ()}))

    with pytest.raises(IncompatibleArtifactError, match="outside the artifact's item space"):
        load_item_cf_artifact(storage, catalog=CATALOG)


def test_an_incompatible_catalog_is_not_served(storage: LocalArtifactStorage) -> None:
    _write(storage, {0: [(1, 0.9)]})
    other = CatalogSnapshot.from_rows(
        "20:2027", [(index, f"x-{index}") for index in range(ITEM_COUNT)]
    )

    with pytest.raises(IncompatibleArtifactError, match="not servable"):
        load_item_cf_artifact(storage, catalog=other)


# --- Seed-based retrieval (rec-spec §10) ------------------------------------


def test_candidates_aggregate_evidence_across_seeds(storage: LocalArtifactStorage) -> None:
    """A book reachable from several of a reader's books should outrank one
    reachable from a single stronger edge — that is what item-item CF is
    for."""
    _write(storage, {0: [(5, 0.5)], 1: [(5, 0.5)], 2: [(6, 0.9)]})

    artifact = load_item_cf_artifact(storage, catalog=CATALOG)
    candidates = artifact.candidates_from_seeds([(10, 1.0), (20, 1.0), (30, 1.0)], count=5)

    assert [book_id for book_id, _ in candidates[:2]] == [60, 70]
    assert [score for _, score in candidates[:2]] == pytest.approx([1.0, 0.9])


def test_seed_weight_scales_its_contribution(storage: LocalArtifactStorage) -> None:
    """rec-spec §10: "weight seeds according to signal policy". The caller
    owns the policy; the artifact must honour the weights it is given."""
    _write(storage, {0: [(5, 0.5)], 1: [(6, 0.5)]})

    artifact = load_item_cf_artifact(storage, catalog=CATALOG)
    candidates = dict(artifact.candidates_from_seeds([(10, 4.0), (20, 1.0)], count=5))

    assert candidates[60] == pytest.approx(2.0)
    assert candidates[70] == pytest.approx(0.5)


def test_seeds_are_never_recommended_back(storage: LocalArtifactStorage) -> None:
    _write(storage, {0: [(1, 0.9)], 1: [(0, 0.9)]})

    artifact = load_item_cf_artifact(storage, catalog=CATALOG)
    candidates = artifact.candidates_from_seeds([(10, 1.0), (20, 1.0)], count=5)

    assert candidates == ()


def test_retrieval_respects_exclusion_sets(storage: LocalArtifactStorage) -> None:
    _write(storage, {0: [(5, 0.9), (6, 0.5)]})

    artifact = load_item_cf_artifact(storage, catalog=CATALOG)
    candidates = artifact.candidates_from_seeds(
        [(10, 1.0)], count=5, excluded_book_ids=frozenset({60})
    )

    assert [book_id for book_id, _ in candidates] == [70]


def test_ties_break_deterministically(storage: LocalArtifactStorage) -> None:
    """Engine order is authoritative and nothing downstream re-sorts it, so
    equal scores must not produce a different feed run to run."""
    _write(storage, {0: [(5, 0.5), (6, 0.5), (7, 0.5)]})

    artifact = load_item_cf_artifact(storage, catalog=CATALOG)
    first = artifact.candidates_from_seeds([(10, 1.0)], count=3)
    second = artifact.candidates_from_seeds([(10, 1.0)], count=3)

    assert first == second
    assert [book_id for book_id, _ in first] == [60, 70, 80]


def test_seeding_does_not_depend_on_training(storage: LocalArtifactStorage) -> None:
    """rec-spec §10: "User profile changes do not retrain the item-item
    model; they only alter which seed items and weights are used." Different
    seeds, same artifact, no mutation."""
    _write(storage, {0: [(5, 0.9)], 1: [(6, 0.9)]})
    artifact = load_item_cf_artifact(storage, catalog=CATALOG)
    scores_before = artifact._scores.copy()

    first = artifact.candidates_from_seeds([(10, 1.0)], count=5)
    second = artifact.candidates_from_seeds([(20, 1.0)], count=5)

    assert [book_id for book_id, _ in first] == [60]
    assert [book_id for book_id, _ in second] == [70]
    assert np.array_equal(artifact._scores, scores_before)


def test_zero_and_negative_seed_weights_contribute_nothing(
    storage: LocalArtifactStorage,
) -> None:
    _write(storage, {0: [(5, 0.9)]})

    artifact = load_item_cf_artifact(storage, catalog=CATALOG)

    assert artifact.candidates_from_seeds([(10, 0.0)], count=5) == ()
    assert artifact.candidates_from_seeds([(10, -1.0)], count=5) == ()


def test_no_seeds_or_no_neighbours_yields_no_candidates(
    storage: LocalArtifactStorage,
) -> None:
    _write(storage, {0: [(5, 0.9)]})

    artifact = load_item_cf_artifact(storage, catalog=CATALOG)

    assert artifact.candidates_from_seeds([], count=5) == ()
    assert artifact.candidates_from_seeds([(200, 1.0)], count=5) == ()
    assert artifact.candidates_from_seeds([(10, 1.0)], count=0) == ()


def test_neighbors_per_seed_bounds_the_fan_out(storage: LocalArtifactStorage) -> None:
    _write(storage, {0: [(5, 0.9), (6, 0.8), (7, 0.7)]})

    artifact = load_item_cf_artifact(storage, catalog=CATALOG)
    candidates = artifact.candidates_from_seeds([(10, 1.0)], count=10, neighbors_per_seed=2)

    assert [book_id for book_id, _ in candidates] == [60, 70]


class TestSaturatedSimilarityStillProducesAMeaningfulRank:
    """Risk #111, measured in R9 and fixed here.

    10.37% of the live artifact's edges have a similarity of exactly 1.0, so
    the additive aggregate saturates and large groups of candidates land on
    an identical score. Fusion reads rank and nothing else (ADR-0017), so
    whatever breaks that tie *becomes* the evidence. Before R9 it was
    `book_id` — catalog insertion order, presented to RRF as signal. On the
    live reader, 150 returned candidates carried 57 distinct scores with a
    largest tie group of 74.
    """

    def test_more_seeds_reaching_a_book_outranks_a_lower_book_id(
        self, storage: LocalArtifactStorage
    ) -> None:
        """One strong seed and two weak ones produce identical totals.

        Book 60 is reached once at weight 1.0; book 70 twice at weight 0.5.
        Both total exactly 1.0, and 60 has the smaller id — so the *only*
        thing that can order them correctly is how many of the reader's
        books point at them.
        """
        _write(storage, {0: [(5, 1.0)], 1: [(6, 1.0)], 2: [(6, 1.0)]})

        artifact = load_item_cf_artifact(storage, catalog=CATALOG)
        candidates = artifact.candidates_from_seeds([(10, 1.0), (20, 0.5), (30, 0.5)], count=5)

        assert [score for _, score in candidates] == pytest.approx([1.0, 1.0])
        assert [book_id for book_id, _ in candidates] == [70, 60]

    def test_a_stronger_neighbour_position_breaks_a_saturated_tie(
        self, storage: LocalArtifactStorage
    ) -> None:
        """Every edge at similarity 1.0 from one seed: the scores are
        indistinguishable, but the artifact stores each row strongest-first,
        so position within the row is real signal that `book_id` discarded."""
        _write(storage, {0: [(8, 1.0), (7, 1.0), (6, 1.0), (5, 1.0)]})

        artifact = load_item_cf_artifact(storage, catalog=CATALOG)
        candidates = artifact.candidates_from_seeds([(10, 1.0)], count=4)

        # Row order, not ascending book_id.
        assert [book_id for book_id, _ in candidates] == [90, 80, 70, 60]

    def test_book_id_still_guarantees_determinism_when_all_else_ties(
        self, storage: LocalArtifactStorage
    ) -> None:
        """The final tiebreak has to stay, or the persisted batch stops being
        reproducible (rec-spec §18)."""
        _write(storage, {0: [(6, 1.0)], 1: [(5, 1.0)]})

        artifact = load_item_cf_artifact(storage, catalog=CATALOG)
        runs = {artifact.candidates_from_seeds([(10, 1.0), (20, 1.0)], count=2) for _ in range(5)}

        assert len(runs) == 1
        # Same score, same agreement (1 seed each), same position (0 each) —
        # so book_id decides, ascending.
        assert [book_id for book_id, _ in next(iter(runs))] == [60, 70]
