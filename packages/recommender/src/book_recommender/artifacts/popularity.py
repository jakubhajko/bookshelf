"""Popularity artifact reader/writer (rec-spec §15, ADR-0014).

Before recommender Phase R3 this parsing lived in ``apps/api``'s
``modules/recommendations/wiring.py`` as an inline
``json.loads(...)["scores"]``. ADR-0014 moves it here: application wiring
selects and constructs engines, it does not know model file formats.

The payload is one ``float64`` column, already ordered most-popular-first by
the builder. Storing the *order* implicitly (as array position) rather than
re-sorting at load time is deliberate — the artifact's ordering is the
authoritative one, and the loader verifies it rather than imposing it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from book_recommender.artifacts.loader import ArtifactBundle, load_artifact_bundle
from book_recommender.artifacts.local_storage import LocalArtifactStorage
from book_recommender.artifacts.mapping import CatalogSnapshot
from book_recommender.artifacts.numeric import load_arrays, require_float_array, save_arrays
from book_recommender.config import POPULARITY
from book_recommender.exceptions import IncompatibleArtifactError

SCORES_FILENAME = "scores.npz"
_SCORES_COLUMN = "scores"


@dataclass(frozen=True)
class PopularityArtifact:
    """A ranking the popularity engine can serve directly."""

    #: ``(book_id, score)`` most-popular-first, keyed on *current* book ids.
    ranking: tuple[tuple[int, float], ...]
    bundle: ArtifactBundle

    @property
    def model_version(self) -> str:
        return self.bundle.manifest.model_version


def write_popularity_scores(path: Path, scores: Sequence[float]) -> None:
    """Builder-side writer, so the format has exactly one definition."""
    save_arrays(path, {_SCORES_COLUMN: np.asarray(scores, dtype=np.float64)})


def load_popularity_artifact(
    storage: LocalArtifactStorage,
    *,
    catalog: CatalogSnapshot,
    artifact_dir: str = POPULARITY.directory,
) -> PopularityArtifact:
    """Load, validate and resolve the popularity artifact.

    Raises :class:`IncompatibleArtifactError` if the artifact is missing,
    corrupt or unservable against ``catalog`` — the caller degrades to an
    empty ranking, which is what "popularity is the floor" means when the
    floor itself is unavailable.
    """
    bundle = load_artifact_bundle(
        storage, artifact_dir, catalog=catalog, expected_model_name=POPULARITY.name
    )
    if not bundle.is_servable:
        raise IncompatibleArtifactError(
            f"popularity artifact is not servable: {bundle.resolution.reason}"
        )

    scores_path = storage.resolve(artifact_dir, SCORES_FILENAME)
    scores = require_float_array(
        load_arrays(scores_path), _SCORES_COLUMN, expected_size=bundle.manifest.item_count
    )

    resolution = bundle.resolution
    resolved_scores = scores[resolution.model_item_indices]
    if resolved_scores.size > 1 and bool(np.any(np.diff(resolved_scores) > 1e-9)):
        # The engine treats artifact order as authoritative and does not
        # re-sort (rec-spec §18). If the builder ever emitted an unordered
        # column, the feed would silently be ordered by nothing in
        # particular, so this is checked rather than assumed.
        raise IncompatibleArtifactError(
            "popularity scores are not in descending order — the artifact's "
            "item order is not a ranking"
        )

    ranking = tuple(
        (int(book_id), float(score))
        for book_id, score in zip(resolution.book_ids, resolved_scores, strict=True)
    )
    return PopularityArtifact(ranking=ranking, bundle=bundle)
