"""CLI: evaluate the content embeddings (rec-spec §23.2).

    make evaluate-content [ARGS="--sample 2000 --json"]

There is no ground truth for "semantically similar books", so rec-spec §23.2
prescribes a combination of imperfect proxies rather than a single score:

- **overlap with the resolved Goodreads similarity edges** — a noisy proxy,
  and explicitly *not* a target. rec-spec §23.2: "Do not overfit semantic
  embeddings to the Goodreads graph; it is only one imperfect source." High
  overlap says the embedding space agrees with a human-curated signal; low
  overlap could mean the embedding is wrong *or* that Goodreads is (its
  neighbour lists contain plenty of noise — see the R3 record).
- **author and genre coherence** — what fraction of a book's nearest
  neighbours share its author or broad genre. Sanity, not quality: 100%
  same-author would mean the space had collapsed onto authorship.
- **nearest-neighbour samples** — the check that a human actually reads.

Needs no training dependencies: it reads the artifacts, so it runs in the
ordinary environment.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

import numpy as np
from book_recommender.artifacts import (
    ContentEmbeddings,
    ItemMetadataTable,
    SourceSimilarityGraph,
    load_content_artifact,
    load_item_metadata_artifact,
    load_source_similarity_artifact,
)
from book_recommender.exceptions import IncompatibleArtifactError

from book_app.core.config import get_settings
from book_app.core.database import create_db_engine, create_session_factory
from book_app.core.logging import configure_logging, get_logger
from book_app.modules.recommendations.artifact_paths import (
    build_artifact_storage,
    read_catalog_snapshot,
)

logger = get_logger("book_app.cli.evaluate_content")

DEFAULT_SAMPLE = 2000
DEFAULT_K = 10
#: Fixed so two runs over the same artifact are comparable.
RANDOM_SEED = 0
SAMPLE_PREVIEW = 5


@dataclass(frozen=True)
class NeighbourEntry:
    book_id: int
    title: str
    author: str
    similarity: float
    in_source_graph: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "book_id": self.book_id,
            "title": self.title,
            "author": self.author,
            "similarity": round(self.similarity, 4),
            "in_source_graph": self.in_source_graph,
        }


@dataclass(frozen=True)
class NeighbourSample:
    book_id: int
    title: str
    author: str
    neighbours: tuple[NeighbourEntry, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "book_id": self.book_id,
            "title": self.title,
            "author": self.author,
            "neighbours": [entry.as_dict() for entry in self.neighbours],
        }


@dataclass
class ContentEvaluation:
    sample_size: int = 0
    k: int = 0
    source_overlap: float = 0.0
    source_recall: float = 0.0
    same_author_rate: float = 0.0
    same_genre_rate: float = 0.0
    mean_top_similarity: float = 0.0
    mean_kth_similarity: float = 0.0
    neighbour_samples: list[NeighbourSample] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "sample_size": self.sample_size,
            "k": self.k,
            "source_edge_overlap": round(self.source_overlap, 4),
            "source_edge_recall": round(self.source_recall, 4),
            "same_author_rate": round(self.same_author_rate, 4),
            "same_genre_rate": round(self.same_genre_rate, 4),
            "mean_top1_similarity": round(self.mean_top_similarity, 4),
            "mean_kth_similarity": round(self.mean_kth_similarity, 4),
            "neighbour_samples": [sample.as_dict() for sample in self.neighbour_samples],
        }


def evaluate(
    embeddings: ContentEmbeddings,
    graph: SourceSimilarityGraph,
    metadata: ItemMetadataTable,
    *,
    sample_size: int = DEFAULT_SAMPLE,
    k: int = DEFAULT_K,
) -> ContentEvaluation:
    """Compare semantic neighbours against Goodreads edges and metadata."""
    with_neighbours = [
        int(book_id) for book_id in embeddings.book_ids if graph.has_neighbors(int(book_id))
    ]
    if not with_neighbours:
        return ContentEvaluation(k=k)

    rng = np.random.default_rng(RANDOM_SEED)
    chosen = rng.choice(
        np.asarray(with_neighbours),
        size=min(sample_size, len(with_neighbours)),
        replace=False,
    )

    overlaps: list[float] = []
    recalls: list[float] = []
    same_author: list[float] = []
    same_genre: list[float] = []
    top_similarity: list[float] = []
    kth_similarity: list[float] = []
    samples: list[NeighbourSample] = []

    for book_id in sorted(int(value) for value in chosen):
        query = embeddings.vector_for(book_id)
        if query is None:
            continue
        neighbours = embeddings.search(query, count=k + 1, excluded_book_ids=frozenset({book_id}))
        if not neighbours:
            continue
        neighbour_ids = [candidate for candidate, _ in neighbours[:k]]
        source_ids = set(graph.neighbor_book_ids(book_id))

        hits = len(set(neighbour_ids) & source_ids)
        overlaps.append(hits / max(len(neighbour_ids), 1))
        recalls.append(hits / max(len(source_ids), 1))

        seed = metadata.get(book_id)
        if seed is not None:
            rows = [metadata.get(candidate) for candidate in neighbour_ids]
            present = [row for row in rows if row is not None]
            if present and seed.author:
                same_author.append(
                    sum(1 for row in present if row.author == seed.author) / len(present)
                )
            if present and seed.genre:
                same_genre.append(
                    sum(1 for row in present if row.genre == seed.genre) / len(present)
                )

        top_similarity.append(neighbours[0][1])
        if len(neighbours) >= k:
            kth_similarity.append(neighbours[k - 1][1])

        if len(samples) < SAMPLE_PREVIEW and seed is not None:
            samples.append(
                NeighbourSample(
                    book_id=book_id,
                    title=seed.title,
                    author=seed.author,
                    neighbours=tuple(
                        NeighbourEntry(
                            book_id=candidate,
                            title=(row.title if (row := metadata.get(candidate)) else ""),
                            author=(row.author if row else ""),
                            similarity=score,
                            in_source_graph=candidate in source_ids,
                        )
                        for candidate, score in neighbours[:5]
                    ),
                )
            )

    return ContentEvaluation(
        sample_size=len(overlaps),
        k=k,
        source_overlap=float(np.mean(overlaps)) if overlaps else 0.0,
        source_recall=float(np.mean(recalls)) if recalls else 0.0,
        same_author_rate=float(np.mean(same_author)) if same_author else 0.0,
        same_genre_rate=float(np.mean(same_genre)) if same_genre else 0.0,
        mean_top_similarity=float(np.mean(top_similarity)) if top_similarity else 0.0,
        mean_kth_similarity=float(np.mean(kth_similarity)) if kth_similarity else 0.0,
        neighbour_samples=samples,
    )


def _render(evaluation: ContentEvaluation, *, encoder: str, model_version: str) -> str:
    lines = [
        f"content evaluation — {model_version} ({encoder})",
        f"  books sampled          : {evaluation.sample_size}",
        f"  k                      : {evaluation.k}",
        "",
        "  Goodreads-edge agreement (a noisy proxy, not a target — rec-spec §23.2)",
        f"    overlap@k            : {evaluation.source_overlap:.4f}"
        "   (share of semantic neighbours that are also source edges)",
        f"    recall of source     : {evaluation.source_recall:.4f}"
        "   (share of a book's source edges recovered)",
        "",
        "  Coherence (sanity, not quality — 1.0 would mean collapse)",
        f"    same author          : {evaluation.same_author_rate:.4f}",
        f"    same broad genre     : {evaluation.same_genre_rate:.4f}",
        "",
        "  Similarity spread",
        f"    mean top-1           : {evaluation.mean_top_similarity:.4f}",
        f"    mean k-th            : {evaluation.mean_kth_similarity:.4f}",
        "",
        "  Nearest-neighbour samples:",
    ]
    for sample in evaluation.neighbour_samples:
        lines.append(f"    #{sample.book_id} {sample.title!r} — {sample.author}")
        for neighbour in sample.neighbours:
            marker = "*" if neighbour.in_source_graph else " "
            lines.append(
                f"      {marker} {neighbour.similarity:.3f}  "
                f"{neighbour.title[:44]!r} — {neighbour.author}"
            )
    lines.append("    (* also a Goodreads source-similarity edge)")
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the content-embedding artifact.")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    configure_logging(settings)

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    storage = build_artifact_storage(settings)
    try:
        with session_factory() as session:
            catalog = read_catalog_snapshot(session)
        try:
            embeddings = load_content_artifact(storage, catalog=catalog)
            graph = load_source_similarity_artifact(storage, catalog=catalog)
            metadata = load_item_metadata_artifact(storage, catalog=catalog)
        except IncompatibleArtifactError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    finally:
        engine.dispose()

    evaluation = evaluate(embeddings, graph, metadata, sample_size=args.sample, k=args.k)

    if args.json:
        print(
            json.dumps(
                {
                    "encoder": embeddings.encoder,
                    "model_version": embeddings.model_version,
                    **evaluation.as_dict(),
                },
                indent=2,
            )
        )
    else:
        print(
            _render(
                evaluation,
                encoder=embeddings.encoder,
                model_version=embeddings.model_version,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
