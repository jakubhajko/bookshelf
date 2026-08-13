"""ALS and item-item CF training (rec-spec §9.1, §10).

**The only module in the repository that imports ``implicit`` or ``scipy``.**
Both live in the ``training`` dependency group, which ``make setup`` does not
install and the API never needs (ADR-0018/ADR-0021) — verified, not merely
declared: ``uv sync --all-packages`` prunes them from the environment. So
this module is imported by the build CLIs and nothing else, and its tests
skip when the group is absent.

Its runtime counterparts are plain NumPy in the recommender package:
``AlsArtifact.fold_in`` solves against fixed item factors without
``implicit``, and ``ItemCfNeighbors`` slices arrays without ``scipy``.
Nothing trained here is needed to serve what it produces.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import scipy.sparse as sp
from book_recommender.config import AlsConfig, ItemCfConfig
from implicit.als import AlternatingLeastSquares

from book_app.modules.recommendations.interaction_transform import InteractionDataset


def build_user_item_matrix(
    dataset: InteractionDataset, *, row_mask: npt.NDArray[np.bool_] | None = None
) -> sp.csr_matrix:
    """Confidence matrix in ``users × model_item_index`` orientation.

    The column space is the whole catalog, not just interacted items, so
    that column *i* is ``model_item_index`` *i* in every artifact family
    (ADR-0014). Untouched columns are simply empty.
    """
    mask = np.ones(len(dataset), dtype=bool) if row_mask is None else row_mask
    matrix = sp.csr_matrix(
        (
            dataset.confidences[mask].astype(np.float32, copy=False),
            (dataset.user_indices[mask], dataset.item_indices[mask]),
        ),
        shape=(max(dataset.user_count, 1), dataset.item_count),
        dtype=np.float32,
    )
    # A reader can appear twice for one book across the source data; summing
    # duplicates is what csr_matrix does on construction, and sum_duplicates
    # makes the stored representation canonical so a rebuild is byte-stable.
    matrix.sum_duplicates()
    return matrix


@dataclass(frozen=True)
class TrainedAls:
    item_factors: npt.NDArray[np.float32]
    user_factors: npt.NDArray[np.float32]
    config: AlsConfig

    @property
    def factor_count(self) -> int:
        return int(self.item_factors.shape[1])


def train_als(matrix: sp.csr_matrix, config: AlsConfig) -> TrainedAls:
    """Train implicit-feedback ALS.

    ``random_state`` is fixed from config so a rebuild on identical input
    reproduces identical factors — the same determinism property every other
    artifact family holds to (rec-spec §28).
    """
    model = AlternatingLeastSquares(
        factors=config.factors,
        regularization=config.regularization,
        iterations=config.iterations,
        random_state=config.random_state,
        use_gpu=False,
        calculate_training_loss=False,
    )
    model.fit(matrix, show_progress=False)
    return TrainedAls(
        item_factors=np.ascontiguousarray(model.item_factors, dtype=np.float32),
        user_factors=np.ascontiguousarray(model.user_factors, dtype=np.float32),
        config=config,
    )


def rank_for_users(
    trained: TrainedAls,
    matrix: sp.csr_matrix,
    user_indices: Sequence[int],
    *,
    count: int,
) -> dict[int, list[int]]:
    """Top-``count`` item indices per historical user, excluding their own
    training items.

    Used only for offline evaluation. Recommending back a book the user
    already has is trivially easy and would flatter every configuration
    equally, so those columns are masked out before ranking.
    """
    rankings: dict[int, list[int]] = {}
    item_factors = trained.item_factors.astype(np.float32, copy=False)

    for user_index in user_indices:
        if user_index >= trained.user_factors.shape[0]:
            continue
        scores = item_factors @ trained.user_factors[user_index]
        seen = matrix.indices[matrix.indptr[user_index] : matrix.indptr[user_index + 1]]
        scores[seen] = -np.inf
        take = min(count, scores.size)
        top = np.argpartition(-scores, take - 1)[:take]
        rankings[int(user_index)] = [
            int(index) for index in top[np.argsort(-scores[top], kind="stable")]
        ]
    return rankings


# --- Item-item CF -----------------------------------------------------------


def _bm25_weight(matrix: sp.csr_matrix, k1: float, b: float) -> sp.csr_matrix:
    """BM25 reweighting of the user×item confidence matrix.

    rec-spec §10 asks for "popularity-aware weighting such as BM25/TF-IDF or
    a clearly documented cosine baseline". BM25's contribution here is the
    IDF term — except that it does not, and the reason is worth stating
    because the obvious implementation is silently inert.

    **The IDF is deliberately not applied.** BM25's IDF is a *per-item*
    scalar, and ``train_item_neighbors`` L2-normalizes each item vector
    before taking cosine similarity. Normalizing a vector cancels any scalar
    multiple of it exactly, so multiplying item *i*'s column by ``idf[i]``
    changes nothing about any similarity it participates in. Writing that
    multiplication would look like popularity correction while doing
    arithmetic with no effect. (This is also why ``implicit``'s own
    ``BM25Recommender`` gets its behaviour from the same two terms below.)

    What genuinely survives normalization, and is therefore what "BM25"
    means here:

    - ``b`` — **user-length normalization.** A reader with 500 books
      provides weaker per-book evidence than one with 5, because their
      co-occurrences are far more likely to be incidental. This varies
      *within* an item's column, so it does not cancel.
    - ``k1`` — **saturation.** Repeated or high-confidence interactions
      stop adding evidence linearly.

    Together they discount exactly the co-occurrences that make neighbour
    lists collapse onto bestsellers, which is the effect rec-spec §10 asks
    for. The test
    ``test_bm25_prefers_evidence_from_focused_readers`` pins it down.
    """
    weighted = matrix.tocsr(copy=True).astype(np.float64)

    row_sums = np.asarray(weighted.sum(axis=1)).ravel()
    average_length = row_sums.mean() if row_sums.size else 0.0
    if average_length <= 0:
        return weighted.astype(np.float32)

    row_lengths = np.repeat(row_sums, np.diff(weighted.indptr))
    norm = k1 * (1.0 - b + b * row_lengths / average_length)
    weighted.data = weighted.data * (k1 + 1.0) / (norm + weighted.data)
    return weighted.astype(np.float32)


def train_item_neighbors(
    matrix: sp.csr_matrix, config: ItemCfConfig
) -> tuple[list[int], list[int], list[float]]:
    """Top-K item-item neighbours as CSR columns over the item space.

    Cosine similarity over L2-normalized item columns, optionally after BM25
    reweighting. The whole item-item product is ~92k × 92k conceptually, so
    it is computed in column blocks and truncated to top-K per item before
    anything dense is materialized.
    """
    weighted = (
        _bm25_weight(matrix, config.bm25_k1, config.bm25_b)
        if config.similarity == "bm25"
        else matrix
    )
    items = weighted.T.tocsr().astype(np.float32)

    norms = np.sqrt(items.multiply(items).sum(axis=1))
    norms = np.asarray(norms).ravel()
    norms[norms == 0] = 1.0
    inverse = sp.diags(1.0 / norms)
    normalized = (inverse @ items).tocsr()

    item_count = normalized.shape[0]
    indptr = [0]
    neighbor_indices: list[int] = []
    scores: list[float] = []

    transposed = normalized.T.tocsc()
    block = 1024
    for start in range(0, item_count, block):
        end = min(start + block, item_count)
        # Two items are similar only if some reader touched both, so the
        # product stays genuinely sparse — ~8 interactions per item over 92k
        # items. Densifying the slice would cost 380 MB per block to hold
        # mostly zeros, so the top-K selection runs on the sparse rows.
        similarity = (normalized[start:end] @ transposed).tocsr()
        for offset in range(end - start):
            row_start = int(similarity.indptr[offset])
            row_end = int(similarity.indptr[offset + 1])
            columns = similarity.indices[row_start:row_end]
            values = similarity.data[row_start:row_end]

            keep = (columns != start + offset) & (values > 0)
            columns, values = columns[keep], values[keep]

            if columns.size > config.top_k:
                partial = np.argpartition(-values, config.top_k - 1)[: config.top_k]
                columns, values = columns[partial], values[partial]
            # Stable sort on (-score) with ascending column order as the
            # implicit tiebreak keeps rebuilds byte-identical.
            order = np.lexsort((columns, -values))
            neighbor_indices.extend(int(index) for index in columns[order])
            scores.extend(float(value) for value in values[order])
            indptr.append(len(neighbor_indices))

    return indptr, neighbor_indices, scores


def rank_from_neighbors(
    indptr: Sequence[int],
    neighbor_indices: Sequence[int],
    scores: Sequence[float],
    matrix: sp.csr_matrix,
    user_indices: Sequence[int],
    *,
    count: int,
    item_count: int,
) -> dict[int, list[int]]:
    """Offline counterpart of ``ItemCfNeighbors.candidates_from_seeds``,
    scoring historical users from their own training items."""
    indptr_array = np.asarray(indptr, dtype=np.int64)
    indices_array = np.asarray(neighbor_indices, dtype=np.int64)
    scores_array = np.asarray(scores, dtype=np.float64)

    rankings: dict[int, list[int]] = {}
    for user_index in user_indices:
        seeds = matrix.indices[matrix.indptr[user_index] : matrix.indptr[user_index + 1]]
        weights = matrix.data[matrix.indptr[user_index] : matrix.indptr[user_index + 1]]
        if seeds.size == 0:
            continue
        totals = np.zeros(item_count, dtype=np.float64)
        for seed, weight in zip(seeds, weights, strict=True):
            start, end = int(indptr_array[seed]), int(indptr_array[seed + 1])
            if end > start:
                np.add.at(totals, indices_array[start:end], weight * scores_array[start:end])
        totals[seeds] = -np.inf
        take = min(count, totals.size)
        top = np.argpartition(-totals, take - 1)[:take]
        top = top[np.argsort(-totals[top], kind="stable")]
        rankings[int(user_index)] = [int(index) for index in top if np.isfinite(totals[index])]
    return rankings
