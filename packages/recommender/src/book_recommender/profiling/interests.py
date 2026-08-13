"""Semantic user profiling: explicit shelves and inferred interests
(rec-spec §12, §13; ADR-0016).

Pure: no ORM, no FastAPI, no I/O, no clock. It takes evidence the
application has already gathered plus the content-embedding artifact, and
returns a profile. That purity is what lets the inspection CLI (rec-spec
§13) call *exactly* the same code the recommender serves from, which the
spec requires: "Do not create a second debug-only clustering
implementation."

Two halves, per rec-spec §12:

- **explicit shelf profiles** — a reader has told us these belong together,
  so no inference is needed; each shelf becomes one weighted normalized
  vector.
- **inferred interests** — clustering positive evidence, because a reader's
  tastes are usually several things and a single global centroid would
  average "medieval history" and "space opera" into a vector describing
  neither.

The fallback ladder in :func:`build_interest_profile` is rec-spec §12.2's,
implemented literally, because the interesting cases are the sparse ones:
most real readers have very little evidence, and fabricating cluster
structure from three books would produce confident nonsense.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

import numpy as np
import numpy.typing as npt

from book_recommender.config import INTEREST_PROFILE_DEFAULT, InterestProfileConfig
from book_recommender.profiling.clustering import (
    average_linkage_clusters,
    cosine_similarity_matrix,
    medoid_index,
    weighted_centroid,
)

#: Cap on member ids and label terms carried in a summary, so diagnostics
#: cannot grow unbounded with a heavy reader's library (rec-spec §13).
MAX_SUMMARY_MEMBERS = 20
MAX_SUMMARY_TERMS = 6


class ProfileStrategy(StrEnum):
    """Which branch of rec-spec §12.2's ladder produced this profile.

    Recorded rather than inferred, because "this reader has one interest"
    and "this reader had too little evidence to cluster" look identical from
    the outside and mean completely different things.
    """

    NONE = "none"
    INDIVIDUAL_BOOKS = "individual_books"
    SINGLE_CLUSTER = "single_cluster"
    CLUSTERED = "clustered"
    FALLBACK_CENTROID = "fallback_centroid"


@dataclass(frozen=True)
class EvidenceItem:
    """One positive signal about one book.

    ``weight`` is evidence strength from the application's signal policy
    (rec-spec §7.1) — a 10/10 rating counts more than an open. ``source`` is
    kept so a summary can answer "why is this book here?" in words.
    """

    book_id: int
    weight: float
    source: str


@dataclass(frozen=True)
class InterestCluster:
    """One inferred interest, with both its query vector and its evidence."""

    interest_id: str
    query_vector: npt.NDArray[np.float64]
    representative_book_id: int
    member_book_ids: tuple[int, ...]
    weight: float
    coherence: float
    sources: tuple[str, ...]

    @property
    def member_count(self) -> int:
        return len(self.member_book_ids)


@dataclass(frozen=True)
class ShelfProfile:
    """rec-spec §12.1: one normalized weighted vector per shelf."""

    shelf_id: str
    query_vector: npt.NDArray[np.float64]
    member_book_ids: tuple[int, ...]
    representative_book_id: int
    weight: float

    @property
    def member_count(self) -> int:
        return len(self.member_book_ids)


@dataclass(frozen=True)
class InterestProfile:
    """Everything the semantic generators need, plus why it looks this way."""

    strategy: ProfileStrategy
    clusters: tuple[InterestCluster, ...] = ()
    shelves: tuple[ShelfProfile, ...] = ()
    #: Evidence that had no embedding — books added since the last content
    #: build. Reported rather than silently dropped.
    unembedded_book_ids: tuple[int, ...] = ()
    evidence_count: int = 0
    config: InterestProfileConfig = field(default=INTEREST_PROFILE_DEFAULT)

    @property
    def is_empty(self) -> bool:
        return not self.clusters and not self.shelves


class EmbeddingLookup(Protocol):
    """The subset of the content artifact this module needs.

    A structural protocol rather than a direct dependency on
    ``ContentEmbeddings``: profiling is pure logic over vectors, and taking
    the narrow interface keeps it testable with a dozen hand-written vectors
    instead of a 190 MB artifact.
    """

    def vectors_for(self, book_ids: Sequence[int]) -> tuple[npt.NDArray[np.float32], list[int]]: ...


def build_interest_profile(
    evidence: Sequence[EvidenceItem],
    embeddings: EmbeddingLookup,
    *,
    config: InterestProfileConfig = INTEREST_PROFILE_DEFAULT,
) -> InterestProfile:
    """Infer a reader's interests from positive evidence (rec-spec §12.2).

    The ladder, in order:

    - **0 items** → no semantic profile at all. Not an empty cluster, not a
      zero vector: the caller must fall back to non-semantic generators.
    - **1-2 items** → the books themselves are the queries. Clustering two
      books says nothing that the books do not already say.
    - **enough items** → threshold clustering, keeping clusters of at least
      ``min_cluster_size``.
    - **only singletons survive** → the thresholding found no structure, so
      fall back to the strongest individual books rather than presenting
      noise as interests.
    """
    ranked = _rank_evidence(evidence, config.max_evidence_items)
    if not ranked:
        return InterestProfile(strategy=ProfileStrategy.NONE, config=config)

    vectors, resolved_ids = embeddings.vectors_for([item.book_id for item in ranked])
    by_id = {item.book_id: item for item in ranked}
    items = [by_id[book_id] for book_id in resolved_ids]
    unembedded = tuple(item.book_id for item in ranked if item.book_id not in set(resolved_ids))

    if not items:
        return InterestProfile(
            strategy=ProfileStrategy.NONE,
            unembedded_book_ids=unembedded,
            evidence_count=len(ranked),
            config=config,
        )

    matrix = np.asarray(vectors, dtype=np.float64)

    if len(items) < config.min_items_for_clustering:
        return InterestProfile(
            strategy=ProfileStrategy.INDIVIDUAL_BOOKS,
            clusters=tuple(
                _cluster_from_members(matrix, items, (index,), position)
                for position, index in enumerate(range(len(items)))
            ),
            shelves=(),
            unembedded_book_ids=unembedded,
            evidence_count=len(ranked),
            config=config,
        )

    similarity = cosine_similarity_matrix(matrix)
    groups = average_linkage_clusters(similarity, threshold=config.merge_threshold)
    meaningful = [group for group in groups if len(group) >= config.min_cluster_size]

    if not meaningful:
        # Thresholding found no structure. rec-spec §12.2: "fall back to a
        # small set of strongest individual query books ... rather than
        # fabricating cluster structure".
        strongest = tuple(range(min(len(items), config.max_interests)))
        return InterestProfile(
            strategy=ProfileStrategy.FALLBACK_CENTROID,
            clusters=tuple(
                _cluster_from_members(matrix, items, (index,), position)
                for position, index in enumerate(strongest)
            ),
            unembedded_book_ids=unembedded,
            evidence_count=len(ranked),
            config=config,
        )

    # Strongest interests first, so a truncated profile keeps what matters.
    ordered = sorted(
        meaningful,
        key=lambda group: (-sum(items[index].weight for index in group), group[0]),
    )[: config.max_interests]

    clusters = tuple(
        _cluster_from_members(matrix, items, group, position)
        for position, group in enumerate(ordered)
    )
    strategy = ProfileStrategy.SINGLE_CLUSTER if len(clusters) == 1 else ProfileStrategy.CLUSTERED
    return InterestProfile(
        strategy=strategy,
        clusters=clusters,
        unembedded_book_ids=unembedded,
        evidence_count=len(ranked),
        config=config,
    )


def build_shelf_profiles(
    shelf_members: Mapping[str, Sequence[EvidenceItem]],
    embeddings: EmbeddingLookup,
) -> tuple[ShelfProfile, ...]:
    """One normalized weighted vector per shelf (rec-spec §12.1).

    No clustering: the reader has already declared these books to belong
    together, and second-guessing that with an inference step would discard
    the most reliable signal in the system.
    """
    profiles: list[ShelfProfile] = []
    for shelf_id in sorted(shelf_members):
        items = list(shelf_members[shelf_id])
        if not items:
            continue
        vectors, resolved_ids = embeddings.vectors_for([item.book_id for item in items])
        if not resolved_ids:
            continue
        by_id = {item.book_id: item for item in items}
        resolved = [by_id[book_id] for book_id in resolved_ids]
        matrix = np.asarray(vectors, dtype=np.float64)
        weights = np.asarray([item.weight for item in resolved], dtype=np.float64)
        similarity = cosine_similarity_matrix(matrix)
        representative = medoid_index(similarity)
        profiles.append(
            ShelfProfile(
                shelf_id=shelf_id,
                query_vector=weighted_centroid(matrix, weights),
                member_book_ids=tuple(item.book_id for item in resolved),
                representative_book_id=resolved[representative].book_id,
                weight=float(weights.sum()),
            )
        )
    return tuple(profiles)


def _rank_evidence(evidence: Sequence[EvidenceItem], limit: int) -> list[EvidenceItem]:
    """Strongest evidence first, capped (rec-spec §12.2's bounded input).

    One book can arrive from several signals — saved *and* rated 9 — and
    they are collapsed to the strongest rather than summed, so a book cannot
    dominate a cluster merely by appearing in several places (rec-spec
    §7.1's "avoid uncontrolled double-counting").
    """
    strongest: dict[int, EvidenceItem] = {}
    for item in evidence:
        if item.weight <= 0:
            continue
        current = strongest.get(item.book_id)
        if current is None or item.weight > current.weight:
            strongest[item.book_id] = item
    return sorted(strongest.values(), key=lambda item: (-item.weight, item.book_id))[:limit]


def _cluster_from_members(
    matrix: npt.NDArray[np.float64],
    items: Sequence[EvidenceItem],
    members: Sequence[int],
    position: int,
) -> InterestCluster:
    rows = matrix[list(members)]
    weights = np.asarray([items[index].weight for index in members], dtype=np.float64)
    similarity = cosine_similarity_matrix(rows)
    representative = medoid_index(similarity)

    # Mean off-diagonal similarity: how much of a single thing this interest
    # actually is. A singleton is trivially coherent, hence 1.0.
    if len(members) > 1:
        off_diagonal = similarity[~np.eye(len(members), dtype=bool)]
        coherence = float(off_diagonal.mean())
    else:
        coherence = 1.0

    return InterestCluster(
        interest_id=f"i{position}",
        query_vector=weighted_centroid(rows, weights),
        representative_book_id=items[members[representative]].book_id,
        member_book_ids=tuple(items[index].book_id for index in members),
        weight=float(weights.sum()),
        coherence=coherence,
        sources=tuple(sorted({items[index].source for index in members})),
    )


def query_vector_for(
    cluster: InterestCluster,
    embeddings: EmbeddingLookup,
    *,
    config: InterestProfileConfig = INTEREST_PROFILE_DEFAULT,
) -> npt.NDArray[np.float64]:
    """The vector to retrieve with, honouring ``query_strategy``.

    rec-spec §12.2 requires centroid-vs-medoid to stay configurable "for
    future offline comparison", so the choice is made here rather than baked
    into the cluster.
    """
    if config.query_strategy != "medoid":
        return cluster.query_vector
    vectors, resolved = embeddings.vectors_for([cluster.representative_book_id])
    if not resolved:
        return cluster.query_vector
    return np.asarray(vectors[0], dtype=np.float64)
