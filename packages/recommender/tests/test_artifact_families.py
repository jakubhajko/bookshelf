"""Family loaders: popularity, source similarity, item metadata
(rec-spec §14, §15, §13)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from book_recommender.artifacts import (
    CatalogSnapshot,
    LocalArtifactStorage,
    build_csr,
    load_item_metadata_artifact,
    load_popularity_artifact,
    load_source_similarity_artifact,
    write_artifact,
    write_item_metadata,
    write_popularity_scores,
    write_source_similarity_graph,
)
from book_recommender.artifacts.item_metadata import (
    METADATA_FILENAME,
    NO_GENRE_CODE,
    TAGS_VERSION_CONFIG_KEY,
)
from book_recommender.artifacts.numeric import save_arrays
from book_recommender.artifacts.source_similarity import GRAPH_FILENAME, SOURCES_CONFIG_KEY
from book_recommender.config import ITEM_METADATA, POPULARITY, SOURCE_SIMILARITY
from book_recommender.exceptions import IncompatibleArtifactError

# Twenty books: model_item_index ``i`` is book_id ``10 * (i + 1)``, work_id
# ``w-i``. Twenty rather than four so that dropping a single book from the
# catalog lands at 5% unresolved — inside the loader's degradation threshold —
# and the "items disappear" tests exercise dropping rather than rejection.
ITEM_COUNT = 20
ITEMS = [(10 * (index + 1), f"w-{index}") for index in range(ITEM_COUNT)]
CATALOG = CatalogSnapshot.from_rows(f"{ITEM_COUNT}:2026-08-13T00:00:00", ITEMS)


def _catalog_without(*work_ids: str) -> CatalogSnapshot:
    remaining = [row for row in ITEMS if row[1] not in work_ids]
    return CatalogSnapshot.from_rows(f"{len(remaining)}:2026-09-01T00:00:00", remaining)


def _reimported_catalog() -> CatalogSnapshot:
    """Same works, all new autoincrement ids — what a rebuild produces."""
    return CatalogSnapshot.from_rows(
        f"{ITEM_COUNT}:2026-09-01T00:00:00",
        [(500 + index, work_id) for index, (_, work_id) in enumerate(ITEMS)],
    )


def _descending(count: int = ITEM_COUNT) -> list[float]:
    return [float(count - index) for index in range(count)]


@pytest.fixture
def storage(tmp_path: Path) -> LocalArtifactStorage:
    return LocalArtifactStorage(tmp_path)


# --- Popularity -------------------------------------------------------------


def _write_popularity(
    storage: LocalArtifactStorage,
    scores: list[float],
    *,
    items: list[tuple[int, str]] | None = None,
) -> None:
    write_artifact(
        storage,
        POPULARITY,
        model_version="20260813T120000Z",
        catalog_version=CATALOG.catalog_version,
        items=items if items is not None else ITEMS,
        payloads={"scores.npz": lambda path: write_popularity_scores(path, scores)},
    )


def test_popularity_ranking_preserves_artifact_order(storage: LocalArtifactStorage) -> None:
    _write_popularity(storage, _descending())

    artifact = load_popularity_artifact(storage, catalog=CATALOG)

    assert artifact.ranking[:4] == ((10, 20.0), (20, 19.0), (30, 18.0), (40, 17.0))
    assert len(artifact.ranking) == ITEM_COUNT
    assert artifact.model_version == "20260813T120000Z"


def test_popularity_ranking_uses_current_book_ids_after_a_reimport(
    storage: LocalArtifactStorage,
) -> None:
    """The whole point of ``work_id`` durability: the artifact says book 10,
    the live catalog says that work is now book 999, and the engine must be
    handed 999."""
    _write_popularity(storage, _descending())

    artifact = load_popularity_artifact(storage, catalog=_reimported_catalog())

    assert [book_id for book_id, _ in artifact.ranking][:4] == [500, 501, 502, 503]


def test_popularity_drops_books_missing_from_the_catalog(storage: LocalArtifactStorage) -> None:
    _write_popularity(storage, _descending())

    artifact = load_popularity_artifact(storage, catalog=_catalog_without("w-1"))

    assert len(artifact.ranking) == ITEM_COUNT - 1
    assert 20 not in [book_id for book_id, _ in artifact.ranking]
    assert artifact.ranking[:2] == ((10, 20.0), (30, 18.0))


def test_popularity_against_an_incompatible_catalog_raises(
    storage: LocalArtifactStorage,
) -> None:
    _write_popularity(storage, _descending())
    other = CatalogSnapshot.from_rows(
        "20:2027", [(index, f"x-{index}") for index in range(ITEM_COUNT)]
    )

    with pytest.raises(IncompatibleArtifactError, match="not servable"):
        load_popularity_artifact(storage, catalog=other)


def test_popularity_scores_out_of_order_are_rejected(storage: LocalArtifactStorage) -> None:
    """Item order *is* the ranking, so an unordered score column would make
    the feed's order meaningless while looking healthy."""
    _write_popularity(storage, [1.0, 5.0, 2.0, 3.0] + _descending(ITEM_COUNT - 4))

    with pytest.raises(IncompatibleArtifactError, match="not in descending order"):
        load_popularity_artifact(storage, catalog=CATALOG)


