"""Candidate generators (rec-spec §16, Phase R6).

The five V1 candidate families behind one structural protocol. Each takes
its artifact at construction and an immutable :class:`GeneratorRequest` per
call; none of them can reach PostgreSQL, a clock or the filesystem, which is
what makes their output reproducible for a fixed request.

Fusing the five lists into one ordered batch is Phase R7's job (weighted
RRF, ADR-0017). Nothing here ranks across generators, and nothing here
decides how much a generator counts on a given surface — that is surface
configuration, deliberately kept outside the generators (rec-spec §17).
"""

from __future__ import annotations

from book_recommender.generators.als import AlsCandidateGenerator
from book_recommender.generators.base import (
    PROVENANCE_GLOBAL,
    PROVENANCE_INTEREST,
    PROVENANCE_SHELF,
    PROVENANCE_SOURCE_BOOK,
    PROVENANCE_TARGET_SHELF,
    Candidate,
    CandidateGenerator,
    GeneratorId,
    GeneratorRequest,
    GeneratorResult,
    GeneratorStatus,
    interleave,
    rank_all,
)
from book_recommender.generators.item_cf import ItemItemCFCandidateGenerator
from book_recommender.generators.popularity import PopularityCandidateGenerator
from book_recommender.generators.seeds import Seed, collect_seeds
from book_recommender.generators.semantic import SemanticCandidateGenerator
from book_recommender.generators.source_similarity import SourceSimilarityCandidateGenerator

__all__ = [
    "PROVENANCE_GLOBAL",
    "PROVENANCE_INTEREST",
    "PROVENANCE_SHELF",
    "PROVENANCE_SOURCE_BOOK",
    "PROVENANCE_TARGET_SHELF",
    "AlsCandidateGenerator",
    "Candidate",
    "CandidateGenerator",
    "GeneratorId",
    "GeneratorRequest",
    "GeneratorResult",
    "GeneratorStatus",
    "ItemItemCFCandidateGenerator",
    "PopularityCandidateGenerator",
    "Seed",
    "SemanticCandidateGenerator",
    "SourceSimilarityCandidateGenerator",
    "collect_seeds",
    "interleave",
    "rank_all",
]
