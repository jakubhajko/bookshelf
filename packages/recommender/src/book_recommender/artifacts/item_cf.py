"""Item-item collaborative-filtering artifact (rec-spec §10, ADR-0014).

Top-K nearest neighbours per item, precomputed offline and stored as CSR
over the shared model-item-index space — structurally the same shape as the
source-similarity graph, with one deliberate difference: these edges carry a
**similarity score**, because unlike Goodreads' ordered list this one was
computed and the magnitude is meaningful. Fusion (ADR-0017) may use either
the rank or the score; the artifact keeps both available rather than
deciding for it.

Runtime behaviour is seeding, not inference (rec-spec §10): take the live
user's positively-interacted books, look up their precomputed neighbours,
and aggregate. A profile change alters *which seeds* are used and how they
are weighted — it never retrains anything, which is the property
``test_seeding_does_not_depend_on_training`` pins down.

Aggregation across seeds is additive over ``seed_weight × similarity``, and
that is a real choice: rec-spec §7.1 warns against "uncontrolled
double-counting" for a book with multiple positive signals. Additive
aggregation here is intentional and bounded — it means a candidate reachable
from several of a reader's books outranks one reachable from a single book,
which is the entire point of item-item CF. The signal-policy cap belongs on
the *seed weights* the caller supplies, not on the neighbour sum.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from book_recommender.artifacts.loader import ArtifactBundle, load_artifact_bundle
from book_recommender.artifacts.local_storage import LocalArtifactStorage
from book_recommender.artifacts.mapping import CatalogSnapshot
from book_recommender.artifacts.numeric import (
    load_arrays,
    require_float_array,
    require_int_array,
    save_arrays,
)
from book_recommender.config import ITEM_CF
from book_recommender.exceptions import IncompatibleArtifactError

NEIGHBORS_FILENAME = "neighbors.npz"

SIMILARITY_CONFIG_KEY = "similarity"
TOP_K_CONFIG_KEY = "top_k"

_INDPTR = "indptr"
_NEIGHBOR_INDICES = "neighbor_indices"
_SCORES = "scores"


@dataclass(frozen=True)
class ItemNeighbor:
    book_id: int
    score: float


def write_item_cf_neighbors(
    path: Path,
    *,
    indptr: Sequence[int],
    neighbor_indices: Sequence[int],
    scores: Sequence[float],
) -> None:
    """Builder-side writer; columns are in model-item-index space, each row's
    neighbours ordered strongest-first."""
    save_arrays(
        path,
        {
            _INDPTR: np.asarray(indptr, dtype=np.int64),
            _NEIGHBOR_INDICES: np.asarray(neighbor_indices, dtype=np.int32),
            _SCORES: np.asarray(scores, dtype=np.float32),
        },
    )


@dataclass(frozen=True)
class ItemCfNeighbors:
    """Neighbour lookup keyed on current catalog ``book_id``."""

    _indptr: npt.NDArray[np.int64]
    _neighbor_book_ids: npt.NDArray[np.int64]
    _scores: npt.NDArray[np.float64]
    _row_by_book_id: Mapping[int, int]
    similarity: str
    top_k: int
    bundle: ArtifactBundle

    @property
    def item_count(self) -> int:
        return len(self._row_by_book_id)

    @property
    def edge_count(self) -> int:
        return int(self._neighbor_book_ids.size)

    @property
    def model_version(self) -> str:
        return self.bundle.manifest.model_version

    def neighbors(self, book_id: int, *, limit: int | None = None) -> tuple[ItemNeighbor, ...]:
        start, end = self._slice(book_id, limit)
        return tuple(
            ItemNeighbor(book_id=int(self._neighbor_book_ids[i]), score=float(self._scores[i]))
            for i in range(start, end)
        )

    def has_neighbors(self, book_id: int) -> bool:
        start, end = self._slice(book_id, None)
        return end > start

    def candidates_from_seeds(
        self,
        seeds: Sequence[tuple[int, float]],
        *,
        count: int,
        excluded_book_ids: frozenset[int] = frozenset(),
        neighbors_per_seed: int | None = None,
    ) -> tuple[tuple[int, float], ...]:
        """Aggregate neighbours of ``(book_id, seed_weight)`` into candidates.

        The seeds themselves are always excluded from their own results — a
        reader's own book coming back as a recommendation is never useful,
        and application eligibility would drop it later anyway. Doing it here
        keeps the returned count honest.
        """
        if count <= 0 or not seeds:
            return ()

        totals: dict[int, float] = {}
        #: How many distinct seeds reached this candidate.
        agreement: dict[int, int] = {}
        #: Best (smallest) position within any seed's neighbour row.
        best_position: dict[int, int] = {}
        seed_ids = {book_id for book_id, _ in seeds}
        for seed_book_id, weight in seeds:
            if weight <= 0.0:
                continue
            start, end = self._slice(seed_book_id, neighbors_per_seed)
            for offset in range(start, end):
                candidate = int(self._neighbor_book_ids[offset])
                if candidate in seed_ids or candidate in excluded_book_ids:
                    continue
                totals[candidate] = totals.get(candidate, 0.0) + weight * float(
                    self._scores[offset]
                )
                agreement[candidate] = agreement.get(candidate, 0) + 1
                position = offset - start
                if position < best_position.get(candidate, position + 1):
                    best_position[candidate] = position

        if not totals:
            return ()
        # Score desc, then agreement desc, then neighbour position asc, then
        # book_id.
        #
        # The middle two replace what used to be a straight fall-through to
        # `book_id` — catalog insertion order, which RRF would then read as
        # rank and treat as evidence (ADR-0017). A book reachable from
        # several of the reader's books is better evidence than one
        # reachable from a single book, which is the premise of item-item
        # CF; and rows are stored strongest-first, so position within a row
        # is real signal too. `book_id` stays last because determinism must
        # still be guaranteed when everything else ties (rec-spec §18).
        #
        # **This is not what fixed risk #111**, and the distinction matters
        # to anyone tempted to tune here. R6 predicted the saturated-rank
        # problem could be solved at this aggregation. R9 measured that it
        # could not: the dominant tie group came from a *single* seed's row,
        # so agreement was uniformly 1 and position was already the order
        # being complained about. The cause was upstream — edges whose only
        # evidence was one reader owning both books — and the fix is the
        # builder's `min_support` filter (`cf_training.train_item_neighbors`).
        # These tiebreaks handle the multi-seed ties that remain, which on
        # the live reader is now a largest group of 2 rather than 74.
        ranked = sorted(
            totals.items(),
            key=lambda item: (
                -item[1],
                -agreement[item[0]],
                best_position[item[0]],
                item[0],
            ),
        )
        return tuple(ranked[:count])

    def _slice(self, book_id: int, limit: int | None) -> tuple[int, int]:
        row = self._row_by_book_id.get(book_id)
        if row is None:
            return (0, 0)
        start, end = int(self._indptr[row]), int(self._indptr[row + 1])
        if limit is not None:
            end = min(end, start + limit)
        return (start, end)


def load_item_cf_artifact(
    storage: LocalArtifactStorage,
    *,
    catalog: CatalogSnapshot,
    artifact_dir: str = ITEM_CF.directory,
) -> ItemCfNeighbors:
    bundle = load_artifact_bundle(
        storage, artifact_dir, catalog=catalog, expected_model_name=ITEM_CF.name
    )
    if not bundle.is_servable:
        raise IncompatibleArtifactError(
            f"item-CF artifact is not servable: {bundle.resolution.reason}"
        )

    item_count = bundle.manifest.item_count
    arrays = load_arrays(storage.resolve(artifact_dir, NEIGHBORS_FILENAME))
    indptr = require_int_array(arrays, _INDPTR, expected_size=item_count + 1)
    edge_count = int(indptr[-1])
    neighbor_indices = require_int_array(arrays, _NEIGHBOR_INDICES, expected_size=edge_count)
    scores = require_float_array(arrays, _SCORES, expected_size=edge_count)

    if int(indptr[0]) != 0 or bool(np.any(np.diff(indptr) < 0)):
        raise IncompatibleArtifactError("item-CF indptr is not a valid CSR row pointer")
    if edge_count and (
        int(neighbor_indices.min()) < 0 or int(neighbor_indices.max()) >= item_count
    ):
        raise IncompatibleArtifactError(
            "item-CF neighbour points outside the artifact's item space"
        )

    # Same both-endpoints-must-resolve filter as the source-similarity graph:
    # a neighbour whose book left the catalog is not a candidate.
    lookup = bundle.resolution.index_to_book_id(item_count)
    edge_sources = np.repeat(np.arange(item_count, dtype=np.int64), np.diff(indptr))
    keep = (lookup[edge_sources] >= 0) & (lookup[neighbor_indices] >= 0)

    kept_lengths = np.bincount(edge_sources[keep], minlength=item_count)
    resolved_indices = bundle.resolution.model_item_indices
    compact_indptr = np.zeros(resolved_indices.size + 1, dtype=np.int64)
    np.cumsum(kept_lengths[resolved_indices], out=compact_indptr[1:])

    similarity = bundle.manifest.config.get(SIMILARITY_CONFIG_KEY)
    top_k = bundle.manifest.config.get(TOP_K_CONFIG_KEY)

    return ItemCfNeighbors(
        _indptr=compact_indptr,
        _neighbor_book_ids=lookup[neighbor_indices[keep]],
        _scores=scores[keep],
        _row_by_book_id={
            int(book_id): row for row, book_id in enumerate(bundle.resolution.book_ids)
        },
        similarity=str(similarity) if isinstance(similarity, str) else "unknown",
        top_k=int(top_k) if isinstance(top_k, int) else 0,
        bundle=bundle,
    )
