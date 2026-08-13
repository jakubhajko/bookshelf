"""Shared historical-interaction transform for the CF builders
(rec-spec §7.2, §9.1, §10; ADR-0014).

Both collaborative-filtering families train on the same thing:
``data/processed/interactions.parquet``, resolved onto the live catalog and
turned into positive-preference confidences. Doing that twice would let ALS
and item-item CF silently disagree about what a "positive" is, so it happens
once, here, and both builders consume the result.

Deliberately free of ``scipy`` and ``implicit``: this module is pure pandas
and NumPy, so it runs — and is tested — without the training dependency
group installed. Building the sparse matrix from these triplets is the
trainers' job.

Three invariants this module exists to enforce, all of them rules the rest
of the system would have no way to check later:

**Historical users are not application users.** rec-spec §7.2 and CLAUDE.md
both state it. Here it is structural: ``user_id`` is read as an opaque
row-grouping integer, is remapped to a dense training index, and never
leaves this module in any form that could be joined to a ``users`` row. The
artifacts the trainers write contain item factors and neighbour lists only.

**Unresolved works are dropped and reported**, never silently. The parquet
carries 92,526 works; the live catalog has fewer, and the difference is a
number the build must state rather than absorb.

**No timestamps are invented.** The parquet has none. Nothing here orders,
weights or splits by time, and the holdout is explicitly random per user
(rec-spec §23.1) rather than pretending otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pandas as pd
from book_recommender.artifacts import CatalogSnapshot
from book_recommender.config import HistoricalInteractionTransform

#: Exact schema the parquet must have. rec-spec's Phase 4 task list says
#: "Validate schema rather than assuming it" — a silently renamed or
#: retyped column would otherwise surface as a strange metric weeks later.
REQUIRED_COLUMNS: Mapping[str, str] = {
    "user_id": "integer",
    "work_id": "string",
    "rating": "integer",
    "is_explicit": "boolean",
}

MIN_RATING = 0
MAX_RATING = 10


class InteractionDataError(ValueError):
    """The training data is not what the transform requires."""


@dataclass(frozen=True)
class InteractionDataset:
    """Positive-preference triplets in dense training-index space.

    ``user_indices`` index this dataset's own dense user space, which exists
    only inside a training run. ``item_indices`` are ``model_item_index``
    values in the shared artifact item space (ADR-0014), so they mean the
    same thing here as in every artifact.
    """

    user_indices: npt.NDArray[np.int32]
    item_indices: npt.NDArray[np.int32]
    confidences: npt.NDArray[np.float32]
    user_count: int
    item_count: int
    transform_version: str
    report: InteractionReport

    def __len__(self) -> int:
        return int(self.confidences.size)


@dataclass(frozen=True)
class InteractionReport:
    """What the transform used and what it threw away, per rec-spec's
    "Report counts dropped/used by rating bucket and mapping status"."""

    rows_total: int
    rows_used: int
    rows_dropped_unresolved_work: int
    rows_dropped_by_rating: dict[int, int] = field(default_factory=dict)
    works_total: int = 0
    works_resolved: int = 0
    works_unresolved: int = 0
    unresolved_work_sample: tuple[str, ...] = ()
    users_total: int = 0
    users_used: int = 0
    items_used: int = 0

    def as_stats(self) -> dict[str, int | str]:
        """Flat, log-safe counters for a build report."""
        dropped = ", ".join(
            f"{rating}:{count}" for rating, count in sorted(self.rows_dropped_by_rating.items())
        )
        return {
            "rows_total": self.rows_total,
            "rows_used": self.rows_used,
            "rows_dropped_unresolved_work": self.rows_dropped_unresolved_work,
            "rows_dropped_by_rating": dropped or "none",
            "works_total": self.works_total,
            "works_resolved": self.works_resolved,
            "works_unresolved": self.works_unresolved,
            "users_total": self.users_total,
            "users_used": self.users_used,
            "items_used": self.items_used,
        }


def validate_schema(frame: pd.DataFrame) -> None:
    """Fail loudly and specifically rather than let pandas coerce."""
    missing = [name for name in REQUIRED_COLUMNS if name not in frame.columns]
    if missing:
        raise InteractionDataError(
            f"interactions data is missing column(s) {missing}; expected {sorted(REQUIRED_COLUMNS)}"
        )
    checks = {
        "user_id": pd.api.types.is_integer_dtype,
        "work_id": lambda s: pd.api.types.is_string_dtype(s) or pd.api.types.is_object_dtype(s),
        "rating": pd.api.types.is_integer_dtype,
        "is_explicit": pd.api.types.is_bool_dtype,
    }
    for name, is_valid in checks.items():
        if not is_valid(frame[name]):
            raise InteractionDataError(
                f"interactions column {name!r} must be {REQUIRED_COLUMNS[name]}, "
                f"got dtype {frame[name].dtype}"
            )
    if frame[list(REQUIRED_COLUMNS)].isna().to_numpy().any():
        raise InteractionDataError("interactions data contains nulls in required columns")

    ratings = frame["rating"]
    if ratings.empty:
        # An empty dataset is a legitimate state (a fresh checkout with no
        # parquet rows yet); min()/max() on it are NaN, not a range error.
        return
    if int(ratings.min()) < MIN_RATING or int(ratings.max()) > MAX_RATING:
        raise InteractionDataError(
            f"ratings must be within [{MIN_RATING}, {MAX_RATING}], got "
            f"[{int(ratings.min())}, {int(ratings.max())}]"
        )
    # rating 0 means "implicit positive" (rec-spec §7.2). If a row claimed to
    # be explicit while carrying 0, the transform's central distinction would
    # be ambiguous, so it is checked rather than assumed.
    contradictory = int(((ratings == 0) & frame["is_explicit"]).sum())
    if contradictory:
        raise InteractionDataError(
            f"{contradictory} row(s) are marked explicit with rating 0 — "
            "rating 0 is the implicit-positive marker (rec-spec §7.2)"
        )


def read_interactions(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise InteractionDataError(
            f"no interactions dataset at {path} — see data/README.md for how to produce it"
        )
    frame = pd.read_parquet(path, columns=list(REQUIRED_COLUMNS))
    validate_schema(frame)
    return frame


def build_dataset(
    frame: pd.DataFrame,
    catalog: CatalogSnapshot,
    transform: HistoricalInteractionTransform,
    *,
    unresolved_sample_size: int = 10,
) -> InteractionDataset:
    """Resolve works onto the catalog and apply the confidence transform.

    Resolution is by ``work_id``, the durable identity (ADR-0014/ADR-0020),
    and produces ``model_item_index`` values in the *catalog's* item order —
    the same order every artifact family uses — rather than an order local
    to this dataset. That is what lets an ALS item factor and a popularity
    score refer to the same row.
    """
    validate_schema(frame)

    item_index_by_work = _catalog_item_index(catalog)
    work_ids = frame["work_id"].to_numpy(dtype=object)
    ratings = frame["rating"].to_numpy(dtype=np.int16)

    item_index = np.fromiter(
        (item_index_by_work.get(work_id, -1) for work_id in work_ids),
        dtype=np.int64,
        count=len(frame),
    )
    resolved_mask = item_index >= 0

    confidence_by_rating = {
        rating: transform.confidence_for(int(rating))
        for rating in range(MIN_RATING, MAX_RATING + 1)
    }
    positive_ratings = np.array(
        [rating for rating, weight in confidence_by_rating.items() if weight is not None],
        dtype=np.int16,
    )
    positive_mask = np.isin(ratings, positive_ratings)

    keep = resolved_mask & positive_mask

    # Reported separately and precisely: a row dropped because its work is
    # gone is a data-freshness problem, a row dropped because it is a 2/10 is
    # the transform working as designed. Collapsing them would hide the first.
    dropped_by_rating: dict[int, int] = {}
    for rating in range(MIN_RATING, MAX_RATING + 1):
        if confidence_by_rating[rating] is not None:
            continue
        count = int(((ratings == rating) & resolved_mask).sum())
        if count:
            dropped_by_rating[rating] = count

    unresolved_works = pd.unique(work_ids[~resolved_mask])
    kept = frame.loc[keep]
    kept_item_index = item_index[keep]

    user_codes, unique_users = pd.factorize(kept["user_id"].to_numpy(), sort=True)
    confidences = np.fromiter(
        (confidence_by_rating[int(rating)] or 0.0 for rating in kept["rating"].to_numpy()),
        dtype=np.float32,
        count=len(kept),
    )

    report = InteractionReport(
        rows_total=len(frame),
        rows_used=int(keep.sum()),
        rows_dropped_unresolved_work=int((~resolved_mask).sum()),
        rows_dropped_by_rating=dropped_by_rating,
        works_total=int(pd.unique(work_ids).size),
        works_resolved=int(pd.unique(work_ids[resolved_mask]).size),
        works_unresolved=int(unresolved_works.size),
        unresolved_work_sample=tuple(str(w) for w in unresolved_works[:unresolved_sample_size]),
        users_total=int(pd.unique(frame["user_id"].to_numpy()).size),
        users_used=int(unique_users.size),
        items_used=int(np.unique(kept_item_index).size),
    )

    return InteractionDataset(
        user_indices=user_codes.astype(np.int32, copy=False),
        item_indices=kept_item_index.astype(np.int32, copy=False),
        confidences=confidences,
        user_count=int(unique_users.size),
        item_count=len(catalog),
        transform_version=transform.version,
        report=report,
    )


def _catalog_item_index(catalog: CatalogSnapshot) -> dict[str, int]:
    """``work_id`` → ``model_item_index``.

    The item space is the catalog in ``book_id`` order, matching
    ``books_repository.get_active_catalog_identities`` and therefore every
    other artifact family (see cli/build_source_similarity.py).
    """
    ordered = sorted(catalog.work_id_to_book_id.items(), key=lambda item: item[1])
    return {work_id: index for index, (work_id, _) in enumerate(ordered)}


def catalog_items_in_index_order(catalog: CatalogSnapshot) -> list[tuple[int, str]]:
    """``(book_id, work_id)`` in ``model_item_index`` order, for the writer."""
    return sorted(
        ((book_id, work_id) for work_id, book_id in catalog.work_id_to_book_id.items()),
        key=lambda row: row[0],
    )
