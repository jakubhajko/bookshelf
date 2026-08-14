"""Candidate union, ranking and reranking (rec-spec §17-§19, ADR-0017).

The three stages between R6's generators and the authoritative ordered
batch:

1. :mod:`~book_recommender.pipeline.fusion` — weighted RRF over five ranked
   lists, deduplicating by ``book_id`` without losing provenance.
2. :mod:`~book_recommender.pipeline.ranking` — a deterministic,
   interpretable V1 ranker behind a protocol a learned model can replace.
3. :mod:`~book_recommender.pipeline.reranking` — greedy surface-specific
   diversity, applied *inside* the package so the order that leaves it is
   final (ADR-0006, ADR-0007).

All three are pure: artifacts and an immutable request in, an ordered list
out. Wiring them into an engine is Phase R8.
"""

from __future__ import annotations

from book_recommender.pipeline.fusion import (
    FusedCandidate,
    SourceContribution,
    fuse,
    rrf_contribution,
)
from book_recommender.pipeline.ranking import (
    DeterministicRanker,
    RankedCandidate,
    Ranker,
    RankingContext,
)
from book_recommender.pipeline.reranking import (
    DiversityReranker,
    RerankContext,
    RerankedCandidate,
    Reranker,
    series_of,
)

__all__ = [
    "DeterministicRanker",
    "DiversityReranker",
    "FusedCandidate",
    "RankedCandidate",
    "Ranker",
    "RankingContext",
    "RerankContext",
    "RerankedCandidate",
    "Reranker",
    "SourceContribution",
    "fuse",
    "rrf_contribution",
    "series_of",
]