def test_popularity_score_column_of_the_wrong_length_is_rejected(
    storage: LocalArtifactStorage,
) -> None:
    _write_popularity(storage, _descending())
    # Rewrite the payload shorter and re-stamp the manifest so the checksum
    # check is not what catches it — the shape check must.
    write_popularity_scores(storage.resolve(POPULARITY.directory, "scores.npz"), [4.0, 3.0])
    manifest = storage.load_manifest(POPULARITY.directory)
    storage.save_manifest(POPULARITY.directory, manifest.model_copy(update={"files": ()}))

    with pytest.raises(IncompatibleArtifactError, match="expected 20"):
        load_popularity_artifact(storage, catalog=CATALOG)


def test_missing_popularity_artifact_raises(storage: LocalArtifactStorage) -> None:
    with pytest.raises(IncompatibleArtifactError):
        load_popularity_artifact(storage, catalog=CATALOG)


# --- Source similarity ------------------------------------------------------


def _write_graph(
    storage: LocalArtifactStorage,
    edges: list[tuple[int, int, int, int]],
    *,
    sources: list[str] | None = None,
    items: list[tuple[int, str]] | None = None,
) -> None:
    resolved_items = items if items is not None else ITEMS
    indptr, neighbor_indices, ranks, source_codes = build_csr(edges, item_count=len(resolved_items))
    write_artifact(
        storage,
        SOURCE_SIMILARITY,
        model_version="20260813T120000Z",
        catalog_version=CATALOG.catalog_version,
        items=resolved_items,
        payloads={
            GRAPH_FILENAME: lambda path: write_source_similarity_graph(
                path,
                indptr=indptr,
                neighbor_indices=neighbor_indices,
                ranks=ranks,
                source_codes=source_codes,
            )
        },
        config={SOURCES_CONFIG_KEY: sources if sources is not None else ["goodreads"]},
    )


def test_neighbours_come_back_in_rank_order_with_provenance(
    storage: LocalArtifactStorage,
) -> None:
    _write_graph(storage, [(0, 1, 0, 0), (0, 2, 1, 0), (2, 3, 0, 0)])

    graph = load_source_similarity_artifact(storage, catalog=CATALOG)

    assert graph.neighbor_book_ids(10) == (20, 30)
    assert [n.rank for n in graph.neighbors(10)] == [0, 1]
    assert {n.source for n in graph.neighbors(10)} == {"goodreads"}
    assert graph.neighbor_book_ids(30) == (40,)
    assert graph.neighbor_book_ids(20) == ()
    assert graph.edge_count == 3


def test_neighbour_limit_truncates_from_the_top_rank(storage: LocalArtifactStorage) -> None:
    _write_graph(storage, [(0, 1, 0, 0), (0, 2, 1, 0), (0, 3, 2, 0)])

    graph = load_source_similarity_artifact(storage, catalog=CATALOG)

    assert graph.neighbor_book_ids(10, limit=2) == (20, 30)


def test_unknown_book_has_no_neighbours(storage: LocalArtifactStorage) -> None:
    _write_graph(storage, [(0, 1, 0, 0)])

    graph = load_source_similarity_artifact(storage, catalog=CATALOG)

    assert graph.neighbor_book_ids(999999) == ()
    assert graph.neighbors(999999) == ()
    assert not graph.has_neighbors(999999)


