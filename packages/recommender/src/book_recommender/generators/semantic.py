"""Semantic/content candidate generator (rec-spec §11, §12, §20).

The only generator that issues *several* queries per request, because a
reader has several interests and rec-spec §12.2 refuses to collapse them
into one centroid. Each query carries its own provenance, so a candidate
can say which interest or shelf found it — rec-spec §21's requirement that
a reason correspond to real evidence.

Query strategies, by surface:

============  ==========================================================
Home          one query per inferred interest cluster, plus one per
              explicit shelf profile (rec-spec §20.1, both HIGH)
Shelf         the target shelf's own profile (§20.2, VERY HIGH). The
              reader's global interests are deliberately absent: the
              goal is to extend *this shelf*, not their whole taste
Similar       the source book's own vector (§20.3)
============  ==========================================================

Retrieval is exact — one batched matrix multiply over the full catalog
(rec-spec §11.1, §24). Measured on the live 92,524-book artifact, a single
query takes 2.8 ms, which is why CLAUDE.md rules out a vector database at
this scale.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from book_recommender.artifacts.content import ContentEmbeddings
from book_recommender.config import GENERATOR_CONFIG_DEFAULT, GeneratorConfig
from book_recommender.contracts.context import ShelfContext, SimilarBooksContext
from book_recommender.generators.base import (
    PROVENANCE_GLOBAL,
    PROVENANCE_INTEREST,
    PROVENANCE_SHELF,
    PROVENANCE_SOURCE_BOOK,
    PROVENANCE_TARGET_SHELF,
    GeneratorId,
    GeneratorRequest,
    GeneratorResult,
    GeneratorStatus,
    interleave,
)
from book_recommender.profiling import ProfileStrategy, query_vector_for

#: One query's ranked results, tagged with what produced it.
_Query = tuple[str, npt.NDArray[np.float64]]


class SemanticCandidateGenerator:
    """Retrieves nearest catalog books for each of the request's queries."""

    def __init__(
        self,
        embeddings: ContentEmbeddings | None,
        *,
        config: GeneratorConfig = GENERATOR_CONFIG_DEFAULT,
    ) -> None:
        self._embeddings = embeddings
        self._config = config

    @property
    def generator_id(self) -> GeneratorId:
        return GeneratorId.SEMANTIC

    def generate(self, request: GeneratorRequest) -> GeneratorResult:
        embeddings = self._embeddings
        if embeddings is None:
            return GeneratorResult(
                generator=self.generator_id,
                status=GeneratorStatus.NO_ARTIFACT,
                diagnostics={"reason": "content artifact not loaded"},
            )

        queries = self._queries(request, embeddings)
        if not queries:
            return GeneratorResult(
                generator=self.generator_id,
                status=GeneratorStatus.NO_EVIDENCE,
                diagnostics={"queries": 0, **self._profile_diagnostics(request)},
            )

        # rec-spec §24: "batch all semantic query vectors into one matrix
        # multiply where practical instead of scanning the catalog
        # separately in Python loops."
        matrix = np.vstack([vector for _, vector in queries])
        results = embeddings.search_many(
            matrix,
            count=request.count,
            excluded_book_ids=request.excluded_book_ids,
        )

        ranked_lists: list[tuple[str, list[tuple[int, float]]]] = []
        for (provenance, _), hits in zip(queries, results, strict=True):
            kept = [
                (book_id, score)
                for book_id, score in hits
                if score > self._config.semantic_min_score
            ]
            if kept:
                ranked_lists.append((provenance, kept))

        if not ranked_lists:
            return GeneratorResult(
                generator=self.generator_id,
                status=GeneratorStatus.EMPTY,
                diagnostics={
                    "queries": len(queries),
                    "min_score": self._config.semantic_min_score,
                    **self._profile_diagnostics(request),
                },
            )

        candidates = interleave(
            ranked_lists,
            generator=self.generator_id,
            limit=request.count,
            excluded_book_ids=request.excluded_book_ids,
        )

        return GeneratorResult(
            generator=self.generator_id,
            candidates=candidates,
            status=GeneratorStatus.OK if candidates else GeneratorStatus.EMPTY,
            diagnostics={
                "queries": len(queries),
                "queries_with_hits": len(ranked_lists),
                "model_version": embeddings.model_version,
                "encoder": embeddings.encoder,
                **self._profile_diagnostics(request),
            },
        )

    def _queries(self, request: GeneratorRequest, embeddings: ContentEmbeddings) -> list[_Query]:
        surface = request.surface_context

        if isinstance(surface, SimilarBooksContext):
            vector = embeddings.vector_for(surface.source_book_id)
            if vector is None:
                # The source book has no embedding — added since the last
                # content build (risk #108). Similar Books then relies on
                # the source graph and item-CF, which is rec-spec §27's
                # intended degradation, not an error.
                return []
            return [(PROVENANCE_SOURCE_BOOK, np.asarray(vector, dtype=np.float64))]

        profile = request.semantic_profile
        if profile is None:
            return []

        if isinstance(surface, ShelfContext):
            target = str(surface.shelf_id)
            for shelf in profile.shelves:
                if shelf.shelf_id == target:
                    return [(PROVENANCE_TARGET_SHELF, shelf.query_vector)]
            return []

        # Home (and Search, which has no query understanding yet): every
        # interest and every shelf, strongest first so `interleave`'s
        # round-robin gives the strongest interest the first slot.
        #
        # rec-spec §12.2's last fallback rung produces one *global weighted
        # centroid* rather than an inferred interest — the clustering found
        # no structure. It is labelled as such, because calling it
        # `interest:c0` would let a diagnostic claim the reader has an
        # interest the profiler explicitly declined to infer.
        cluster_prefix = (
            PROVENANCE_GLOBAL
            if profile.strategy is ProfileStrategy.FALLBACK_CENTROID
            else PROVENANCE_INTEREST
        )
        weighted: list[tuple[float, str, npt.NDArray[np.float64]]] = [
            (
                cluster.weight,
                f"{cluster_prefix}:{cluster.interest_id}",
                query_vector_for(cluster, embeddings, config=profile.config),
            )
            for cluster in profile.clusters
        ]
        weighted += [
            (shelf.weight, f"{PROVENANCE_SHELF}:{shelf.shelf_id}", shelf.query_vector)
            for shelf in profile.shelves
        ]
        # Weight desc, then provenance asc: two interests of equal weight
        # must not swap places between runs, or the persisted batch stops
        # being reproducible.
        weighted.sort(key=lambda item: (-item[0], item[1]))
        return [
            (provenance, vector)
            for _, provenance, vector in weighted[: self._config.max_semantic_queries]
        ]

    @staticmethod
    def _profile_diagnostics(request: GeneratorRequest) -> dict[str, object]:
        profile = request.semantic_profile
        if profile is None:
            return {"profile": "absent"}
        return {
            "strategy": str(profile.strategy),
            "interests": len(profile.clusters),
            "shelf_profiles": len(profile.shelves),
        }
