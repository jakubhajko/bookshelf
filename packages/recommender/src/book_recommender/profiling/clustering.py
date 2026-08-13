"""Threshold-based agglomerative clustering over normalized vectors
(rec-spec §12.2, ADR-0016).

**Pure NumPy, on purpose.** This runs at *serving* time — a reader's
interests are inferred when their recommendation batch is built — so it
cannot import scikit-learn, which lives in the training-only dependency
group (ADR-0018/ADR-0021). Average-linkage agglomerative clustering over at
most ~100 bounded items is about forty lines of array arithmetic, and
writing those forty lines is cheaper than putting a training dependency on
the request path.

**Similarity, not distance, and a threshold, not a K.** rec-spec §12.2:
"distance/similarity threshold rather than fixed K" and "Do not force every
user into the same number of interests." Vectors arrive L2-normalized from
the content artifact, so cosine similarity is the dot product and
average-linkage merging can work directly on a similarity matrix.

The implementation is the textbook one, kept naive deliberately: repeatedly
merge the two most similar clusters until the best remaining pair falls
below the threshold. That is O(n³) in the worst case, which for n ≤ 100 is
microseconds and is far easier to verify than a heap-based variant.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt


def average_linkage_clusters(
    similarity: npt.NDArray[np.floating], *, threshold: float
) -> tuple[tuple[int, ...], ...]:
    """Group indices by average-linkage similarity.

    ``similarity`` must be square and symmetric. Returns clusters as tuples
    of original indices, each sorted ascending, and the clusters themselves
    ordered by their smallest member — so the output depends only on the
    input, never on iteration order. Determinism matters here beyond
    tidiness: an interest id is derived from cluster membership, and a
    profile that reshuffled between two identical requests would produce
    different diagnostics for the same reader.
    """
    count = int(similarity.shape[0])
    if count == 0:
        return ()
    if count == 1:
        return ((0,),)

    # Work on a mutable copy: merged rows are masked out with -inf rather
    # than deleted, which keeps every index stable throughout.
    scores = np.array(similarity, dtype=np.float64, copy=True)
    np.fill_diagonal(scores, -np.inf)
    clusters: dict[int, list[int]] = {index: [index] for index in range(count)}

    while len(clusters) > 1:
        best = np.unravel_index(int(np.argmax(scores)), scores.shape)
        row, column = int(best[0]), int(best[1])
        if not np.isfinite(scores[row, column]) or scores[row, column] < threshold:
            break

        # Merge the higher index into the lower one so the surviving key is
        # always the cluster's smallest member.
        keep, drop = (row, column) if row < column else (column, row)
        keep_size = len(clusters[keep])
        drop_size = len(clusters[drop])
        clusters[keep] = clusters[keep] + clusters.pop(drop)

        # Average linkage: the merged cluster's similarity to any other is
        # the size-weighted mean of its two parts'. Sizes are read *before*
        # the merge — using the merged size for both halves would silently
        # turn this into something that is not average linkage.
        for other in clusters:
            if other == keep:
                continue
            left = scores[keep, other]
            right = scores[drop, other]
            if not np.isfinite(left) or not np.isfinite(right):
                continue
            combined = (left * keep_size + right * drop_size) / (keep_size + drop_size)
            scores[keep, other] = scores[other, keep] = combined

        scores[drop, :] = -np.inf
        scores[:, drop] = -np.inf

    return tuple(
        tuple(sorted(members)) for _, members in sorted(clusters.items(), key=lambda kv: kv[0])
    )


def cosine_similarity_matrix(vectors: npt.NDArray[np.floating]) -> npt.NDArray[np.float64]:
    """Pairwise cosine similarity for already-normalized vectors.

    Re-normalizes defensively: a caller that passes unnormalized vectors
    would otherwise get a magnitude-weighted matrix and clusters that track
    description length rather than meaning.
    """
    matrix = np.asarray(vectors, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] == 0:
        return np.zeros((0, 0), dtype=np.float64)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = matrix / norms
    similarity: npt.NDArray[np.float64] = np.clip(unit @ unit.T, -1.0, 1.0)
    return similarity


def weighted_centroid(
    vectors: npt.NDArray[np.floating], weights: npt.NDArray[np.floating]
) -> npt.NDArray[np.float64]:
    """Normalized weighted mean — the default retrieval query for a cluster
    (rec-spec §12.2)."""
    matrix = np.asarray(vectors, dtype=np.float64)
    weight_vector = np.asarray(weights, dtype=np.float64)
    if matrix.shape[0] == 0:
        return np.zeros(0, dtype=np.float64)
    total = weight_vector.sum()
    if total <= 0:
        centroid = matrix.mean(axis=0)
    else:
        centroid = (matrix * weight_vector[:, None]).sum(axis=0) / total
    norm = float(np.linalg.norm(centroid))
    return centroid if norm == 0 else centroid / norm


def medoid_index(similarity: npt.NDArray[np.floating]) -> int:
    """The member most similar to all the others — the cluster's
    representative real book (rec-spec §12.2).

    A medoid is an actual interacted book, unlike the centroid, which is why
    rec-spec §13 uses it for human-readable labels: "Interest around 'The
    Left Hand of Darkness'" is meaningful in a way that a 512-dimensional
    mean is not.
    """
    matrix = np.asarray(similarity, dtype=np.float64)
    if matrix.shape[0] == 0:
        return 0
    totals = matrix.sum(axis=1)
    # Ties resolve to the lowest index, keeping the choice deterministic.
    return int(np.argmax(totals))
