"""A small, fully-known world the generator tests assert against.

Twelve books in three clearly separated taste groups, and every artifact
built over the *same* grouping, so "these two books are similar" is a fact
about the fixture rather than something the test hopes the maths produced:

===========  =======  ==================================================
Books        Group    Shared by every artifact
===========  =======  ==================================================
101-104      fantasy  content axis 0, ALS factor 0, CF/source neighbours
105-108      scifi    content axis 1, ALS factor 1, CF/source neighbours
109-112      romance  content axis 2, ALS factor 2, CF/source neighbours
===========  =======  ==================================================

Artifacts are written to disk and loaded back through the real loaders
rather than constructed by hand, so the tests exercise the same validation
path that serving does — a fixture that bypassed the loader could not catch
a generator that depends on something the loader normalizes.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import numpy as np

from book_recommender.artifacts import (
    AlsArtifact,
    CatalogSnapshot,
    ContentEmbeddings,
    ItemCfNeighbors,
    ItemMetadataTable,
    LocalArtifactStorage,
    PopularityArtifact,
    SourceSimilarityGraph,
    load_als_artifact,
    load_content_artifact,
    load_item_cf_artifact,
    load_item_metadata_artifact,
    load_popularity_artifact,
    load_source_similarity_artifact,
    write_artifact,
)
from book_recommender.artifacts.als import ITEM_FACTORS_FILENAME, write_item_factors
from book_recommender.artifacts.content import EMBEDDINGS_FILENAME, write_embeddings
from book_recommender.artifacts.item_cf import NEIGHBORS_FILENAME, write_item_cf_neighbors
from book_recommender.artifacts.item_metadata import METADATA_FILENAME, write_item_metadata
from book_recommender.artifacts.popularity import SCORES_FILENAME, write_popularity_scores
from book_recommender.artifacts.source_similarity import (
    GRAPH_FILENAME,
    write_source_similarity_graph,
)
from book_recommender.config import (
    ALS,
    CONTENT,
    ITEM_CF,
    ITEM_METADATA,
    POPULARITY,
    SOURCE_SIMILARITY,
)
from book_recommender.contracts.context import (
    RatingSnapshot,
    SavedBookSnapshot,
    TasteSeedSnapshot,
    UserContext,
)
from book_recommender.profiling import (
    InterestCluster,
    InterestProfile,
    ProfileStrategy,
    ShelfProfile,
)

FANTASY = (101, 102, 103, 104)
SCIFI = (105, 106, 107, 108)
ROMANCE = (109, 110, 111, 112)
ALL_BOOKS: tuple[int, ...] = FANTASY + SCIFI + ROMANCE
GROUPS: tuple[tuple[int, ...], ...] = (FANTASY, SCIFI, ROMANCE)

ITEMS: list[tuple[int, str]] = [(book_id, f"w-{book_id}") for book_id in ALL_BOOKS]
CATALOG = CatalogSnapshot.from_rows(f"{len(ITEMS)}:2026-08-13", ITEMS)
MODEL_VERSION = "20260813T120000Z"
CATALOG_VERSION = CATALOG.catalog_version

USER_ID = UUID("00000000-0000-0000-0000-0000000000aa")
SHELF_FANTASY = UUID("00000000-0000-0000-0000-0000000000f1")
SHELF_SCIFI = UUID("00000000-0000-0000-0000-0000000000f2")

DIMENSION = 8


def _group_of(book_id: int) -> int:
    for index, group in enumerate(GROUPS):
        if book_id in group:
            return index
    raise AssertionError(f"{book_id} is not in the fixture world")


#: How much of each book's vector is its own rather than its group's.
#: Chosen so within-group cosine lands near 0.74 and cross-group at 0.0 —
#: books in a group are recognisably alike without being *duplicates*.
#:
#: The first version of this fixture gave every book in a group the same
#: axis plus a 0.01 jitter, making them 0.999 alike. That is not what a
#: taste group looks like, and it silently fired the reranker's
#: near-duplicate penalty on every second candidate, which hid real
#: ordering behaviour behind a constant 1.0 penalty.
_BOOK_AXIS_WEIGHT = 0.6


def group_vectors() -> np.ndarray:
    """Unit-norm vectors: one shared axis per taste group, plus one axis
    unique to each book so members of a group are similar but distinct."""
    vectors = np.zeros((len(ALL_BOOKS), DIMENSION), dtype=np.float32)
    for row, book_id in enumerate(ALL_BOOKS):
        group = _group_of(book_id)
        vectors[row, group] = 1.0
        vectors[row, len(GROUPS) + GROUPS[group].index(book_id)] = _BOOK_AXIS_WEIGHT
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return (vectors / norms).astype(np.float32)


def write_content(storage: LocalArtifactStorage, vectors: np.ndarray | None = None) -> None:
    matrix = group_vectors() if vectors is None else vectors
    write_artifact(
        storage,
        CONTENT,
        model_version=MODEL_VERSION,
        catalog_version=CATALOG_VERSION,
        items=ITEMS,
        payloads={EMBEDDINGS_FILENAME: lambda path: write_embeddings(path, matrix)},
        config={
            "encoder": "fixture-encoder",
            "dimension": int(matrix.shape[1]),
            "normalized": True,
        },
        trained_at=datetime(2026, 8, 13, tzinfo=UTC),
    )


def write_als(storage: LocalArtifactStorage) -> None:
    """Item factors on the same three-group structure, so a reader folded in
    from fantasy books scores fantasy books highest."""
    factors = np.zeros((len(ALL_BOOKS), 3), dtype=np.float32)
    for row, book_id in enumerate(ALL_BOOKS):
        factors[row, _group_of(book_id)] = 1.0
        # A small within-group gradient, so top_candidates has a defined
        # order instead of twelve identical scores.
        factors[row, _group_of(book_id)] += 0.01 * (book_id % 10)
    write_artifact(
        storage,
        ALS,
        model_version=MODEL_VERSION,
        catalog_version=CATALOG_VERSION,
        items=ITEMS,
        payloads={ITEM_FACTORS_FILENAME: lambda path: write_item_factors(path, factors)},
        config={"factors": 3, "regularization": 0.05},
        trained_at=datetime(2026, 8, 13, tzinfo=UTC),
    )


def _within_group_csr() -> tuple[list[int], list[int], list[float]]:
    """Every book's neighbours are the rest of its own group, strongest
    first by index order."""
    indptr = [0]
    indices: list[int] = []
    scores: list[float] = []
    for book_id in ALL_BOOKS:
        group = GROUPS[_group_of(book_id)]
        peers = [peer for peer in group if peer != book_id]
        for offset, peer in enumerate(peers):
            indices.append(ALL_BOOKS.index(peer))
            scores.append(1.0 - 0.1 * offset)
        indptr.append(len(indices))
    return indptr, indices, scores


def write_item_cf(storage: LocalArtifactStorage) -> None:
    indptr, indices, scores = _within_group_csr()
    write_artifact(
        storage,
        ITEM_CF,
        model_version=MODEL_VERSION,
        catalog_version=CATALOG_VERSION,
        items=ITEMS,
        payloads={
            NEIGHBORS_FILENAME: lambda path: write_item_cf_neighbors(
                path, indptr=indptr, neighbor_indices=indices, scores=scores
            )
        },
        config={"similarity": "bm25", "top_k": 3},
        trained_at=datetime(2026, 8, 13, tzinfo=UTC),
    )


def write_source_graph(storage: LocalArtifactStorage) -> None:
    indptr, indices, _ = _within_group_csr()
    ranks: list[int] = []
    for start, end in zip(indptr[:-1], indptr[1:], strict=True):
        # 0-based within each row, matching the live graph (ranks span 0-17).
        ranks.extend(range(end - start))
    write_artifact(
        storage,
        SOURCE_SIMILARITY,
        model_version=MODEL_VERSION,
        catalog_version=CATALOG_VERSION,
        items=ITEMS,
        payloads={
            GRAPH_FILENAME: lambda path: write_source_similarity_graph(
                path,
                indptr=indptr,
                neighbor_indices=indices,
                ranks=ranks,
                source_codes=[0] * len(indices),
            )
        },
        config={"sources": ["goodreads"]},
        trained_at=datetime(2026, 8, 13, tzinfo=UTC),
    )


def write_popularity(storage: LocalArtifactStorage) -> None:
    """Descending scores in catalog order, so the ranking is 101 first."""
    scores = [1.0 - 0.01 * index for index in range(len(ALL_BOOKS))]
    write_artifact(
        storage,
        POPULARITY,
        model_version=MODEL_VERSION,
        catalog_version=CATALOG_VERSION,
        items=ITEMS,
        payloads={SCORES_FILENAME: lambda path: write_popularity_scores(path, scores)},
        trained_at=datetime(2026, 8, 13, tzinfo=UTC),
    )


#: Titles and authors chosen so the reranker's controls have something real
#: to act on: two books share an author *and* a series inside the fantasy
#: group, and 104 is a deliberate near-duplicate of 103 by title.
GENRE_BY_GROUP = ("fantasy", "science fiction", "romance")
AUTHORS = {
    101: "Alpha Author",
    102: "Alpha Author",
    103: "Beta Author",
    104: "Beta Author",
    105: "Gamma Author",
    106: "Gamma Author",
    107: "Delta Author",
    108: "Epsilon Author",
    109: "Zeta Author",
    110: "Zeta Author",
    111: "Eta Author",
    112: "Theta Author",
}
TITLES = {
    101: "First Fantasy (Alpha Saga, #1)",
    102: "Second Fantasy (Alpha Saga, #2)",
    103: "Third Fantasy",
    104: "Fourth Fantasy",
    105: "First Scifi (Gamma Cycle, #1)",
    106: "Second Scifi (Gamma Cycle, #2)",
    107: "Third Scifi",
    108: "Fourth Scifi",
    109: "First Romance",
    110: "Second Romance",
    111: "Third Romance",
    112: "Fourth Romance",
}


def write_metadata(storage: LocalArtifactStorage) -> None:
    genre_vocab = list(GENRE_BY_GROUP)
    write_artifact(
        storage,
        ITEM_METADATA,
        model_version=MODEL_VERSION,
        catalog_version=CATALOG_VERSION,
        items=ITEMS,
        payloads={
            METADATA_FILENAME: lambda path: write_item_metadata(
                path,
                titles=[TITLES[book_id] for book_id in ALL_BOOKS],
                authors=[AUTHORS[book_id] for book_id in ALL_BOOKS],
                genre_codes=[_group_of(book_id) for book_id in ALL_BOOKS],
                genre_vocab=genre_vocab,
            )
        },
        trained_at=datetime(2026, 8, 13, tzinfo=UTC),
    )


def build_all(tmp_path: Path) -> LocalArtifactStorage:
    storage = LocalArtifactStorage(tmp_path)
    write_content(storage)
    write_als(storage)
    write_item_cf(storage)
    write_source_graph(storage)
    write_popularity(storage)
    write_metadata(storage)
    return storage


def load_content(storage: LocalArtifactStorage) -> ContentEmbeddings:
    return load_content_artifact(storage, catalog=CATALOG)


def load_als(storage: LocalArtifactStorage) -> AlsArtifact:
    return load_als_artifact(storage, catalog=CATALOG)


def load_item_cf(storage: LocalArtifactStorage) -> ItemCfNeighbors:
    return load_item_cf_artifact(storage, catalog=CATALOG)


def load_source_graph(storage: LocalArtifactStorage) -> SourceSimilarityGraph:
    return load_source_similarity_artifact(storage, catalog=CATALOG)


def load_popularity(storage: LocalArtifactStorage) -> PopularityArtifact:
    return load_popularity_artifact(storage, catalog=CATALOG)


def load_metadata(storage: LocalArtifactStorage) -> ItemMetadataTable:
    return load_item_metadata_artifact(storage, catalog=CATALOG)


def user_context(
    *,
    ratings: Sequence[tuple[int, int]] = (),
    saved: Sequence[tuple[int, UUID]] = (),
    taste_seeds: Sequence[int] = (),
    not_interested: Sequence[int] = (),
    profile_version: str = "fixture-profile-v1",
) -> UserContext:
    when = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    saved_books = tuple(
        SavedBookSnapshot(book_id=book_id, shelf_id=shelf_id, added_at=when)
        for book_id, shelf_id in saved
    )
    return UserContext(
        user_id=USER_ID,
        ratings=tuple(
            RatingSnapshot(book_id=book_id, rating_value=value, rated_at=when)
            for book_id, value in ratings
        ),
        saved_book_ids=frozenset(book_id for book_id, _ in saved),
        saved_books=saved_books,
        shelf_ids=tuple({shelf_id for _, shelf_id in saved}),
        not_interested_book_ids=frozenset(not_interested),
        recent_interactions=(),
        shelf_summaries=(),
        taste_seeds=tuple(
            TasteSeedSnapshot(book_id=book_id, source="onboarding", selected_at=when)
            for book_id in taste_seeds
        ),
        profile_version=profile_version,
    )


def _unit(axis: int) -> np.ndarray:
    vector = np.zeros(DIMENSION, dtype=np.float64)
    vector[axis] = 1.0
    return vector


def interest_profile(
    *,
    clusters: Sequence[tuple[str, int, tuple[int, ...], float]] = (),
    shelves: Sequence[tuple[UUID, int, tuple[int, ...], float]] = (),
    strategy: ProfileStrategy = ProfileStrategy.CLUSTERED,
) -> InterestProfile:
    """Build a profile from ``(id, group_axis, members, weight)`` tuples, so
    a test states which taste each query points at instead of hand-rolling
    vectors."""
    return InterestProfile(
        strategy=strategy,
        clusters=tuple(
            InterestCluster(
                interest_id=interest_id,
                query_vector=_unit(axis),
                representative_book_id=members[0],
                member_book_ids=members,
                weight=weight,
                coherence=0.9,
                sources=("shelf_save",),
            )
            for interest_id, axis, members, weight in clusters
        ),
        shelves=tuple(
            ShelfProfile(
                shelf_id=str(shelf_id),
                query_vector=_unit(axis),
                member_book_ids=members,
                representative_book_id=members[0],
                weight=weight,
            )
            for shelf_id, axis, members, weight in shelves
        ),
        evidence_count=sum(len(members) for _, _, members, _ in clusters),
    )
