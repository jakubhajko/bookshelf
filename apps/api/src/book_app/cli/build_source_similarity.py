"""CLI: export the resolved Goodreads source-similarity graph (rec-spec §14).

    uv run --project apps/api python -m book_app.cli.build_source_similarity [options]

or via ``make build-source-similarity``. The catalog import already resolved
Goodreads "similar works" to books in this catalog and dropped the rest, so
this builder does not resolve anything new — it exports what is there and
**re-validates the invariant** the import claims, because rec-spec §14 asks
for exactly that: "The import path already resolves similarities to items
present in the application catalog and drops unresolved/out-of-catalog
edges. Still validate this invariant during artifact build."

Two things it drops, both counted in the report rather than passed over:

- edges touching a non-active book (the foreign keys guarantee the row
  exists, not that it is still ``ACTIVE``);
- self-edges, which no similarity generator can use and which would show up
  as "this book is similar to itself" in diagnostics.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from book_recommender.artifacts import (
    LocalArtifactStorage,
    build_csr,
    write_artifact,
    write_source_similarity_graph,
)
from book_recommender.artifacts.source_similarity import GRAPH_FILENAME, SOURCES_CONFIG_KEY
from book_recommender.config import SOURCE_SIMILARITY
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from book_app.core.config import get_settings
from book_app.core.database import create_db_engine, create_session_factory
from book_app.core.logging import configure_logging, get_logger
from book_app.modules.books import repository as books_repository
from book_app.modules.books.models import BookSourceSimilarity
from book_app.modules.recommendations.artifact_build import (
    ArtifactBuildReport,
    new_model_version,
    register_model_version,
)
from book_app.modules.recommendations.artifact_paths import resolve_artifact_root

logger = get_logger("book_app.cli.build_source_similarity")

PREVIEW_SIZE = 5


@dataclass(frozen=True)
class SourceGraph:
    """Edges in model-item-index space, plus what was dropped getting there."""

    items: list[tuple[int, str]]
    #: ``(source_index, neighbor_index, rank, source_code)``, sorted.
    edges: list[tuple[int, int, int, int]]
    sources: list[str]
    edges_total: int
    dropped_out_of_catalog: int
    dropped_self_edges: int


def collect_source_graph(session: Session) -> SourceGraph:
    """Read the edges and project them onto the active catalog's item space.

    The item space is *the whole active catalog*, not just books that have
    neighbours. Every artifact family shares one ``model_item_index`` space
    (ADR-0014), and a book with no source neighbours still needs an index so
    the same mapping can serve the other families — it simply gets an empty
    CSR row.
    """
    items = books_repository.get_active_catalog_identities(session)
    index_by_book_id = {book_id: index for index, (book_id, _) in enumerate(items)}

    stmt = select(
        BookSourceSimilarity.book_id,
        BookSourceSimilarity.similar_book_id,
        BookSourceSimilarity.rank,
        BookSourceSimilarity.source,
    ).order_by(BookSourceSimilarity.book_id, BookSourceSimilarity.rank)

    sources: list[str] = []
    source_code_by_name: dict[str, int] = {}
    edges: list[tuple[int, int, int, int]] = []
    edges_total = 0
    dropped_out_of_catalog = 0
    dropped_self_edges = 0

    for book_id, similar_book_id, rank, source in session.execute(stmt):
        edges_total += 1
        if book_id == similar_book_id:
            dropped_self_edges += 1
            continue
        source_index = index_by_book_id.get(book_id)
        neighbor_index = index_by_book_id.get(similar_book_id)
        if source_index is None or neighbor_index is None:
            dropped_out_of_catalog += 1
            continue
        if source not in source_code_by_name:
            source_code_by_name[source] = len(sources)
            sources.append(source)
        edges.append((source_index, neighbor_index, rank, source_code_by_name[source]))

    # The SQL orders by (book_id, rank); build_csr needs (source_index, rank).
    # Those agree only because item indices follow book_id order — sorting
    # explicitly rather than relying on that coincidence, since the item
    # ordering is a property of get_active_catalog_identities, not of here.
    edges.sort(key=lambda edge: (edge[0], edge[2], edge[1]))

    return SourceGraph(
        items=items,
        edges=edges,
        sources=sources,
        edges_total=edges_total,
        dropped_out_of_catalog=dropped_out_of_catalog,
        dropped_self_edges=dropped_self_edges,
    )


def run_build(
    session_factory: sessionmaker[Session], *, artifact_root: Path, dry_run: bool = False
) -> ArtifactBuildReport:
    with session_factory() as session:
        graph = collect_source_graph(session)
        catalog_version = books_repository.get_catalog_version(session)
        model_version = new_model_version()

        books_with_neighbors = len({edge[0] for edge in graph.edges})
        stats: dict[str, int | str] = {
            "edges_exported": len(graph.edges),
            "edges_in_database": graph.edges_total,
            "dropped_out_of_catalog": graph.dropped_out_of_catalog,
            "dropped_self_edges": graph.dropped_self_edges,
            "books_with_neighbors": books_with_neighbors,
            "sources": ",".join(graph.sources),
        }
        preview = [
            {
                "book_id": graph.items[source_index][0],
                "work_id": graph.items[source_index][1],
                "similar_book_id": graph.items[neighbor_index][0],
                "rank": rank,
                "source": graph.sources[source_code],
            }
            for source_index, neighbor_index, rank, source_code in graph.edges[:PREVIEW_SIZE]
        ]

        if dry_run or not graph.items:
            return ArtifactBuildReport(
                model_name=SOURCE_SIMILARITY.name,
                model_version=model_version,
                catalog_version=catalog_version,
                item_count=len(graph.items),
                dry_run=dry_run,
                stats=stats,
                preview=preview,
            )

        indptr, neighbor_indices, ranks, source_codes = build_csr(
            graph.edges, item_count=len(graph.items)
        )
        written = write_artifact(
            LocalArtifactStorage(artifact_root),
            SOURCE_SIMILARITY,
            model_version=model_version,
            catalog_version=catalog_version,
            items=graph.items,
            payloads={
                GRAPH_FILENAME: lambda path: write_source_similarity_graph(
                    path,
                    indptr=indptr,
                    neighbor_indices=neighbor_indices,
                    ranks=ranks,
                    source_codes=source_codes,
                )
            },
            config={
                SOURCES_CONFIG_KEY: graph.sources,
                "edge_count": len(graph.edges),
                "books_with_neighbors": books_with_neighbors,
            },
        )
        register_model_version(session, SOURCE_SIMILARITY, written)
        session.commit()

        return ArtifactBuildReport(
            model_name=SOURCE_SIMILARITY.name,
            model_version=model_version,
            catalog_version=catalog_version,
            item_count=len(graph.items),
            dry_run=False,
            checksums=written.checksums,
            stale_files=written.stale_files,
            stats=stats,
            preview=preview,
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export resolved source-similarity edges to a recommender artifact."
    )
    parser.add_argument("--dry-run", action="store_true", help="Collect and report without writing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    configure_logging(settings)

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        report = run_build(
            session_factory,
            artifact_root=resolve_artifact_root(settings.artifact_storage_local_path),
            dry_run=args.dry_run,
        )
    finally:
        engine.dispose()

    print(report.summary_line())
    for line in report.warning_lines():
        print(line)
    for key, value in report.stats.items():
        print(f"  {key}: {value}")
    for row in report.preview:
        print(f"  #{row['book_id']} -> #{row['similar_book_id']} (rank {row['rank']})")

    logger.info("build_source_similarity_completed", **report.stats, dry_run=report.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
