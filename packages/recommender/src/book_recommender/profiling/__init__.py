"""Semantic user profiling (rec-spec §12, §13; ADR-0016).

Pure logic over vectors the content artifact supplies: no ORM, no I/O, no
clock, and — importantly — no scikit-learn, because this runs at serving
time and the training stack must not reach the request path (ADR-0021).

The inspection command in ``apps/api`` calls exactly these functions, which
is rec-spec §13's requirement that there be no second debug-only
implementation of the clustering.
"""

from __future__ import annotations

from book_recommender.profiling.clustering import (
    average_linkage_clusters,
    cosine_similarity_matrix,
    medoid_index,
    weighted_centroid,
)
from book_recommender.profiling.interests import (
    EmbeddingLookup,
    EvidenceItem,
    InterestCluster,
    InterestProfile,
    ProfileStrategy,
    ShelfProfile,
    build_interest_profile,
    build_shelf_profiles,
    query_vector_for,
)
from book_recommender.profiling.summaries import (
    BookDescriptor,
    InterestClusterSummary,
    ProfileSummary,
    ShelfProfileSummary,
    build_label,
    summarize_cluster,
    summarize_profile,
    summarize_shelf,
)

__all__ = [
    "BookDescriptor",
    "EmbeddingLookup",
    "EvidenceItem",
    "InterestCluster",
    "InterestClusterSummary",
    "InterestProfile",
    "ProfileStrategy",
    "ProfileSummary",
    "ShelfProfile",
    "ShelfProfileSummary",
    "average_linkage_clusters",
    "build_interest_profile",
    "build_label",
    "build_shelf_profiles",
    "cosine_similarity_matrix",
    "medoid_index",
    "query_vector_for",
    "summarize_cluster",
    "summarize_profile",
    "summarize_shelf",
    "weighted_centroid",
]
