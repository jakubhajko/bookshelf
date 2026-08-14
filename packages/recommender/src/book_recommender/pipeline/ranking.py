"""The deterministic V1 ranker (rec-spec §18, ADR-0017).

There is no learned ranker here, and that is a gate rather than a
preference. A learned engagement model needs click/open labels with
attribution; ADR-0015 is the decision to start *collecting* them, and R1
began doing so. Training one now would mean training on impressions as
labels — treating "we showed it" as "they wanted it" — which is the exact
mistake ADR-0015 rejects.

So V1 scores a weighted sum of interpretable features, every one of which a
person can read off the diagnostics and argue with. The interface is clean
enough that swapping in a learned model later touches nothing else.

The features, and why each is here (rec-spec §18's own list):

===========================  =================================================
fusion                       ADR-0017's consensus score
agreement                    how many independent generators found it
semantic_relevance           cosine to the surface's query profile
collaborative_relevance      best normalized rank among the CF generators
popularity_prior             quality prior — deliberately *not* dominant
evidence_affinity            similarity to the reader's strongest positives
surface_coherence            same genre as the shelf, same author as source
negative_evidence            subtracted: similarity to what they rejected
===========================  =================================================

rec-spec §18's hard rule — "Do not use raw popularity as the dominant
personalization score" — is a property of the weights in
:class:`~book_recommender.config.RankingWeights`, and it is asserted by a
test rather than left to inspection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import numpy.typing as npt

from book_recommender.artifacts.content import ContentEmbeddings
from book_recommender.artifacts.item_metadata import ItemMetadataTable
from book_recommender.config import SurfaceConfig
from book_recommender.generators import GeneratorId
from book_recommender.pipeline.fusion import FusedCandidate

#: Generators whose rank expresses collaborative evidence.
_COLLABORATIVE = (GeneratorId.ALS.value, GeneratorId.ITEM_CF.value)


@dataclass(frozen=True)
class RankingContext:
    """Everything the ranker may read, resolved before ranking starts.

    Artifact-backed and immutable: no database, no clock (rec-spec §8). All
    artifact fields are optional because rec-spec §27 requires the pipeline
    to degrade — a missing content artifact costs the semantic features and
    leaves the rest working, rather than failing the request.
    """

    surface: SurfaceConfig
    embeddings: ContentEmbeddings | None = None
    metadata: ItemMetadataTable | None = None
    #: ``book_id -> popularity score``, on the artifact's own scale. The
    #: ranker normalizes within the candidate set, so the scale is free.
    popularity: Mapping[int, float] | None = None
    #: The surface's query profile: interest centroids on Home, the target
    #: shelf profile on Shelf, the source book's vector on Similar.
    query_vectors: tuple[npt.NDArray[np.float64], ...] = ()
    #: The reader's strongest positive evidence, for affinity.
    evidence_book_ids: tuple[int, ...] = ()
    #: Not Interested plus books rated 1-5 (rec-spec §7.1's negative rows).
    negative_book_ids: tuple[int, ...] = ()
    #: Genres/authors this surface considers coherent — the target shelf's
    #: genres, or the source book's.
    coherent_genres: frozenset[str] = frozenset()
    coherent_authors: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RankedCandidate:
    """A scored candidate with its breakdown kept inspectable.

    rec-spec §18: "Keep the scoring breakdown inspectable in diagnostics for
    development/evaluation." ``features`` holds the *normalized* feature
    values before weighting, so a diagnostic can show both what the ranker
    saw and what it did with it.
    """

    book_id: int
    score: float
    fused: FusedCandidate
    features: Mapping[str, float] = field(default_factory=dict)

    @property
    def agreement(self) -> int:
        return self.fused.agreement


class Ranker(Protocol):
    """The seam a learned model replaces later without touching the pipeline."""

    def rank(
        self, candidates: Sequence[FusedCandidate], *, context: RankingContext
    ) -> tuple[RankedCandidate, ...]: ...


class DeterministicRanker:
    """Weighted sum of normalized interpretable features."""

    def rank(
        self, candidates: Sequence[FusedCandidate], *, context: RankingContext
    ) -> tuple[RankedCandidate, ...]:
        if not candidates:
            return ()

        weights = context.surface.ranking
        book_ids = [candidate.book_id for candidate in candidates]

        semantic = self._similarity_to(book_ids, context.query_vectors, context)
        affinity = self._similarity_to_books(book_ids, context.evidence_book_ids, context)
        negative = self._similarity_to_books(book_ids, context.negative_book_ids, context)
        popularity = self._popularity(book_ids, context)

        # Fusion scores are tiny (weight / (60 + rank)) and their absolute
        # size means nothing — only their order within this batch does. So
        # they are normalized against the batch maximum, which puts every
        # feature on the same [0, 1] footing and makes the weights in
        # RankingWeights directly comparable to one another.
        max_fusion = max(candidate.fusion_score for candidate in candidates) or 1.0
        enabled = max(len(context.surface.enabled_generators), 1)

        ranked: list[RankedCandidate] = []
        for index, candidate in enumerate(candidates):
            features = {
                "fusion": candidate.fusion_score / max_fusion,
                "agreement": min(candidate.agreement / enabled, 1.0),
                "semantic_relevance": semantic[index],
                "collaborative_relevance": self._collaborative(candidate, context),
                "popularity_prior": popularity[index],
                "evidence_affinity": affinity[index],
                "surface_coherence": self._coherence(candidate.book_id, context),
                "negative_evidence": negative[index],
            }
            score = (
                weights.fusion * features["fusion"]
                + weights.agreement * features["agreement"]
                + weights.semantic_relevance * features["semantic_relevance"]
                + weights.collaborative_relevance * features["collaborative_relevance"]
                + weights.popularity_prior * features["popularity_prior"]
                + weights.evidence_affinity * features["evidence_affinity"]
                + weights.surface_coherence * features["surface_coherence"]
                - weights.negative_evidence * features["negative_evidence"]
            )
            ranked.append(
                RankedCandidate(
                    book_id=candidate.book_id,
                    score=score,
                    fused=candidate,
                    features=features,
                )
            )

        # Score desc, then agreement desc, then book_id asc — deterministic
        # for a fixed request, profile, artifact set and configuration, which
        # ADR-0017 requires so the persisted batch stays reproducible.
        ranked.sort(key=lambda item: (-item.score, -item.agreement, item.book_id))
        return tuple(ranked)

    # --- features ---------------------------------------------------------

    @staticmethod
    def _similarity_to(
        book_ids: Sequence[int],
        queries: Sequence[npt.NDArray[np.float64]],
        context: RankingContext,
    ) -> list[float]:
        """Best cosine from each candidate to any of the surface's queries.

        *Best*, not mean: a book strongly matching one of a reader's four
        interests is a good recommendation. Averaging would punish it for
        being unrelated to the other three, which is how multi-interest
        profiling gets quietly undone at the ranking stage.
        """
        embeddings = context.embeddings
        if embeddings is None or not queries:
            return [0.0] * len(book_ids)

        vectors, resolved = embeddings.vectors_for(list(book_ids))
        if not resolved:
            return [0.0] * len(book_ids)

        matrix = np.asarray(vectors, dtype=np.float64)
        query_matrix = np.vstack([np.asarray(query, dtype=np.float64) for query in queries])
        # One matmul for every candidate against every query (rec-spec §24).
        similarity = matrix @ query_matrix.T
        best = similarity.max(axis=1)

        by_book = {book_id: float(best[row]) for row, book_id in enumerate(resolved)}
        # Vectors are unit-norm, so a cosine is in [-1, 1]; a negative one
        # means "points away from this interest", which as a *relevance*
        # feature is simply zero rather than a reward for being opposite.
        return [max(by_book.get(book_id, 0.0), 0.0) for book_id in book_ids]

    @classmethod
    def _similarity_to_books(
        cls,
        book_ids: Sequence[int],
        reference_book_ids: Sequence[int],
        context: RankingContext,
    ) -> list[float]:
        embeddings = context.embeddings
        if embeddings is None or not reference_book_ids:
            return [0.0] * len(book_ids)
        vectors, resolved = embeddings.vectors_for(list(reference_book_ids))
        if not resolved:
            return [0.0] * len(book_ids)
        queries = [np.asarray(row, dtype=np.float64) for row in vectors]
        return cls._similarity_to(book_ids, queries, context)

    @staticmethod
    def _collaborative(candidate: FusedCandidate, context: RankingContext) -> float:
        """Best normalized rank across the CF generators.

        Rank rather than score, for the same reason fusion uses rank: an ALS
        dot product and an item-CF similarity are not comparable, but "third
        out of a hundred and fiftieth" means the same thing in both.
        """
        best = 0.0
        for generator in _COLLABORATIVE:
            rank = candidate.rank_in(generator)
            if rank is None:
                continue
            quota = context.surface.quota_for(generator)
            depth = quota.count if quota is not None and quota.count > 0 else rank
            best = max(best, max(0.0, 1.0 - (rank - 1) / max(depth, 1)))
        return best

    @staticmethod
    def _popularity(book_ids: Sequence[int], context: RankingContext) -> list[float]:
        """Min-max normalized *within the candidate set*.

        Normalizing against the whole catalog would make this feature nearly
        constant — every candidate that survived retrieval is already far
        above the catalog median — and a constant feature cannot break a tie,
        which is the only job rec-spec §18 leaves it.
        """
        table = context.popularity
        if not table:
            return [0.0] * len(book_ids)
        values = [table.get(book_id, 0.0) for book_id in book_ids]
        low, high = min(values), max(values)
        if high <= low:
            return [0.0] * len(book_ids)
        return [(value - low) / (high - low) for value in values]

    @staticmethod
    def _coherence(book_id: int, context: RankingContext) -> float:
        """Agreement with what this surface considers coherent.

        Genre and author are *ranking features* here, which is exactly where
        rec-spec §14 says they belong — it forbids mixing them into the
        source-similarity generator, where they would masquerade as
        Goodreads edges, but explicitly allows them as ranking signals.
        """
        table = context.metadata
        if table is None or (not context.coherent_genres and not context.coherent_authors):
            return 0.0
        row = table.get(book_id)
        if row is None:
            return 0.0
        score = 0.0
        if row.genre and row.genre in context.coherent_genres:
            score += 0.5
        if row.author and row.author in context.coherent_authors:
            score += 0.5
        return score
