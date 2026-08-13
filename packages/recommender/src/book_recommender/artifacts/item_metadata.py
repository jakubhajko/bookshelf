"""Compact item-metadata artifact (recommender Phase R3 task 8, rec-spec §13,
§18, §21).

The ranker needs broad genre for diversity, the reason builder needs a title
and an author to say anything human, and interest inspection (rec-spec §13)
needs both plus cleaned shelf tags. None of that can come from PostgreSQL at
inference time (ADR-0014), so it is an artifact.

**The tag columns exist but are empty in R3.** The implementation plan is
explicit that tag cleaning belongs with the content-embedding work: "if tag
cleaning belongs more naturally in Phase 5, create the artifact contract now
and fill it there." So the CSR tag columns are written with zero edges and
``config["tags_version"]`` is ``None``, which is a *declared* absence — the
loader reports empty tag lists rather than failing, and R5 fills the columns
without a format change. An artifact whose ``tags_version`` is set but whose
columns are empty is a build bug, and is rejected.

**Genres are dictionary-encoded**, titles and authors are not. There are a
few hundred distinct genres over ~92k books, so codes into a vocabulary cost
4 bytes a row instead of ~15; titles are near-unique, so a vocabulary would
just add an indirection to the same bytes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from book_recommender.artifacts.loader import ArtifactBundle, load_artifact_bundle
from book_recommender.artifacts.local_storage import LocalArtifactStorage
from book_recommender.artifacts.mapping import CatalogSnapshot
from book_recommender.artifacts.numeric import (
    load_arrays,
    require_int_array,
    require_string_column,
    save_arrays,
    string_column_arrays,
)
from book_recommender.config import ITEM_METADATA
from book_recommender.exceptions import IncompatibleArtifactError

METADATA_FILENAME = "items.npz"

#: Manifest ``config`` key recording which tag-cleaning version filled the
#: tag columns. ``None`` until R5.
TAGS_VERSION_CONFIG_KEY = "tags_version"

_GENRE_CODES = "genre_codes"
_GENRE_VOCAB = "genre_vocab"
_TAG_INDPTR = "tag_indptr"
_TAG_CODES = "tag_codes"
_TAG_VOCAB = "tag_vocab"
_TITLE = "title"
_AUTHOR = "author"

#: Genre code meaning "this book has no broad genre in the catalog". Kept out
#: of the vocabulary so an absent genre can never be confused with a real one.
NO_GENRE_CODE = -1


@dataclass(frozen=True)
class ItemMetadataRow:
    book_id: int
    work_id: str
    title: str
    author: str
    genre: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class ItemMetadataTable:
    """Row lookup by current catalog ``book_id``."""

    _book_ids: npt.NDArray[np.int64]
    _work_ids: tuple[str, ...]
    _titles: tuple[str, ...]
    _authors: tuple[str, ...]
    _genres: tuple[str | None, ...]
    _tags: tuple[tuple[str, ...], ...]
    _row_by_book_id: dict[int, int]
    bundle: ArtifactBundle

    def __len__(self) -> int:
        return len(self._row_by_book_id)

    @property
    def has_tags(self) -> bool:
        return any(self._tags)

    def get(self, book_id: int) -> ItemMetadataRow | None:
        row = self._row_by_book_id.get(book_id)
        if row is None:
            return None
        return ItemMetadataRow(
            book_id=int(self._book_ids[row]),
            work_id=self._work_ids[row],
            title=self._titles[row],
            author=self._authors[row],
            genre=self._genres[row],
            tags=self._tags[row],
        )

    def genre_of(self, book_id: int) -> str | None:
        """The single field the surface reranker needs per candidate
        (rec-spec §19's genre-diversity caps), without building a whole row."""
        row = self._row_by_book_id.get(book_id)
        if row is None:
            return None
        return self._genres[row]


def write_item_metadata(
    path: Path,
    *,
    titles: Sequence[str],
    authors: Sequence[str],
    genre_codes: Sequence[int],
    genre_vocab: Sequence[str],
    tag_indptr: Sequence[int] | None = None,
    tag_codes: Sequence[int] | None = None,
    tag_vocab: Sequence[str] | None = None,
) -> None:
    """Builder-side writer. ``tag_*`` default to the empty CSR that R5
    replaces."""
    item_count = len(titles)
    save_arrays(
        path,
        {
            **string_column_arrays(_TITLE, list(titles)),
            **string_column_arrays(_AUTHOR, list(authors)),
            _GENRE_CODES: np.asarray(genre_codes, dtype=np.int32),
            **string_column_arrays(_GENRE_VOCAB, list(genre_vocab)),
            _TAG_INDPTR: np.asarray(
                tag_indptr if tag_indptr is not None else [0] * (item_count + 1), dtype=np.int64
            ),
            _TAG_CODES: np.asarray(tag_codes if tag_codes is not None else [], dtype=np.int32),
            **string_column_arrays(_TAG_VOCAB, list(tag_vocab) if tag_vocab is not None else []),
        },
    )


def load_item_metadata_artifact(
    storage: LocalArtifactStorage,
    *,
    catalog: CatalogSnapshot,
    artifact_dir: str = ITEM_METADATA.directory,
) -> ItemMetadataTable:
    bundle = load_artifact_bundle(
        storage, artifact_dir, catalog=catalog, expected_model_name=ITEM_METADATA.name
    )
    if not bundle.is_servable:
        raise IncompatibleArtifactError(
            f"item-metadata artifact is not servable: {bundle.resolution.reason}"
        )

    item_count = bundle.manifest.item_count
    arrays = load_arrays(storage.resolve(artifact_dir, METADATA_FILENAME))
    titles = require_string_column(arrays, _TITLE, expected_size=item_count)
    authors = require_string_column(arrays, _AUTHOR, expected_size=item_count)
    genre_codes = require_int_array(arrays, _GENRE_CODES, expected_size=item_count)
    genre_vocab = require_string_column(arrays, _GENRE_VOCAB)
    if genre_codes.size and int(genre_codes.max()) >= len(genre_vocab):
        raise IncompatibleArtifactError(
            f"genre code {int(genre_codes.max())} is outside a {len(genre_vocab)}-entry vocabulary"
        )

    tag_indptr = require_int_array(arrays, _TAG_INDPTR, expected_size=item_count + 1)
    tag_codes = require_int_array(arrays, _TAG_CODES, expected_size=int(tag_indptr[-1]))
    tag_vocab = require_string_column(arrays, _TAG_VOCAB)
    _validate_tags(bundle, tag_codes, tag_vocab)

    resolved = bundle.resolution.model_item_indices
    return ItemMetadataTable(
        _book_ids=bundle.resolution.book_ids,
        _work_ids=tuple(bundle.mapping.work_ids[int(index)] for index in resolved),
        _titles=tuple(titles[int(index)] for index in resolved),
        _authors=tuple(authors[int(index)] for index in resolved),
        _genres=tuple(
            genre_vocab[int(genre_codes[index])] if genre_codes[index] >= 0 else None
            for index in resolved
        ),
        _tags=tuple(
            tuple(
                tag_vocab[int(code)]
                for code in tag_codes[int(tag_indptr[index]) : int(tag_indptr[index + 1])]
            )
            for index in resolved
        ),
        _row_by_book_id={
            int(book_id): row for row, book_id in enumerate(bundle.resolution.book_ids)
        },
        bundle=bundle,
    )


def _validate_tags(
    bundle: ArtifactBundle, tag_codes: npt.NDArray[np.int64], tag_vocab: tuple[str, ...]
) -> None:
    declared_version = bundle.manifest.config.get(TAGS_VERSION_CONFIG_KEY)
    if declared_version is not None and tag_codes.size == 0:
        raise IncompatibleArtifactError(
            f"manifest declares tags_version={declared_version!r} but the artifact contains no tags"
        )
    if tag_codes.size and declared_version is None:
        raise IncompatibleArtifactError(
            "artifact contains tags but declares no tags_version — the cleaning "
            "rules that produced them would be unknown"
        )
    if tag_codes.size and int(tag_codes.max()) >= len(tag_vocab):
        raise IncompatibleArtifactError(
            f"tag code {int(tag_codes.max())} is outside a {len(tag_vocab)}-entry vocabulary"
        )
