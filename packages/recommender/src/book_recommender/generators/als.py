"""ALS collaborative-filtering candidate generator (rec-spec §9).

The global ALS model is trained offline over historical Book-Crossing
preference and never retrains for a live reader (rec-spec §9.2, CLAUDE.md).
What happens per request is a *fold-in*: solve one user factor against the
fixed item factors from current evidence, then score the catalog.

The seam that matters here is identity. Historical integer users are not
application users and are never joined as such (CLAUDE.md); a live reader
has no row in the trained user matrix and does not need one. Fold-in is
precisely the mechanism that makes that true — the reader is expressed
entirely as a point in the item-factor space.

This is also the most concentrated generator in the system. R4 measured
coverage 0.046 and Gini 0.86 against item-CF's 0.547/0.374 — it is accurate
and it recommends a narrow slice of the catalog. That is a fusion-weight
problem (R7) and a reranking problem (ADR-0017), not something to correct
here by degrading the model's own ordering.
"""

from __future__ import annotations

from book_recommender.artifacts.als import AlsArtifact
from book_recommender.config import (
    COLLABORATIVE_WEIGHTS_DEFAULT,
    GENERATOR_CONFIG_DEFAULT,
    CollaborativeSignalWeights,
    GeneratorConfig,
)
from book_recommender.contracts.context import SimilarBooksContext
from book_recommender.generators.base import (
    GeneratorId,
    GeneratorRequest,
    GeneratorResult,
    GeneratorStatus,
    rank_all,
)
from book_recommender.generators.seeds import collect_seeds


class AlsCandidateGenerator:
    """Folds the request's evidence into a user factor and retrieves."""

    def __init__(
        self,
        artifact: AlsArtifact | None,
        *,
        weights: CollaborativeSignalWeights = COLLABORATIVE_WEIGHTS_DEFAULT,
        config: GeneratorConfig = GENERATOR_CONFIG_DEFAULT,
    ) -> None:
        self._artifact = artifact
        self._weights = weights
        self._config = config

    @property
    def generator_id(self) -> GeneratorId:
        return GeneratorId.ALS

    def generate(self, request: GeneratorRequest) -> GeneratorResult:
        if isinstance(request.surface_context, SimilarBooksContext):
            # rec-spec §20.3 lists the source graph, item-CF, semantic and
            # popularity for Similar Books, and says global personalization
            # should be "absent or only a tiny tie-break feature". A
            # folded-in *global* user factor is the definition of global
            # personalization, so it does not run here — that is what turns
            # "what is like this book" into "more books you may like".
            return GeneratorResult(
                generator=self.generator_id,
                status=GeneratorStatus.NOT_APPLICABLE,
                diagnostics={"reason": "als does not run on the similar-books surface"},
            )

        if self._artifact is None:
            return GeneratorResult(
                generator=self.generator_id,
                status=GeneratorStatus.NO_ARTIFACT,
                diagnostics={"reason": "als artifact not loaded"},
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

        # On Shelf, the seeds are the target shelf's books, so this folds in
        # a *pseudo-user whose entire taste is that shelf* — rec-spec §20.2's
        # "ALS fold-in using target-shelf books as a pseudo-user". Same code
        # path, different evidence; the surface never needs a second solver.
        user_factor = self._artifact.fold_in([(seed.book_id, seed.weight) for seed in seeds])
        if user_factor is None:
            # Not one seed resolved to a factor row: every book this reader
            # likes is absent from the historical model. Scoring against a
            # zero vector would rank by nothing at all and look like a
            # working recommendation, so report it instead.
            return GeneratorResult(
                generator=self.generator_id,
                status=GeneratorStatus.NO_EVIDENCE,
                diagnostics={"seeds": len(seeds), "reason": "no seed resolved to a factor row"},
            )

        scored = self._artifact.top_candidates(
            user_factor,
            count=request.count,
            # Seeds are excluded alongside application eligibility: a reader's
            # own books scoring highly against their own folded-in factor is
            # arithmetic, not a recommendation.
            excluded_book_ids=request.excluded_book_ids | {seed.book_id for seed in seeds},
        )

        candidates = rank_all(
            scored,
            generator=self.generator_id,
            provenance=GeneratorId.ALS.value,
            limit=request.count,
            excluded_book_ids=request.excluded_book_ids,
        )

        return GeneratorResult(
            generator=self.generator_id,
            candidates=candidates,
            status=GeneratorStatus.OK if candidates else GeneratorStatus.EMPTY,
            diagnostics={
                "seeds": len(seeds),
                "factors": self._artifact.factor_count,
                "model_version": self._artifact.model_version,
            },
        )
