"""Item-item collaborative-filtering candidate generator (rec-spec §10).

Reads precomputed neighbour rows for the request's seed books and
aggregates them. The offline artifact never changes for a live reader —
rec-spec §10: "User profile changes do not retrain the item-item model;
they only alter which seed items and weights are used on the next fresh
recommendation batch."

Where ALS is accurate and narrow, this is the broad one: R4 measured
coverage 0.547 and Gini 0.374 against ALS's 0.046/0.86. The two disagree
usefully, which is the entire argument for fusing them rather than picking
one.
"""

from __future__ import annotations

from book_recommender.artifacts.item_cf import ItemCfNeighbors
from book_recommender.config import (
    COLLABORATIVE_WEIGHTS_DEFAULT,
    GENERATOR_CONFIG_DEFAULT,
    CollaborativeSignalWeights,
    GeneratorConfig,
)
from book_recommender.generators.base import (
    GeneratorId,
    GeneratorRequest,
    GeneratorResult,
    GeneratorStatus,
    rank_all,
)
from book_recommender.generators.seeds import collect_seeds


class ItemItemCFCandidateGenerator:
    """Aggregates precomputed item neighbours over weighted seeds."""

    def __init__(
        self,
        neighbors: ItemCfNeighbors | None,
        *,
        weights: CollaborativeSignalWeights = COLLABORATIVE_WEIGHTS_DEFAULT,
        config: GeneratorConfig = GENERATOR_CONFIG_DEFAULT,
    ) -> None:
        self._neighbors = neighbors
        self._weights = weights
        self._config = config

    @property
    def generator_id(self) -> GeneratorId:
        return GeneratorId.ITEM_CF

    def generate(self, request: GeneratorRequest) -> GeneratorResult:
        if self._neighbors is None:
            return GeneratorResult(
                generator=self.generator_id,
                status=GeneratorStatus.NO_ARTIFACT,
                diagnostics={"reason": "item_cf artifact not loaded"},
            )

        seeds = collect_seeds(
            request.user_context,
            request.surface_context,
            weights=self._weights,
            config=self._config,
        )
        if not seeds:
            return GeneratorResult(
                generator=self.generator_id,
                status=GeneratorStatus.NO_EVIDENCE,
                diagnostics={"seeds": 0},
            )

        # `candidates_from_seeds` already aggregates duplicates across seeds,
        # excludes the seeds themselves, applies the exclusion set and sorts
        # deterministically (score desc, book_id asc). Re-implementing any of
        # that here would be a second definition of the same behaviour.
        scored = self._neighbors.candidates_from_seeds(
            [(seed.book_id, seed.weight) for seed in seeds],
            count=request.count,
            excluded_book_ids=request.excluded_book_ids,
            neighbors_per_seed=self._config.item_cf_neighbors_per_seed,
        )

        candidates = rank_all(
            scored,
            generator=self.generator_id,
            provenance=GeneratorId.ITEM_CF.value,
            limit=request.count,
            excluded_book_ids=request.excluded_book_ids,
        )

        seeds_with_neighbors = sum(
            1 for seed in seeds if self._neighbors.has_neighbors(seed.book_id)
        )
        return GeneratorResult(
            generator=self.generator_id,
            candidates=candidates,
            status=GeneratorStatus.OK if candidates else GeneratorStatus.EMPTY,
            diagnostics={
                "seeds": len(seeds),
                "seeds_with_neighbors": seeds_with_neighbors,
                "model_version": self._neighbors.model_version,
            },
        )
