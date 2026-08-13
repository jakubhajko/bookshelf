"""Content-embedding artifact and exact semantic retrieval (rec-spec §11)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from book_recommender.artifacts import (
    CatalogSnapshot,
    LocalArtifactStorage,
    load_content_artifact,
    write_artifact,
    write_embeddings,
)
from book_recommender.artifacts.content import EMBEDDINGS_FILENAME
from book_recommender.artifacts.numeric import save_array
from book_recommender.config import CONTENT
from book_recommender.exceptions import IncompatibleArtifactError

ITEM_COUNT = 20
ITEMS = [(10 * (index + 1), f"w-{index}") for index in range(ITEM_COUNT)]
CATALOG = CatalogSnapshot.from_rows(f"{ITEM_COUNT}:2026-08-13", ITEMS)
DIMENSION = 4


def _vectors(seed: int = 0) -> np.ndarray:
    """Two separated clusters: items 0-9 near axis 0, 10-19 near axis 1."""
    rng = np.random.default_rng(seed)
    matrix = rng.normal(scale=0.02, size=(ITEM_COUNT, DIMENSION))
    matrix[:10, 0] += 1.0
    matrix[10:, 1] += 1.0
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix.astype(np.float32)


@pytest.fixture
def storage(tmp_path: Path) -> LocalArtifactStorage:
    return LocalArtifactStorage(tmp_path)


def _write(
    storage: LocalArtifactStorage,
    vectors: np.ndarray | None = None,
    *,
    config: dict[str, object] | None = None,
) -> None:
    matrix = _vectors() if vectors is None else vectors
    write_artifact(
        storage,
        CONTENT,
        model_version="20260813T120000Z",
        catalog_version=CATALOG.catalog_version,
        items=ITEMS,
        payloads={EMBEDDINGS_FILENAME: lambda path: write_embeddings(path, matrix)},
        config=config  # type: ignore[arg-type]
        if config is not None
        else {
            "encoder": "Qwen/Qwen3-Embedding-0.6B",
            "encoder_revision": "abc123",
            "dimension": DIMENSION,
            "normalized": True,
            "prompt_version": "noprompt-v1",
            "text_template_version": "booktext-v1",
            "tags_version": "tags-v1",
        },
    )


# --- Loading ----------------------------------------------------------------


def test_artifact_round_trips_with_encoder_metadata(storage: LocalArtifactStorage) -> None:
    """rec-spec §11.1 requires the encoder identity to be recorded, because
    swapping encoders changes every vector."""
    _write(storage)

    artifact = load_content_artifact(storage, catalog=CATALOG)

    assert artifact.item_count == ITEM_COUNT
    assert artifact.dimension == DIMENSION
    assert artifact.encoder == "Qwen/Qwen3-Embedding-0.6B"
    config = artifact.bundle.manifest.config
    assert config["encoder_revision"] == "abc123"
    assert config["text_template_version"] == "booktext-v1"
    assert config["tags_version"] == "tags-v1"


def test_an_artifact_that_does_not_declare_normalization_is_refused(
    storage: LocalArtifactStorage,
) -> None:
    """Retrieval treats the dot product as cosine similarity. Unnormalized
    vectors would rank by magnitude — longer descriptions first — and look
    entirely plausible."""
    _write(storage, config={"dimension": DIMENSION, "normalized": False})

    with pytest.raises(IncompatibleArtifactError, match="normalized"):
        load_content_artifact(storage, catalog=CATALOG)


def test_unnormalized_vectors_are_detected_even_when_declared(
    storage: LocalArtifactStorage,
) -> None:
    """The tolerance accommodates float32 round-trip (the real artifact's
    rows land in [0.9972, 1.0026]); an artifact that skipped normalization is
    off by whole factors, which is what this catches."""
    unnormalized = _vectors() * 4.0
    _write(storage, unnormalized)

    with pytest.raises(IncompatibleArtifactError, match="unit-norm"):
        load_content_artifact(storage, catalog=CATALOG)


def test_float32_round_trip_noise_is_accepted(storage: LocalArtifactStorage) -> None:
    """Real encoder output is not exactly unit-norm. Measured on the live
    92,524-book artifact: rows span [0.9972, 1.0026]."""
    noisy = _vectors() * np.linspace(0.997, 1.003, ITEM_COUNT, dtype=np.float32)[:, None]
    _write(storage, noisy.astype(np.float32))

    artifact = load_content_artifact(storage, catalog=CATALOG)

    assert artifact.item_count == ITEM_COUNT


def test_a_dimension_mismatch_is_rejected(storage: LocalArtifactStorage) -> None:
    _write(storage, config={"dimension": 999, "normalized": True})

    with pytest.raises(IncompatibleArtifactError, match="512|999"):
        load_content_artifact(storage, catalog=CATALOG)


def test_non_finite_vectors_are_rejected(storage: LocalArtifactStorage) -> None:
    broken = _vectors()
    broken[3, 1] = np.nan
    _write(storage, broken)

    with pytest.raises(IncompatibleArtifactError, match="non-finite"):
        load_content_artifact(storage, catalog=CATALOG)


def test_a_one_dimensional_payload_is_rejected(storage: LocalArtifactStorage) -> None:
    _write(storage)
    save_array(
        storage.resolve(CONTENT.directory, EMBEDDINGS_FILENAME),
        np.zeros(ITEM_COUNT, dtype=np.float32),
    )
    manifest = storage.load_manifest(CONTENT.directory)
    storage.save_manifest(CONTENT.directory, manifest.model_copy(update={"files": ()}))

    with pytest.raises(IncompatibleArtifactError, match="2-D matrix"):
        load_content_artifact(storage, catalog=CATALOG)


def test_vectors_resolve_to_current_book_ids_after_a_reimport(
    storage: LocalArtifactStorage,
) -> None:
    _write(storage)
    reimported = CatalogSnapshot.from_rows(
        f"{ITEM_COUNT}:2026-09-01",
        [(500 + index, work_id) for index, (_, work_id) in enumerate(ITEMS)],
    )

    artifact = load_content_artifact(storage, catalog=reimported)

    assert artifact.book_ids.tolist()[:3] == [500, 501, 502]


def test_departed_books_lose_their_vectors(storage: LocalArtifactStorage) -> None:
    _write(storage)
    thinned = CatalogSnapshot.from_rows("19:2026-09-01", [r for r in ITEMS if r[1] != "w-5"])

    artifact = load_content_artifact(storage, catalog=thinned)

    assert artifact.item_count == ITEM_COUNT - 1
    assert artifact.vector_for(60) is None


def test_mmap_loading_works(storage: LocalArtifactStorage) -> None:
    """The embedding matrix is the artifact large enough to want it."""
    _write(storage)

    artifact = load_content_artifact(storage, catalog=CATALOG, mmap=True)

    assert artifact.item_count == ITEM_COUNT


# --- Retrieval --------------------------------------------------------------


def test_search_returns_the_query_s_own_cluster(storage: LocalArtifactStorage) -> None:
    artifact = load_content_artifact(_written(storage), catalog=CATALOG)
    query = artifact.vector_for(10)
    assert query is not None

    results = artifact.search(query, count=5)

    assert {book_id for book_id, _ in results} <= {row[0] for row in ITEMS[:10]}
    scores = [score for _, score in results]
    assert scores == sorted(scores, reverse=True)


def test_search_excludes_what_it_is_told_to(storage: LocalArtifactStorage) -> None:
    artifact = load_content_artifact(_written(storage), catalog=CATALOG)
    query = artifact.vector_for(10)
    assert query is not None

    unfiltered = artifact.search(query, count=5)
    excluded = frozenset(book_id for book_id, _ in unfiltered[:2])
    filtered = artifact.search(query, count=5, excluded_book_ids=excluded)

    assert not excluded & {book_id for book_id, _ in filtered}
    # Filtering before top-K, so the page stays full.
    assert len(filtered) == 5


def test_search_is_exact_cosine(storage: LocalArtifactStorage) -> None:
    """No index, no approximation — the score must equal the dot product."""
    artifact = load_content_artifact(_written(storage), catalog=CATALOG)
    query = artifact.vector_for(10)
    assert query is not None

    top_id, top_score = artifact.search(query, count=1)[0]
    expected = float(np.asarray(artifact.vector_for(top_id)) @ np.asarray(query))

    assert top_score == pytest.approx(expected, abs=1e-5)
    assert artifact.similarity(10, top_id) == pytest.approx(top_score, abs=1e-5)


def test_batched_search_matches_individual_searches(storage: LocalArtifactStorage) -> None:
    artifact = load_content_artifact(_written(storage), catalog=CATALOG)
    first, second = artifact.vector_for(10), artifact.vector_for(110)
    assert first is not None and second is not None

    batched = artifact.search_many(np.vstack([first, second]), count=3)

    assert batched[0] == artifact.search(first, count=3)
    assert batched[1] == artifact.search(second, count=3)


def test_vectors_for_skips_unknown_books_rather_than_raising(
    storage: LocalArtifactStorage,
) -> None:
    """A reader's shelf can legitimately contain a book added after the last
    embedding build; a profile should degrade, not fail."""
    artifact = load_content_artifact(_written(storage), catalog=CATALOG)

    vectors, resolved = artifact.vectors_for([10, 999999, 20])

    assert resolved == [10, 20]
    assert vectors.shape == (2, DIMENSION)


def test_vectors_for_handles_a_completely_unknown_set(
    storage: LocalArtifactStorage,
) -> None:
    artifact = load_content_artifact(_written(storage), catalog=CATALOG)

    vectors, resolved = artifact.vectors_for([999999])

    assert resolved == []
    assert vectors.shape == (0, DIMENSION)


def test_excluding_everything_returns_nothing(storage: LocalArtifactStorage) -> None:
    artifact = load_content_artifact(_written(storage), catalog=CATALOG)
    query = artifact.vector_for(10)
    assert query is not None

    everything = frozenset(book_id for book_id, _ in ITEMS)

    assert artifact.search(query, count=5, excluded_book_ids=everything) == ()
    assert artifact.search(query, count=0) == ()


def test_similarity_between_clusters_is_lower_than_within(
    storage: LocalArtifactStorage,
) -> None:
    artifact = load_content_artifact(_written(storage), catalog=CATALOG)

    within = artifact.similarity(10, 20)
    across = artifact.similarity(10, 110)

    assert within is not None and across is not None
    assert within > across


def test_similarity_of_an_unknown_book_is_none(storage: LocalArtifactStorage) -> None:
    artifact = load_content_artifact(_written(storage), catalog=CATALOG)

    assert artifact.similarity(10, 999999) is None


def _written(storage: LocalArtifactStorage) -> LocalArtifactStorage:
    _write(storage)
    return storage
