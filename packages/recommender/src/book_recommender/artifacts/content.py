"""Content-embedding artifact and exact semantic retrieval
(rec-spec §11, §24; ADR-0014, ADR-0018).

The embedding matrix is the largest artifact in the system — 92,524 × 512
float32, about 190 MB — so this module is where ``mmap`` finally earns the
`.npy` format choice made back in R3.

**Retrieval is a dense matmul, deliberately.** rec-spec §11.1: "For this
catalog size (~92k books), exact batched matrix similarity is acceptable
initially. Do not introduce pgvector, FAISS, a vector database, or a
separate retrieval microservice unless profiling demonstrates a real need."
Vectors are stored L2-normalized, so cosine similarity *is* the dot product
and one query is a single `(92524, 512) @ (512,)` product. No index, no
approximation, no drift between what was built and what is searched.

**No model is ever loaded here.** ADR-0018: the API reads vectors, the
offline build produces them. Nothing in this module imports a transformer,
and the encoder identity it validates is metadata, not a dependency.
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
from book_recommender.artifacts.numeric import load_array, save_array
from book_recommender.config import CONTENT
from book_recommender.exceptions import IncompatibleArtifactError

EMBEDDINGS_FILENAME = "embeddings.npy"

#: Manifest ``config`` keys. rec-spec §11.1 requires every one of these to be
#: recorded so an artifact can be reproduced and so a swapped encoder is
#: visible rather than silent.
ENCODER_CONFIG_KEY = "encoder"
ENCODER_REVISION_CONFIG_KEY = "encoder_revision"
DIMENSION_CONFIG_KEY = "dimension"
NORMALIZED_CONFIG_KEY = "normalized"
PROMPT_VERSION_CONFIG_KEY = "prompt_version"
TEXT_TEMPLATE_CONFIG_KEY = "text_template_version"
TAGS_VERSION_CONFIG_KEY = "tags_version"

#: Tolerance for "is this row unit-norm".
#:
#: Measured, not guessed: the real Qwen3 artifact normalizes in float32 and
#: its rows land in [0.9972, 1.0026] — a 2.6e-3 spread that a tighter bound
#: rejects. Found by running the inspection command against a real build,
#: which hand-written fixtures (normalized in float64, then cast) could not
#: have surfaced.
#:
#: 1e-2 still catches what this check is for. An artifact that skipped
#: normalization has rows off by whole factors, not by thousandths.
_NORM_TOLERANCE = 1e-2


def write_embeddings(path: Path, embeddings: npt.NDArray[np.float32]) -> None:
    """Builder-side writer. Stores ``float32`` and expects unit-norm rows."""
    save_array(path, np.ascontiguousarray(embeddings, dtype=np.float32))


@dataclass(frozen=True)
class ContentEmbeddings:
    """Normalized book vectors plus exact retrieval over them."""

    vectors: npt.NDArray[np.float32]
    book_ids: npt.NDArray[np.int64]
    encoder: str
    dimension: int
    bundle: ArtifactBundle
    _row_by_book_id: Mapping[int, int]

    @property
    def item_count(self) -> int:
        return int(self.vectors.shape[0])

    @property
    def model_version(self) -> str:
        return self.bundle.manifest.model_version

    def vector_for(self, book_id: int) -> npt.NDArray[np.float32] | None:
        row = self._row_by_book_id.get(book_id)
        return None if row is None else self.vectors[row]

    def vectors_for(self, book_ids: Sequence[int]) -> tuple[npt.NDArray[np.float32], list[int]]:
        """Vectors for the books that have one, plus the ids they belong to.

        Returns the surviving ids rather than raising on unknown books: a
        user's shelf can legitimately contain a book added after the last
        embedding build, and a profile should degrade rather than fail.
        """
        rows = [
            (self._row_by_book_id[book_id], book_id)
            for book_id in book_ids
            if book_id in self._row_by_book_id
        ]
        if not rows:
            return np.empty((0, self.dimension), dtype=np.float32), []
        indices = [row for row, _ in rows]
        return np.asarray(self.vectors[indices], dtype=np.float32), [bid for _, bid in rows]

    def search(
        self,
        query: npt.NDArray[np.floating],
        *,
        count: int,
        excluded_book_ids: frozenset[int] = frozenset(),
    ) -> tuple[tuple[int, float], ...]:
        """Nearest books to one normalized query vector, as ``(book_id, score)``.

        Exclusions are applied before top-K selection, not after, so a reader
        with a large library still gets a full page (same reasoning as the
        ALS retrieval path).
        """
        if count <= 0 or self.item_count == 0:
            return ()
        scores = self.vectors @ np.asarray(query, dtype=np.float32)

        eligible = np.ones(scores.shape[0], dtype=bool)
        if excluded_book_ids:
            rows = [
                row
                for row in (self._row_by_book_id.get(book_id) for book_id in excluded_book_ids)
                if row is not None
            ]
            if rows:
                eligible[rows] = False

        candidate_rows = np.flatnonzero(eligible)
        if candidate_rows.size == 0:
            return ()

        candidate_scores = scores[candidate_rows]
        take = min(count, candidate_rows.size)
        top = np.argpartition(-candidate_scores, take - 1)[:take]
        top = top[np.argsort(-candidate_scores[top], kind="stable")]
        return tuple(
            (int(self.book_ids[candidate_rows[index]]), float(candidate_scores[index]))
            for index in top
        )

    def search_many(
        self,
        queries: npt.NDArray[np.floating],
        *,
        count: int,
        excluded_book_ids: frozenset[int] = frozenset(),
    ) -> tuple[tuple[tuple[int, float], ...], ...]:
        """Batched retrieval for several queries — one matmul for all of them
        (rec-spec §11.1's "exact batched matrix similarity")."""
        matrix = np.atleast_2d(np.asarray(queries, dtype=np.float32))
        if matrix.size == 0 or count <= 0:
            return ()
        return tuple(
            self.search(row, count=count, excluded_book_ids=excluded_book_ids) for row in matrix
        )

    def similarity(self, left_book_id: int, right_book_id: int) -> float | None:
        """Cosine similarity between two catalog books, for diagnostics."""
        left, right = self.vector_for(left_book_id), self.vector_for(right_book_id)
        if left is None or right is None:
            return None
        return float(left @ right)


def load_content_artifact(
    storage: LocalArtifactStorage,
    *,
    catalog: CatalogSnapshot,
    artifact_dir: str = CONTENT.directory,
    mmap: bool = False,
) -> ContentEmbeddings:
    bundle = load_artifact_bundle(
        storage, artifact_dir, catalog=catalog, expected_model_name=CONTENT.name
    )
    if not bundle.is_servable:
        raise IncompatibleArtifactError(
            f"content artifact is not servable: {bundle.resolution.reason}"
        )

    vectors = load_array(storage.resolve(artifact_dir, EMBEDDINGS_FILENAME), mmap=mmap)
    if vectors.ndim != 2:
        raise IncompatibleArtifactError(
            f"content embeddings must be a 2-D matrix, got {vectors.ndim}-D"
        )
    if vectors.shape[0] != bundle.manifest.item_count:
        raise IncompatibleArtifactError(
            f"content embeddings have {vectors.shape[0]} rows, manifest declares "
            f"{bundle.manifest.item_count} items"
        )

    declared_dimension = bundle.manifest.config.get(DIMENSION_CONFIG_KEY)
    if isinstance(declared_dimension, int) and vectors.shape[1] != declared_dimension:
        raise IncompatibleArtifactError(
            f"content embeddings are {vectors.shape[1]}-dimensional, manifest declares "
            f"{declared_dimension}"
        )
    if not np.all(np.isfinite(vectors)):
        raise IncompatibleArtifactError("content embeddings contain non-finite values")

    if bundle.manifest.config.get(NORMALIZED_CONFIG_KEY) is not True:
        # Retrieval treats the dot product as cosine similarity. An artifact
        # that is not normalized would score by magnitude — longer
        # descriptions would simply rank higher — and look plausible.
        raise IncompatibleArtifactError(
            "content embeddings must declare normalized=true; retrieval relies on it"
        )
    _verify_normalized(vectors)

    resolution = bundle.resolution
    resolved = np.ascontiguousarray(
        np.asarray(vectors)[resolution.model_item_indices], dtype=np.float32
    )
    encoder = bundle.manifest.config.get(ENCODER_CONFIG_KEY)

    return ContentEmbeddings(
        vectors=resolved,
        book_ids=resolution.book_ids,
        encoder=str(encoder) if isinstance(encoder, str) else "unknown",
        dimension=int(resolved.shape[1]),
        bundle=bundle,
        _row_by_book_id={int(book_id): row for row, book_id in enumerate(resolution.book_ids)},
    )


def _verify_normalized(vectors: npt.NDArray[np.generic]) -> None:
    """Spot-check row norms rather than compute all 92k.

    A build that forgot to normalize gets it wrong everywhere, not in a
    scattered few rows, so a bounded deterministic sample catches it at a
    fraction of the cost. The stride is fixed, so the check is reproducible.
    """
    sample = np.asarray(vectors[:: max(1, vectors.shape[0] // 512)], dtype=np.float64)
    if sample.size == 0:
        return
    norms = np.sqrt((sample**2).sum(axis=1))
    # An all-zero row is a book whose text failed to encode; that is a build
    # bug worth failing on, not a degenerate vector to serve.
    if float(norms.min()) < 1.0 - _NORM_TOLERANCE or float(norms.max()) > 1.0 + _NORM_TOLERANCE:
        raise IncompatibleArtifactError(
            f"content embedding rows are not unit-norm (sampled range "
            f"[{float(norms.min()):.4f}, {float(norms.max()):.4f}])"
        )
