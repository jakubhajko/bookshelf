"""Goodreads/source-similarity candidate generator (rec-spec §14).

rec-spec §14's central instruction is about what this generator must *not*
become: "Keep this generator semantically pure — it represents source/
Goodreads similarity edges. Do not quietly mix same-author, same-genre or
semantic KNN heuristics into this generator."

So this reads edges and nothing else. Same-author and same-genre are real
signals, but they belong in the ranker as features (rec-spec §18) where
their contribution stays visible. Folded in here they would be laundered
into "Goodreads says these are similar", which is false and unfalsifiable.

The generator is strong on Similar Books, moderate on Shelf, and a low-
weight source on Home (rec-spec §14, §20) — but *how much* it counts is
surface configuration in R7, not something this file decides.
"""

from __future__ import annotations

from book_recommender.artifacts.source_similarity import SourceSimilarityGraph
from book_recommender.config import GENERATOR_CONFIG_DEFAULT, GeneratorConfig
from book_recommender.generators.base import (
    GeneratorId,
    GeneratorRequest,
    GeneratorResult,
    GeneratorStatus,
    rank_all,
)
from book_recommender.generators.seeds import collect_seeds


class SourceSimilarityCandidateGenerator:
    """Aggregates source-graph neighbours of the request's seed books."""

    def __init__(
        self,
        graph: SourceSimilarityGraph | None,
        *,
        config: GeneratorConfig = GENERATOR_CONFIG_DEFAULT,
    ) -> None:
        self._graph = graph
        self._config = config

    @property
    def generator_id(self) -> GeneratorId:
        return GeneratorId.SOURCE_SIMILARITY

    def generate(self, request: GeneratorRequest) -> GeneratorResult:
        if self._graph is None:
            return GeneratorResult(
                generator=self.generator_id,
                status=GeneratorStatus.NO_ARTIFACT,
                diagnostics={"reason": "source similarity artifact not loaded"},
            )

        seeds = collect_seeds(request.user_context, request.surface_context, config=self._config)
        if not seeds:
            return GeneratorResult(
                generator=self.generator_id,
                status=GeneratorStatus.NO_EVIDENCE,
                diagnostics={"seeds": 0},
            )

        seed_ids = {seed.book_id for seed in seeds}
        totals: dict[int, float] = {}
        contributors: dict[int, int] = {}

        for seed in seeds:
            neighbors = self._graph.neighbors(
                seed.book_id, limit=self._config.source_neighbors_per_seed
            )
            for neighbor in neighbors:
                if neighbor.book_id in seed_ids or neighbor.book_id in request.excluded_book_ids:
                    continue
                # The graph stores an edge *rank*, not a weight — the source
                # never published a similarity score. Reciprocal rank turns
                # position into a comparable contribution without inventing
                # a similarity the data does not contain, and matches how
                # ADR-0017 fuses ranks one level up.
                #
                # Stored ranks are 0-based (the live graph spans 0-17) and
                # sparse, because the import drops edges whose target left
                # the catalog. `+ 1` makes the top edge worth 1.0 rather
                # than dividing by zero; the sparseness is deliberate and
                # means a surviving rank-5 edge keeps rank-5's weight.
                contribution = seed.weight / float(neighbor.rank + 1)
                totals[neighbor.book_id] = totals.get(neighbor.book_id, 0.0) + contribution
                contributors[neighbor.book_id] = contributors.get(neighbor.book_id, 0) + 1

        if not totals:
            return GeneratorResult(
                generator=self.generator_id,
                status=GeneratorStatus.EMPTY,
                diagnostics={"seeds": len(seeds), "seeds_with_edges": 0},
            )

        # Score desc, then *agreement* desc, then book_id asc.
        #
        # The middle term matters more than it looks. On the live graph a
        # reader's seeds produce large groups of candidates at an identical
        # aggregate score — one rank-0 edge from a shelf save is worth
        # exactly 3.0, and dozens of books tie there. RRF consumes only
        # rank, so whatever breaks that tie *is* the signal, and ordering
        # by book_id alone would make it catalog-insertion order.
        #
        # Two seeds independently pointing at the same book is real evidence
        # about that book; a low book_id is evidence about nothing. Ties
        # still fall back to book_id last, so the order stays deterministic.
        ordered = sorted(
            totals.items(),
            key=lambda item: (-item[1], -contributors.get(item[0], 0), item[0]),
        )
        candidates = rank_all(
            ordered,
            generator=self.generator_id,
            provenance=GeneratorId.SOURCE_SIMILARITY.value,
            limit=request.count,
            excluded_book_ids=request.excluded_book_ids,
            diagnostics_for={
                book_id: {"seeds": count} for book_id, count in contributors.items() if count > 1
            },
        )

        with_edges = sum(1 for seed in seeds if self._graph.has_neighbors(seed.book_id))
        return GeneratorResult(
            generator=self.generator_id,
            candidates=candidates,
            status=GeneratorStatus.OK,
            diagnostics={
                "seeds": len(seeds),
                "seeds_with_edges": with_edges,
                "pool": len(totals),
                "sources": self._graph.sources,
            },
        )
