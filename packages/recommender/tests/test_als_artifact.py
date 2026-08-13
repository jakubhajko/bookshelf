"""ALS artifact and live-user fold-in (rec-spec §9).

The phase's required behaviours: a fold-in factor changes after a meaningful
profile change, the item factors themselves never retrain on a live mutation,
and candidate retrieval respects exclusion sets.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from book_recommender.artifacts import (
    CatalogSnapshot,
    LocalArtifactStorage,
    load_als_artifact,
    write_artifact,
    write_item_factors,
)
from book_recommender.artifacts.als import ITEM_FACTORS_FILENAME
from book_recommender.artifacts.numeric import save_array
from book_recommender.config import ALS
from book_recommender.exceptions import IncompatibleArtifactError

ITEM_COUNT = 20
ITEMS = [(10 * (index + 1), f"w-{index}") for index in range(ITEM_COUNT)]
CATALOG = CatalogSnapshot.from_rows(f"{ITEM_COUNT}:2026-08-13", ITEMS)
FACTOR_COUNT = 4


def _factors(seed: int = 0) -> np.ndarray:
    """Two clearly separated taste clusters, so "similar" is a fact about the
    fixture rather than a hope. Items 0-9 load on axis 0, items 10-19 on
    axis 1."""
    rng = np.random.default_rng(seed)
    factors = rng.normal(scale=0.01, size=(ITEM_COUNT, FACTOR_COUNT))
    factors[:10, 0] = 1.0
    factors[10:, 1] = 1.0
    return factors.astype(np.float32)


@pytest.fixture
def storage(tmp_path: Path) -> LocalArtifactStorage:
    return LocalArtifactStorage(tmp_path)


def _write(
    storage: LocalArtifactStorage,
    factors: np.ndarray | None = None,
    *,
    config: dict[str, object] | None = None,
    items: list[tuple[int, str]] | None = None,
) -> None:
    matrix = _factors() if factors is None else factors
    write_artifact(
        storage,
        ALS,
        model_version="20260813T120000Z",
        catalog_version=CATALOG.catalog_version,
        items=items if items is not None else ITEMS,
        payloads={ITEM_FACTORS_FILENAME: lambda path: write_item_factors(path, matrix)},
        config=config  # type: ignore[arg-type]
        if config is not None
        else {"factors": FACTOR_COUNT, "regularization": 0.05},
        training_transform_version="bx-positive-only-v1+no-neutral",
    )


# --- Loading ----------------------------------------------------------------


def test_artifact_round_trips(storage: LocalArtifactStorage) -> None:
    _write(storage)

    artifact = load_als_artifact(storage, catalog=CATALOG)

    assert artifact.item_count == ITEM_COUNT
    assert artifact.factor_count == FACTOR_COUNT
    assert artifact.regularization == pytest.approx(0.05)
    assert artifact.bundle.manifest.training_transform_version is not None


def test_factors_resolve_to_current_book_ids_after_a_reimport(
    storage: LocalArtifactStorage,
) -> None:
    _write(storage)
    reimported = CatalogSnapshot.from_rows(
        f"{ITEM_COUNT}:2026-09-01",
        [(500 + index, work_id) for index, (_, work_id) in enumerate(ITEMS)],
    )

    artifact = load_als_artifact(storage, catalog=reimported)

    assert artifact.book_ids.tolist()[:3] == [500, 501, 502]


def test_factor_rows_for_dropped_items_are_removed(storage: LocalArtifactStorage) -> None:
    """A factor row whose book left the catalog must not survive — it would
    score as a candidate the application cannot name."""
    _write(storage)
    thinned = CatalogSnapshot.from_rows("19:2026-09-01", [row for row in ITEMS if row[1] != "w-5"])

    artifact = load_als_artifact(storage, catalog=thinned)

    assert artifact.item_count == ITEM_COUNT - 1
    assert 60 not in artifact.book_ids.tolist()


def test_non_finite_factors_are_rejected(storage: LocalArtifactStorage) -> None:
    """A diverged training run yields NaN factors, which would score every
    item as NaN and silently empty the feed."""
    broken = _factors()
    broken[3, 1] = np.nan
    _write(storage, broken)

    with pytest.raises(IncompatibleArtifactError, match="non-finite"):
        load_als_artifact(storage, catalog=CATALOG)


def test_factor_width_disagreeing_with_the_manifest_is_rejected(
    storage: LocalArtifactStorage,
) -> None:
    _write(storage, config={"factors": 99, "regularization": 0.05})

    with pytest.raises(IncompatibleArtifactError, match="width 4"):
        load_als_artifact(storage, catalog=CATALOG)


def test_a_one_dimensional_payload_is_rejected(storage: LocalArtifactStorage) -> None:
    _write(storage)
    save_array(
        storage.resolve(ALS.directory, ITEM_FACTORS_FILENAME), np.zeros(20, dtype=np.float32)
    )
    manifest = storage.load_manifest(ALS.directory)
    storage.save_manifest(ALS.directory, manifest.model_copy(update={"files": ()}))

    with pytest.raises(IncompatibleArtifactError, match="2-D matrix"):
        load_als_artifact(storage, catalog=CATALOG)


# --- Fold-in (rec-spec §9.2) ------------------------------------------------


def test_fold_in_produces_a_factor_aligned_with_the_user_s_cluster(
    storage: LocalArtifactStorage,
) -> None:
    artifact = load_als_artifact(_written(storage), catalog=CATALOG)

    factor = artifact.fold_in([(10, 3.0), (20, 3.0), (30, 3.0)])

    assert factor is not None
    # Loaded on cluster-0 books, so axis 0 must dominate.
    assert factor[0] > factor[1]


def test_a_meaningful_profile_change_changes_the_fold_in_factor(
    storage: LocalArtifactStorage,
) -> None:
    """rec-spec §9.2's central requirement — the live factor tracks current
    durable evidence without the global model being retrained."""
    artifact = load_als_artifact(_written(storage), catalog=CATALOG)

    before = artifact.fold_in([(10, 3.0), (20, 3.0)])
    after = artifact.fold_in([(10, 3.0), (20, 3.0), (110, 5.0), (120, 5.0), (130, 5.0)])

    assert before is not None and after is not None
    assert not np.allclose(before, after)
    # The new evidence is all cluster-1, so that axis must have grown.
    assert after[1] > before[1]


def test_fold_in_does_not_mutate_or_retrain_item_factors(
    storage: LocalArtifactStorage,
) -> None:
    """ "Global ALS retraining is offline only" — a live user's evidence must
    leave the shipped item factors byte-identical."""
    artifact = load_als_artifact(_written(storage), catalog=CATALOG)
    snapshot = artifact.item_factors.copy()

    artifact.fold_in([(10, 3.0), (20, 4.0), (150, 5.0)])
    artifact.fold_in([(30, 1.0)])

    assert np.array_equal(artifact.item_factors, snapshot)


def test_fold_in_is_deterministic(storage: LocalArtifactStorage) -> None:
    artifact = load_als_artifact(_written(storage), catalog=CATALOG)
    preferences = [(10, 3.0), (40, 2.0), (170, 5.0)]

    first = artifact.fold_in(preferences)
    second = artifact.fold_in(preferences)
    assert first is not None and second is not None
    assert np.array_equal(first, second)


def test_stronger_confidence_pulls_the_factor_further(
    storage: LocalArtifactStorage,
) -> None:
    artifact = load_als_artifact(_written(storage), catalog=CATALOG)

    weak = artifact.fold_in([(10, 1.0)])
    strong = artifact.fold_in([(10, 10.0)])

    assert weak is not None and strong is not None
    assert strong[0] > weak[0]


def test_a_cold_user_gets_no_factor_rather_than_a_zero_vector(
    storage: LocalArtifactStorage,
) -> None:
    """Scoring against a zero vector would rank the catalog by nothing while
    looking like it worked, so the caller must be told to fall back."""
    artifact = load_als_artifact(_written(storage), catalog=CATALOG)

    assert artifact.fold_in([]) is None
    assert artifact.fold_in([(999999, 5.0)]) is None
    assert artifact.fold_in([(10, 0.0)]) is None


def test_unknown_books_in_a_profile_are_ignored_not_fatal(
    storage: LocalArtifactStorage,
) -> None:
    artifact = load_als_artifact(_written(storage), catalog=CATALOG)

    mixed = artifact.fold_in([(10, 3.0), (999999, 3.0)])
    clean = artifact.fold_in([(10, 3.0)])

    assert mixed is not None and clean is not None
    assert np.allclose(mixed, clean)


# --- Retrieval --------------------------------------------------------------


def test_top_candidates_are_ordered_and_limited(storage: LocalArtifactStorage) -> None:
    artifact = load_als_artifact(_written(storage), catalog=CATALOG)
    factor = artifact.fold_in([(10, 5.0), (20, 5.0)])
    assert factor is not None

    candidates = artifact.top_candidates(factor, count=5)

    assert len(candidates) == 5
    scores = [score for _, score in candidates]
    assert scores == sorted(scores, reverse=True)


def test_retrieval_respects_exclusion_sets(storage: LocalArtifactStorage) -> None:
    """Application-owned eligibility stays outside the engine, so the engine
    has to honour the exclusions it is handed (rec-spec §9.2)."""
    artifact = load_als_artifact(_written(storage), catalog=CATALOG)
    factor = artifact.fold_in([(10, 5.0), (20, 5.0)])
    assert factor is not None

    unfiltered = artifact.top_candidates(factor, count=5)
    excluded = frozenset(book_id for book_id, _ in unfiltered[:2])
    filtered = artifact.top_candidates(factor, count=5, excluded_book_ids=excluded)

    assert not excluded & {book_id for book_id, _ in filtered}


def test_exclusions_do_not_shorten_the_page(storage: LocalArtifactStorage) -> None:
    """Filtering before top-k selection rather than after means a
    heavily-excluded reader still gets a full page."""
    artifact = load_als_artifact(_written(storage), catalog=CATALOG)
    factor = artifact.fold_in([(10, 5.0)])
    assert factor is not None

    excluded = frozenset(book_id for book_id, _ in ITEMS[:10])
    candidates = artifact.top_candidates(factor, count=5, excluded_book_ids=excluded)

    assert len(candidates) == 5


def test_excluding_everything_returns_nothing(storage: LocalArtifactStorage) -> None:
    artifact = load_als_artifact(_written(storage), catalog=CATALOG)
    factor = artifact.fold_in([(10, 5.0)])
    assert factor is not None

    everything = frozenset(book_id for book_id, _ in ITEMS)

    assert artifact.top_candidates(factor, count=5, excluded_book_ids=everything) == ()
    assert artifact.top_candidates(factor, count=0) == ()


def test_requesting_more_than_the_catalog_returns_what_exists(
    storage: LocalArtifactStorage,
) -> None:
    artifact = load_als_artifact(_written(storage), catalog=CATALOG)
    factor = artifact.fold_in([(10, 5.0)])
    assert factor is not None

    assert len(artifact.top_candidates(factor, count=1000)) == ITEM_COUNT


def _written(storage: LocalArtifactStorage) -> LocalArtifactStorage:
    _write(storage)
    return storage
