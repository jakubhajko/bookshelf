"""Stable item mapping and its resolution against the live catalog
(ADR-0014, rec-spec §8).

Every artifact family shares one item-index space: position ``i`` in an
artifact's numeric columns is ``model_item_index`` ``i``, and this mapping
says which book that is. It stores both identifiers the system has, because
they answer different questions:

- ``work_id`` is the dataset's durable identity. It survives a database
  rebuild and is the only thing that can be trusted across the
  offline/online boundary.
- ``book_id`` is PostgreSQL's autoincrement surrogate, assigned at import
  time. It is what the serving path actually needs, and it is *not* durable
  — a re-import can hand the same integer to a different book.

So the mapping is written with both and **resolved through ``work_id`` at
load time**: :func:`resolve_item_mapping` looks each ``work_id`` up in the
live catalog and produces the ``book_id`` that is correct *now*, ignoring
the one recorded at build time except as a drift diagnostic. That is what
makes the failure ADR-0014 describes ("a model trained against one import
and served against another would silently recommend the wrong books")
impossible rather than merely unlikely.

Historical Book-Crossing user ids never appear here. This is an *item*
mapping; rec-spec §7.2's rule that historical integer users are not
application UUID users is upheld by there being no user identity in the
artifact contract at all.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np
import numpy.typing as npt

from book_recommender.artifacts.numeric import (
    load_arrays,
    require_int_array,
    require_string_column,
    save_arrays,
    string_column_arrays,
)
from book_recommender.exceptions import IncompatibleArtifactError

MAPPING_FILENAME = "mapping.npz"

# Above this share of an artifact's items failing to resolve, the artifact is
# not served at all. The judgement being encoded: a handful of books
# disappearing from the catalog between artifact build and serving is normal
# attrition and dropping them is correct, but a *large* unresolved fraction
# means the artifact and the catalog are describing different worlds, and
# serving the intersection would quietly produce a worse feed than the
# popularity floor while looking like it worked.
DEFAULT_MAX_UNRESOLVED_FRACTION = 0.10

# Unresolved ids are logged, so the sample is bounded — a mismatched catalog
# could otherwise put 92k work_ids into a single log line.
UNRESOLVED_SAMPLE_SIZE = 20


class MappingStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CatalogSnapshot:
    """The live catalog's identity table, read once by the application at
    provider-construction time and passed in.

    Deliberately a plain value object: this package has no database access
    (ADR-0006), and resolution must happen before serving starts rather than
    lazily during inference, when no session scope exists (ADR-0007).
    """

    catalog_version: str
    work_id_to_book_id: Mapping[str, int]

    @classmethod
    def from_rows(cls, catalog_version: str, rows: Sequence[tuple[int, str]]) -> CatalogSnapshot:
        """``rows`` are ``(book_id, work_id)`` for active books."""
        return cls(
            catalog_version=catalog_version,
            work_id_to_book_id={work_id: book_id for book_id, work_id in rows},
        )

    def __len__(self) -> int:
        return len(self.work_id_to_book_id)


@dataclass(frozen=True)
class ItemMapping:
    """``model_item_index`` (array position) → build-time ``book_id`` +
    durable ``work_id``."""

    book_ids: npt.NDArray[np.int64]
    work_ids: tuple[str, ...]

    def __len__(self) -> int:
        return len(self.work_ids)

    def save(self, path: Path) -> None:
        save_arrays(
            path,
            {
                "book_ids": self.book_ids.astype(np.int64, copy=False),
                **string_column_arrays("work_ids", self.work_ids),
            },
        )

    @classmethod
    def build(cls, rows: Sequence[tuple[int, str]]) -> ItemMapping:
        """``rows`` are ``(book_id, work_id)`` in model-item-index order."""
        return cls(
            book_ids=np.asarray([book_id for book_id, _ in rows], dtype=np.int64),
            work_ids=tuple(work_id for _, work_id in rows),
        )

    @classmethod
    def load(cls, path: Path, *, expected_item_count: int | None = None) -> ItemMapping:
        """Structural validation only — "is this file a well-formed mapping".
        Whether it matches the *live catalog* is :func:`resolve_item_mapping`'s
        separate question, because the two failures need different responses:
        a malformed file is a bug in the build, a mismatched one is an
        operational state that degrades.
        """
        arrays = load_arrays(path)
        book_ids = require_int_array(arrays, "book_ids", expected_size=expected_item_count)
        work_ids = require_string_column(arrays, "work_ids", expected_size=book_ids.size)
        if expected_item_count is not None and len(work_ids) != expected_item_count:
            raise IncompatibleArtifactError(
                f"mapping declares {len(work_ids)} items, manifest declares {expected_item_count}"
            )
        if len(set(work_ids)) != len(work_ids):
            raise IncompatibleArtifactError(
                "mapping contains duplicate work_ids — model_item_index would be ambiguous"
            )
        return cls(book_ids=book_ids, work_ids=work_ids)


@dataclass(frozen=True)
class MappingResolution:
    """What survived resolution, and what the caller should do about it."""

    status: MappingStatus
    item_count: int
    #: Model item indices that resolved, ascending.
    model_item_indices: npt.NDArray[np.int64]
    #: Current catalog ``book_id`` for each entry of ``model_item_indices``.
    book_ids: npt.NDArray[np.int64]
    unresolved_count: int
    unresolved_work_ids: tuple[str, ...]
    #: Items whose current ``book_id`` differs from the one recorded at build
    #: time. Not an error — it is the normal consequence of a re-import, and
    #: the reason resolution goes through ``work_id`` — but it is worth
    #: logging, because it means any *other* system still keyed on the old
    #: ids is now wrong.
    reassigned_count: int
    reason: str | None = None

    @property
    def resolved_count(self) -> int:
        return int(self.model_item_indices.size)

    @property
    def is_servable(self) -> bool:
        return self.status is not MappingStatus.REJECTED

    def index_to_book_id(self, item_count: int) -> npt.NDArray[np.int64]:
        """A dense ``model_item_index`` → ``book_id`` lookup array, with
        ``-1`` for dropped items. Lets family loaders filter their own
        columns with vectorized NumPy instead of per-row dict lookups."""
        lookup = np.full(item_count, -1, dtype=np.int64)
        lookup[self.model_item_indices] = self.book_ids
        return lookup


def resolve_item_mapping(
    mapping: ItemMapping,
    catalog: CatalogSnapshot,
    *,
    max_unresolved_fraction: float = DEFAULT_MAX_UNRESOLVED_FRACTION,
) -> MappingResolution:
    """Re-resolve an artifact's items against the live catalog by ``work_id``."""
    resolved_indices: list[int] = []
    resolved_book_ids: list[int] = []
    unresolved: list[str] = []
    reassigned = 0

    lookup = catalog.work_id_to_book_id
    for index, work_id in enumerate(mapping.work_ids):
        current_book_id = lookup.get(work_id)
        if current_book_id is None:
            unresolved.append(work_id)
            continue
        resolved_indices.append(index)
        resolved_book_ids.append(current_book_id)
        if current_book_id != int(mapping.book_ids[index]):
            reassigned += 1

    item_count = len(mapping)
    unresolved_count = len(unresolved)
    unresolved_fraction = unresolved_count / item_count if item_count else 0.0

    status = MappingStatus.OK
    reason: str | None = None
    if item_count == 0:
        status = MappingStatus.REJECTED
        reason = "artifact contains no items"
    elif unresolved_fraction > max_unresolved_fraction:
        status = MappingStatus.REJECTED
        reason = (
            f"{unresolved_count}/{item_count} items ({unresolved_fraction:.1%}) do not resolve "
            f"against catalog {catalog.catalog_version!r}, above the "
            f"{max_unresolved_fraction:.0%} threshold — rebuild the artifact"
        )
    elif unresolved_count:
        status = MappingStatus.DEGRADED
        reason = f"dropped {unresolved_count}/{item_count} items missing from the live catalog"

    return MappingResolution(
        status=status,
        item_count=item_count,
        model_item_indices=np.asarray(resolved_indices, dtype=np.int64),
        book_ids=np.asarray(resolved_book_ids, dtype=np.int64),
        unresolved_count=unresolved_count,
        unresolved_work_ids=tuple(unresolved[:UNRESOLVED_SAMPLE_SIZE]),
        reassigned_count=reassigned,
        reason=reason,
    )
