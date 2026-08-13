"""Popularity candidate generator (rec-spec §15).

The safety net. rec-spec §15 gives it four jobs — universal fallback,
cold-start source, a small Home candidate source, and cover for any other
generator that is unavailable or returns too little — and one prohibition:
**popularity is not exploration.** Exploration is a reranking policy
(ADR-0017); conflating the two makes "exploration" mean "show more
bestsellers", which is the opposite of discovery.

This wraps the same precomputed ranking
``PopularityRecommendationEngine`` already serves, in the generator shape.
The engine is untouched and still works: it remains the standalone fallback
provider that runs when the pipeline itself cannot (rec-spec §27), and
duplicating the ranking logic here rather than reusing it would create two
definitions of "popular" that could drift.
"""

from __future__ import annotations

from collections.abc import Sequence

from book_recommender.generators.base import (
    Candidate,
    GeneratorId,
    GeneratorRequest,
    GeneratorResult,
    GeneratorStatus,
    rank_all,
)


class PopularityCandidateGenerator:
    """Serves a page of an already-ordered ranking.

    Order is trusted, never recomputed — the artifact builder owns the
    Bayesian-shrunk score (rec-spec §15: "Preserve the existing
    Bayesian-shrunk popularity approach"), and this package has no database
    to recompute it from anyway.
    """

    def __init__(
        self,
        ranking: Sequence[tuple[int, float]] | None,
        *,
        model_version: str = "",
    ) -> None:
        self._ranking = tuple(ranking) if ranking is not None else None
        self._model_version = model_version

    @property
    def generator_id(self) -> GeneratorId:
        return GeneratorId.POPULARITY

    def generate(self, request: GeneratorRequest) -> GeneratorResult:
        if self._ranking is None:
            # rec-spec §27: do not hide a missing artifact. If *popularity*
            # is missing there is nothing left to fall back to, which is
            # exactly why it must be visible rather than silently empty.
            return GeneratorResult(
                generator=self.generator_id,
                status=GeneratorStatus.NO_ARTIFACT,
                diagnostics={"reason": "popularity artifact not loaded"},
            )

        candidates: tuple[Candidate, ...] = rank_all(
            ((book_id, score) for book_id, score in self._ranking),
            generator=self.generator_id,
            provenance=GeneratorId.POPULARITY.value,
            limit=request.count,
            excluded_book_ids=request.excluded_book_ids,
        )

        return GeneratorResult(
            generator=self.generator_id,
            candidates=candidates,
            status=GeneratorStatus.OK if candidates else GeneratorStatus.EMPTY,
            diagnostics={
                "ranking_size": len(self._ranking),
                "model_version": self._model_version,
            },
        )