def test_graph_contains_only_ids_present_in_the_live_catalog(
    storage: LocalArtifactStorage,
) -> None:
    """rec-spec §14's build-time invariant, re-asserted at load: when a book
    leaves the catalog, every edge pointing at it must disappear too — a
    generator must never be handed an id the application cannot resolve."""
    _write_graph(storage, [(0, 1, 0, 0), (0, 2, 1, 0), (1, 2, 0, 0), (2, 0, 0, 0)])
    thinned = _catalog_without("w-2")

    graph = load_source_similarity_artifact(storage, catalog=thinned)

    live_ids = set(thinned.work_id_to_book_id.values())
    for book_id in live_ids:
        assert set(graph.neighbor_book_ids(book_id)) <= live_ids
    # Book 30 ("w-2") is gone: its own row and both edges into it went with it.
    assert graph.neighbor_book_ids(10) == (20,)
    assert graph.neighbor_book_ids(20) == ()
    assert graph.edge_count == 1


def test_graph_survives_a_reimport_that_reassigns_book_ids(
    storage: LocalArtifactStorage,
) -> None:
    _write_graph(storage, [(0, 1, 0, 0)])

    graph = load_source_similarity_artifact(storage, catalog=_reimported_catalog())

    assert graph.neighbor_book_ids(500) == (501,)


def test_multiple_sources_keep_separate_provenance(storage: LocalArtifactStorage) -> None:
    _write_graph(storage, [(0, 1, 0, 0), (0, 2, 1, 1)], sources=["goodreads", "some-other-source"])

    graph = load_source_similarity_artifact(storage, catalog=CATALOG)

    assert [n.source for n in graph.neighbors(10)] == ["goodreads", "some-other-source"]
    assert graph.sources == ("goodreads", "some-other-source")


def test_a_graph_without_declared_sources_is_rejected(storage: LocalArtifactStorage) -> None:
    with pytest.raises(IncompatibleArtifactError, match="sources"):
        _write_graph(storage, [(0, 1, 0, 0)], sources=[])
        load_source_similarity_artifact(storage, catalog=CATALOG)


def test_an_edge_pointing_outside_the_item_space_is_rejected(
    storage: LocalArtifactStorage,
) -> None:
    _write_graph(storage, [(0, 1, 0, 0)])
    save_arrays(
        storage.resolve(SOURCE_SIMILARITY.directory, GRAPH_FILENAME),
        {
            "indptr": np.array([0] + [1] * ITEM_COUNT, dtype=np.int64),
            "neighbor_indices": np.array([99], dtype=np.int32),
            "ranks": np.array([0], dtype=np.int16),
            "source_codes": np.array([0], dtype=np.uint8),
        },
    )
    manifest = storage.load_manifest(SOURCE_SIMILARITY.directory)
    storage.save_manifest(SOURCE_SIMILARITY.directory, manifest.model_copy(update={"files": ()}))

    with pytest.raises(IncompatibleArtifactError, match="outside the artifact's item space"):
        load_source_similarity_artifact(storage, catalog=CATALOG)


def test_build_csr_produces_one_slice_per_item() -> None:
    indptr, neighbors, ranks, codes = build_csr(
        [(0, 1, 0, 0), (0, 2, 1, 0), (3, 0, 0, 0)], item_count=4
    )
    assert indptr == [0, 2, 2, 2, 3]
    assert neighbors == [1, 2, 0]
    assert ranks == [0, 1, 0]
    assert codes == [0, 0, 0]


def test_build_csr_rejects_unsorted_edges() -> None:
    with pytest.raises(ValueError, match="sorted by source_index"):
        build_csr([(2, 0, 0, 0), (1, 0, 0, 0)], item_count=4)


# --- Item metadata ----------------------------------------------------------


def _titles() -> list[str]:
    return ["Dune", "Hyperion", "Ubik", "Solaris"] + [
        f"Filler {index}" for index in range(4, ITEM_COUNT)
    ]


def _authors() -> list[str]:
    return ["Herbert", "Simmons", "Dick", "Lem"] + [
        f"Author {index}" for index in range(4, ITEM_COUNT)
    ]


def _genre_codes() -> list[int]:
    return [0, 0, 1, NO_GENRE_CODE] + [0] * (ITEM_COUNT - 4)


