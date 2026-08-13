"""ALS collaborative-filtering artifact and live-user fold-in
(rec-spec §9, ADR-0014).

**Only item factors are served.** rec-spec §9.1: "persist item factors and
training metadata; historical user factors are optional at serving time".
They are not merely optional here, they are deliberately absent — 83,200
historical Book-Crossing user vectors have no meaning to any application
user (rec-spec §7.2), so shipping them into the serving process would put
data in memory that nothing may legitimately join to. The trainer keeps them
for evaluation and drops them on the way out.

**Fold-in runs at serving time, in plain NumPy.** rec-spec §9.2: a live user
"does not need to exist in the historical user matrix"; their factor is
solved against fixed item factors from current durable evidence, and the
global model is *not* retrained when someone rates a book. That solve is
~50 lines of linear algebra, so this module implements it directly rather
than importing the training library — which is what keeps `implicit` out of
the API runtime (ADR-0018/ADR-0021).

The maths is the standard implicit-ALS conjugate step. For a user with
confidence weights ``c`` over item rows ``Y``:

    x = (YᵀY + Yᵀ(C−I)Y + λI)⁻¹ · Yᵀ C p

``YᵀY`` is precomputed once at load, because it does not depend on the user
— which is what makes a per-request fold-in cheap. Only the rows the user
actually interacted with contribute to the rest, so the cost scales with the
size of one reader's library, not with the catalog.
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
from book_recommender.config import ALS, ALS_FOLD_IN_REGULARIZATION
from book_recommender.exceptions import IncompatibleArtifactError

ITEM_FACTORS_FILENAME = "item_factors.npy"

#: Manifest ``config`` keys the loader reads back.
FACTORS_CONFIG_KEY = "factors"
REGULARIZATION_CONFIG_KEY = "regularization"


def write_item_factors(path: Path, factors: npt.NDArray[np.float32]) -> None:
    """Builder-side writer. A plain ``.npy`` rather than an ``.npz`` because
    this is the first payload big enough to want ``mmap`` (rec-spec §24)."""
    save_array(path, np.ascontiguousarray(factors, dtype=np.float32))


@dataclass(frozen=True)
class AlsArtifact:
    """Fixed item factors plus the fold-in solver that uses them."""

    #: ``(resolved_item_count, factors)``, row *i* being the factor for
    #: ``book_ids[i]``. Rows for items that no longer resolve are dropped at
    #: load, so this never contains a factor the application cannot name.
    item_factors: npt.NDArray[np.float32]
    #: Current catalog ``book_id`` per row.
    book_ids: npt.NDArray[np.int64]
    regularization: float
    bundle: ArtifactBundle
    _row_by_book_id: Mapping[int, int]
    #: ``YᵀY``, precomputed — user-independent, so it is built once here
    #: rather than per request.
    _gramian: npt.NDArray[np.float64]

    @property
    def factor_count(self) -> int:
        return int(self.item_factors.shape[1])

    @property
    def item_count(self) -> int:
        return int(self.item_factors.shape[0])

    @property
    def model_version(self) -> str:
        return self.bundle.manifest.model_version

    def fold_in(
        self,
        preferences: Sequence[tuple[int, float]],
        *,
        regularization: float | None = None,
    ) -> npt.NDArray[np.float64] | None:
        """Solve a live user's latent factor from ``(book_id, confidence)``.

        Returns ``None`` when no supplied book resolves to a factor row — a
        genuinely cold user, which the caller must handle by falling back
        rather than by scoring against a zero vector (which would silently
        rank by nothing).

        rec-spec §9.2: this is recomputed per fresh batch. Nothing here
        mutates ``item_factors``; the global model is untouched by a live
        user's evidence, which is the property
        ``test_fold_in_does_not_mutate_item_factors`` pins down.
        """
        rows: list[int] = []
        weights: list[float] = []
        for book_id, confidence in preferences:
            row = self._row_by_book_id.get(book_id)
            if row is None or confidence <= 0.0:
                continue
            rows.append(row)
            weights.append(float(confidence))
        if not rows:
            return None

        lam = self.regularization if regularization is None else regularization
        factors = self.item_factors[rows].astype(np.float64, copy=False)
        confidence_vector = np.asarray(weights, dtype=np.float64)

        # A = YᵀY + Yᵀ(C−I)Y + λI, restricted to the user's own rows for the
        # middle term because (C−I) is zero everywhere else.
        scaled = factors * confidence_vector[:, None]
        a = self._gramian + factors.T @ scaled
        a[np.diag_indices_from(a)] += lam
        # b = Yᵀ C p, and p is 1 for every observed positive.
        b = scaled.sum(axis=0)

        try:
            return np.linalg.solve(a, b)
        except np.linalg.LinAlgError:
            # Singular only in degenerate cases (e.g. a zero factor matrix in
            # a fixture). Least-squares still gives a usable direction, and a
            # recommendation request must not raise for it.
            solution, *_ = np.linalg.lstsq(a, b, rcond=None)
            return np.asarray(solution, dtype=np.float64)

    def score_all(self, user_factor: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Score every resolved item for one user factor — a single dense
        matrix-vector product over ~92k rows (rec-spec §24)."""
        return self.item_factors.astype(np.float64, copy=False) @ user_factor

    def top_candidates(
        self,
        user_factor: npt.NDArray[np.float64],
        *,
        count: int,
        excluded_book_ids: frozenset[int] = frozenset(),
    ) -> tuple[tuple[int, float], ...]:
        """Highest-scoring eligible items as ``(book_id, score)``.

        Exclusions are applied *before* the top-k selection rather than by
        over-fetching and filtering afterwards, so a heavily-excluded user
        still gets ``count`` candidates instead of a short page.
        """
        if count <= 0:
            return ()
        scores = self.score_all(user_factor)

        eligible = np.ones(scores.size, dtype=bool)
        if excluded_book_ids:
            excluded_rows = [
                row
                for row in (self._row_by_book_id.get(book_id) for book_id in excluded_book_ids)
                if row is not None
            ]
            if excluded_rows:
                eligible[excluded_rows] = False

        candidate_rows = np.flatnonzero(eligible)
        if candidate_rows.size == 0:
            return ()

        candidate_scores = scores[candidate_rows]
        take = min(count, candidate_rows.size)
        # argpartition is O(n) against a full O(n log n) sort of 92k scores;
        # only the selected slice is then ordered.
        top = np.argpartition(-candidate_scores, take - 1)[:take]
        top = top[np.argsort(-candidate_scores[top], kind="stable")]

        return tuple(
            (int(self.book_ids[candidate_rows[index]]), float(candidate_scores[index]))
            for index in top
        )


