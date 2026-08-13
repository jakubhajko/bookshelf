"""Source-similarity (Goodreads) graph artifact (rec-spec §14, ADR-0014).

The catalog import already resolves Goodreads "similar works" edges to books
present in the application catalog and drops the rest, leaving ~269k edges in
``book_source_similarities``. Those rows are PostgreSQL-only, so nothing can
use them without a database read during inference — which ADR-0014 forbids.
This module is the export's runtime half.

**Storage.** A CSR (compressed sparse row) triple over the shared
model-item-index space: ``indptr`` gives each source item's slice, and
``neighbor_indices``/``ranks``/``source_codes`` are the flat edge columns.
Roughly 3 MB for the whole graph, versus ~15 MB of JSON, and neighbour lookup
is an array slice rather than a dict-of-lists walk.

**Provenance stays intact.** rec-spec §14: "Keep this generator semantically
pure — do not quietly mix same-author, same-genre or semantic KNN heuristics
into this generator." Every edge carries the source that produced it
(``goodreads`` today), so a second source can be added later without the
resulting candidates becoming unattributable. Nothing in this module invents
an edge; it only reads what the import resolved.

**Rank, not score.** The upstream data is an ordered neighbour list with no
similarity values, so the artifact stores the rank and says nothing about
distance. Turning a rank into a score is the fusion layer's job (ADR-0017's
weighted RRF), not this loader's.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from book_recommender.artifacts.loader import ArtifactBundle, load_artifact_bundle
from book_recommender.artifacts.local_storage import LocalArtifactStorage
from book_recommender.artifacts.mapping import CatalogSnapshot
from book_recommender.artifacts.numeric import load_arrays, require_int_array, save_arrays
from book_recommender.config import SOURCE_SIMILARITY
from book_recommender.exceptions import IncompatibleArtifactError

GRAPH_FILENAME = "graph.npz"

_INDPTR = "indptr"
_NEIGHBOR_INDICES = "neighbor_indices"
_RANKS = "ranks"
_SOURCE_CODES = "source_codes"

#: Manifest ``config`` key holding the ordered source vocabulary that
#: ``source_codes`` indexes into.
SOURCES_CONFIG_KEY = "sources"


@dataclass(frozen=True)
class SourceNeighbor:
    book_id: int
    rank: int
    source: str


@dataclass(frozen=True)
class SourceSimilarityGraph:
    """Runtime neighbour lookup, keyed on *current* catalog book ids."""

    _indptr: npt.NDArray[np.int64]
    _neighbor_book_ids: npt.NDArray[np.int64]
    _ranks: npt.NDArray[np.int64]
    _source_codes: npt.NDArray[np.int64]
    _sources: tuple[str, ...]
    _row_by_book_id: dict[int, int]
    bundle: ArtifactBundle

    @property
    def item_count(self) -> int:
        return len(self._row_by_book_id)

    @property
    def edge_count(self) -> int:
        return int(self._neighbor_book_ids.size)

    @property
    def sources(self) -> tuple[str, ...]:
        return self._sources

    def neighbor_book_ids(self, book_id: int, *, limit: int | None = None) -> tuple[int, ...]:
        """Just the ids, in the source's own rank order — the hot path for a
        candidate generator that only needs identities."""
        row = self._row_by_book_id.get(book_id)
        if row is None:
            return ()
        start, end = int(self._indptr[row]), int(self._indptr[row + 1])
        if limit is not None:
            end = min(end, start + limit)
        return tuple(int(value) for value in self._neighbor_book_ids[start:end])

    def neighbors(self, book_id: int, *, limit: int | None = None) -> tuple[SourceNeighbor, ...]:
        """Neighbours with their rank and provenance, for diagnostics and
        reason codes (rec-spec §21)."""
        row = self._row_by_book_id.get(book_id)
        if row is None:
            return ()
        start, end = int(self._indptr[row]), int(self._indptr[row + 1])
        if limit is not None:
            end = min(end, start + limit)
        return tuple(
            SourceNeighbor(
                book_id=int(self._neighbor_book_ids[offset]),
                rank=int(self._ranks[offset]),
                source=self._sources[int(self._source_codes[offset])],
            )
            for offset in range(start, end)
        )

    def has_neighbors(self, book_id: int) -> bool:
        row = self._row_by_book_id.get(book_id)
        if row is None:
            return False
        return int(self._indptr[row + 1]) > int(self._indptr[row])


def write_source_similarity_graph(
    path: Path,
    *,
    indptr: Sequence[int],
    neighbor_indices: Sequence[int],
    ranks: Sequence[int],
    source_codes: Sequence[int],
) -> None:
    """Builder-side writer. Columns are in model-item-index space; the
    builder is responsible for the CSR invariants, which
    :func:`load_source_similarity_artifact` re-checks on the way back in."""
    save_arrays(
        path,
        {
            _INDPTR: np.asarray(indptr, dtype=np.int64),
            _NEIGHBOR_INDICES: np.asarray(neighbor_indices, dtype=np.int32),
            _RANKS: np.asarray(ranks, dtype=np.int16),
            _SOURCE_CODES: np.asarray(source_codes, dtype=np.uint8),
        },
    )


def load_source_similarity_artifact(
    storage: LocalArtifactStorage,
    *,
    catalog: CatalogSnapshot,
    artifact_dir: str = SOURCE_SIMILARITY.directory,
) -> SourceSimilarityGraph:
    bundle = load_artifact_bundle(
        storage, artifact_dir, catalog=catalog, expected_model_name=SOURCE_SIMILARITY.name
    )
    if not bundle.is_servable:
        raise IncompatibleArtifactError(
            f"source-similarity artifact is not servable: {bundle.resolution.reason}"
        )

    item_count = bundle.manifest.item_count
    arrays = load_arrays(storage.resolve(artifact_dir, GRAPH_FILENAME))
    indptr = require_int_array(arrays, _INDPTR, expected_size=item_count + 1)
    edge_count = int(indptr[-1])
    neighbor_indices = require_int_array(arrays, _NEIGHBOR_INDICES, expected_size=edge_count)
    ranks = require_int_array(arrays, _RANKS, expected_size=edge_count)
    source_codes = require_int_array(arrays, _SOURCE_CODES, expected_size=edge_count)

    _validate_csr(indptr, neighbor_indices, item_count)
    sources = _read_sources(bundle)
    if edge_count and int(source_codes.max()) >= len(sources):
        raise IncompatibleArtifactError(
            f"edge references source code {int(source_codes.max())} but the manifest "
            f"declares only {len(sources)} sources"
        )

    # Resolution may have dropped items, and an edge is only meaningful when
    # *both* endpoints still exist. Filtering here rather than at query time
    # keeps the read path a plain slice and means the graph can never hand a
    # generator a book id that is no longer in the catalog.
    lookup = bundle.resolution.index_to_book_id(item_count)
    row_lengths = np.diff(indptr)
    edge_sources = np.repeat(np.arange(item_count, dtype=np.int64), row_lengths)
    keep = (lookup[edge_sources] >= 0) & (lookup[neighbor_indices] >= 0)

    kept_lengths = np.bincount(edge_sources[keep], minlength=item_count)
    resolved_indices = bundle.resolution.model_item_indices
    compact_indptr = np.zeros(resolved_indices.size + 1, dtype=np.int64)
    np.cumsum(kept_lengths[resolved_indices], out=compact_indptr[1:])

    return SourceSimilarityGraph(
        _indptr=compact_indptr,
        _neighbor_book_ids=lookup[neighbor_indices[keep]],
        _ranks=ranks[keep],
        _source_codes=source_codes[keep],
        _sources=sources,
        _row_by_book_id={
            int(book_id): row for row, book_id in enumerate(bundle.resolution.book_ids)
        },
        bundle=bundle,
    )


def _validate_csr(
    indptr: npt.NDArray[np.int64], neighbor_indices: npt.NDArray[np.int64], item_count: int
) -> None:
    if int(indptr[0]) != 0:
        raise IncompatibleArtifactError("source-similarity indptr must start at 0")
    if bool(np.any(np.diff(indptr) < 0)):
        raise IncompatibleArtifactError("source-similarity indptr is not monotonic")
    if neighbor_indices.size and (
        int(neighbor_indices.min()) < 0 or int(neighbor_indices.max()) >= item_count
    ):
        raise IncompatibleArtifactError(
            "source-similarity edge points outside the artifact's item space — "
            "the graph and its mapping disagree"
        )


def _read_sources(bundle: ArtifactBundle) -> tuple[str, ...]:
    raw = bundle.manifest.config.get(SOURCES_CONFIG_KEY)
    if not isinstance(raw, list) or not raw or not all(isinstance(item, str) for item in raw):
        raise IncompatibleArtifactError(
            "source-similarity manifest must declare a non-empty "
            f"{SOURCES_CONFIG_KEY!r} list — edge provenance would otherwise be lost"
        )
    return tuple(str(item) for item in raw)


def build_csr(
    edges_by_index: Iterable[tuple[int, int, int, int]], *, item_count: int
) -> tuple[list[int], list[int], list[int], list[int]]:
    """Turn ``(source_index, neighbor_index, rank, source_code)`` tuples,
    already sorted by ``(source_index, rank)``, into CSR columns.

    Lives here beside the reader so the two halves of the format cannot
    drift; the builder in ``apps/api`` supplies the rows.
    """
    indptr = [0]
    neighbor_indices: list[int] = []
    ranks: list[int] = []
    source_codes: list[int] = []
    current = 0
    for source_index, neighbor_index, rank, source_code in edges_by_index:
        if source_index < current:
            raise ValueError("edges must be sorted by source_index")
        while current < source_index:
            indptr.append(len(neighbor_indices))
            current += 1
        neighbor_indices.append(neighbor_index)
        ranks.append(rank)
        source_codes.append(source_code)
    while current < item_count:
        indptr.append(len(neighbor_indices))
        current += 1
    return indptr, neighbor_indices, ranks, source_codes