def _write_metadata(
    storage: LocalArtifactStorage,
    *,
    titles: list[str] | None = None,
    authors: list[str] | None = None,
    genre_codes: list[int] | None = None,
    genre_vocab: list[str] | None = None,
    config: dict[str, object] | None = None,
    **payload_overrides: object,
) -> None:
    write_artifact(
        storage,
        ITEM_METADATA,
        model_version="20260813T120000Z",
        catalog_version=CATALOG.catalog_version,
        items=ITEMS,
        payloads={
            METADATA_FILENAME: lambda path: write_item_metadata(
                path,
                titles=titles or _titles(),
                authors=authors or _authors(),
                genre_codes=genre_codes if genre_codes is not None else _genre_codes(),
                genre_vocab=genre_vocab if genre_vocab is not None else ["sci-fi", "fantasy"],
                **payload_overrides,  # type: ignore[arg-type]
            )
        },
        config=config if config is not None else {TAGS_VERSION_CONFIG_KEY: None},  # type: ignore[arg-type]
    )


def test_item_metadata_rows_load_by_current_book_id(storage: LocalArtifactStorage) -> None:
    _write_metadata(storage)

    table = load_item_metadata_artifact(storage, catalog=CATALOG)
    row = table.get(20)

    assert row is not None
    assert (row.title, row.author, row.genre, row.work_id) == (
        "Hyperion",
        "Simmons",
        "sci-fi",
        "w-1",
    )
    assert len(table) == ITEM_COUNT


def test_absent_genre_stays_absent_rather_than_becoming_a_category(
    storage: LocalArtifactStorage,
) -> None:
    _write_metadata(storage)

    table = load_item_metadata_artifact(storage, catalog=CATALOG)

    assert table.genre_of(40) is None
    assert table.genre_of(30) == "fantasy"


def test_tag_columns_are_an_empty_declared_contract_in_r3(
    storage: LocalArtifactStorage,
) -> None:
    """R5 fills these. Until then every row reports no tags, and the loader
    must not treat that as corruption."""
    _write_metadata(storage)

    table = load_item_metadata_artifact(storage, catalog=CATALOG)

    assert table.has_tags is False
    row = table.get(10)
    assert row is not None
    assert row.tags == ()


def test_tags_present_without_a_declared_version_are_rejected(
    storage: LocalArtifactStorage,
) -> None:
    """The cleaning rules that produced a tag set are part of its meaning, so
    an artifact cannot ship tags anonymously."""
    _write_metadata(
        storage,
        tag_indptr=[0] + [1] * ITEM_COUNT,
        tag_codes=[0],
        tag_vocab=["space-opera"],
        config={TAGS_VERSION_CONFIG_KEY: None},
    )

    with pytest.raises(IncompatibleArtifactError, match="declares no tags_version"):
        load_item_metadata_artifact(storage, catalog=CATALOG)


def test_a_declared_tags_version_with_no_tags_is_rejected(
    storage: LocalArtifactStorage,
) -> None:
    _write_metadata(storage, config={TAGS_VERSION_CONFIG_KEY: "tags-v1"})

    with pytest.raises(IncompatibleArtifactError, match="contains no tags"):
        load_item_metadata_artifact(storage, catalog=CATALOG)


def test_tags_load_when_both_the_columns_and_the_version_are_present(
    storage: LocalArtifactStorage,
) -> None:
    """The R5 shape, exercised now so the contract is known to work before
    anything depends on it."""
    _write_metadata(
        storage,
        tag_indptr=[0, 2, 2, 3] + [3] * (ITEM_COUNT - 3),
        tag_codes=[0, 1, 1],
        tag_vocab=["space-opera", "classic"],
        config={TAGS_VERSION_CONFIG_KEY: "tags-v1"},
    )

    table = load_item_metadata_artifact(storage, catalog=CATALOG)

    assert table.has_tags is True
    first = table.get(10)
    third = table.get(30)
    assert first is not None and first.tags == ("space-opera", "classic")
    assert third is not None and third.tags == ("classic",)


def test_a_genre_code_outside_the_vocabulary_is_rejected(
    storage: LocalArtifactStorage,
) -> None:
    _write_metadata(
        storage, genre_codes=[0, 1, 2, 3] + [0] * (ITEM_COUNT - 4), genre_vocab=["sci-fi"]
    )

    with pytest.raises(IncompatibleArtifactError, match="outside a 1-entry vocabulary"):
        load_item_metadata_artifact(storage, catalog=CATALOG)


def test_item_metadata_drops_books_missing_from_the_catalog(
    storage: LocalArtifactStorage,
) -> None:
    _write_metadata(storage)

    table = load_item_metadata_artifact(storage, catalog=_catalog_without("w-3"))

    assert len(table) == ITEM_COUNT - 1
    assert table.get(40) is None
    assert table.get(30) is not None