def load_als_artifact(
    storage: LocalArtifactStorage,
    *,
    catalog: CatalogSnapshot,
    artifact_dir: str = ALS.directory,
    mmap: bool = False,
) -> AlsArtifact:
    bundle = load_artifact_bundle(
        storage, artifact_dir, catalog=catalog, expected_model_name=ALS.name
    )
    if not bundle.is_servable:
        raise IncompatibleArtifactError(f"ALS artifact is not servable: {bundle.resolution.reason}")

    factors = load_array(storage.resolve(artifact_dir, ITEM_FACTORS_FILENAME), mmap=mmap)
    if factors.ndim != 2:
        raise IncompatibleArtifactError(
            f"ALS item factors must be a 2-D matrix, got {factors.ndim}-D"
        )
    if factors.shape[0] != bundle.manifest.item_count:
        raise IncompatibleArtifactError(
            f"ALS item factors have {factors.shape[0]} rows, manifest declares "
            f"{bundle.manifest.item_count} items"
        )
    declared_factors = bundle.manifest.config.get(FACTORS_CONFIG_KEY)
    if isinstance(declared_factors, int) and factors.shape[1] != declared_factors:
        raise IncompatibleArtifactError(
            f"ALS item factors have width {factors.shape[1]}, manifest declares {declared_factors}"
        )
    if not np.all(np.isfinite(factors)):
        # A diverged training run produces NaN/inf factors that would score
        # every item as NaN and silently empty the feed.
        raise IncompatibleArtifactError("ALS item factors contain non-finite values")

    resolution = bundle.resolution
    resolved = np.ascontiguousarray(
        np.asarray(factors)[resolution.model_item_indices], dtype=np.float32
    )

    regularization = bundle.manifest.config.get(REGULARIZATION_CONFIG_KEY)
    lam = (
        float(regularization)
        if isinstance(regularization, int | float)
        else ALS_FOLD_IN_REGULARIZATION
    )

    return AlsArtifact(
        item_factors=resolved,
        book_ids=resolution.book_ids,
        regularization=lam,
        bundle=bundle,
        _row_by_book_id={int(book_id): row for row, book_id in enumerate(resolution.book_ids)},
        _gramian=resolved.astype(np.float64, copy=False).T
        @ resolved.astype(np.float64, copy=False),
    )
