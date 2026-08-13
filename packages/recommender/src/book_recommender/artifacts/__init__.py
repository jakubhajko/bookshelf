"""Artifact substrate: manifests, item mapping, numeric payloads, family
loaders and the builder-side writer (ADR-0014, rec-spec §8).

Layering, innermost first:

``numeric``
    NumPy serialization primitives — no pickle, deterministic ``.npz``.
``manifest`` / ``mapping``
    What an artifact claims about itself, and the ``work_id``-keyed item
    mapping every family shares.
``local_storage``
    Path resolution inside a storage root. An S3-backed implementation of
    the same shape is a later addition (spec §10.13), deferred rather than
    built speculatively — the same precedent as cover storage.
``loader`` / ``writer``
    The shared read and write halves of an artifact directory.
``popularity`` / ``source_similarity`` / ``item_metadata``
    One module per family, each owning its own payload format.

ALS, item-item CF and content embeddings add modules at this last level in
R4/R5 without touching the layers beneath.
"""

from __future__ import annotations

from book_recommender.artifacts.als import (
    AlsArtifact,
    load_als_artifact,
    write_item_factors,
)
from book_recommender.artifacts.content import (
    ContentEmbeddings,
    load_content_artifact,
    write_embeddings,
)
from book_recommender.artifacts.item_cf import (
    ItemCfNeighbors,
    ItemNeighbor,
    load_item_cf_artifact,
    write_item_cf_neighbors,
)
from book_recommender.artifacts.item_metadata import (
    ItemMetadataRow,
    ItemMetadataTable,
    load_item_metadata_artifact,
    write_item_metadata,
)
from book_recommender.artifacts.loader import (
    ArtifactBundle,
    load_artifact_bundle,
    verify_artifact_files,
)
from book_recommender.artifacts.local_storage import (
    MANIFEST_FILENAME,
    LocalArtifactStorage,
    UnsafeArtifactKeyError,
)
from book_recommender.artifacts.manifest import (
    MANIFEST_SCHEMA_VERSION,
    ArtifactFile,
    ArtifactManifest,
)
from book_recommender.artifacts.mapping import (
    MAPPING_FILENAME,
    CatalogSnapshot,
    ItemMapping,
    MappingResolution,
    MappingStatus,
    resolve_item_mapping,
)
from book_recommender.artifacts.popularity import (
    PopularityArtifact,
    load_popularity_artifact,
    write_popularity_scores,
)
from book_recommender.artifacts.source_similarity import (
    SourceNeighbor,
    SourceSimilarityGraph,
    build_csr,
    load_source_similarity_artifact,
    write_source_similarity_graph,
)
from book_recommender.artifacts.writer import WrittenArtifact, write_artifact

__all__ = [
    "AlsArtifact",
    "ArtifactBundle",
    "ArtifactFile",
    "ArtifactManifest",
    "ContentEmbeddings",
    "CatalogSnapshot",
    "ItemCfNeighbors",
    "ItemMapping",
    "ItemMetadataRow",
    "ItemMetadataTable",
    "ItemNeighbor",
    "LocalArtifactStorage",
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA_VERSION",
    "MAPPING_FILENAME",
    "MappingResolution",
    "MappingStatus",
    "PopularityArtifact",
    "SourceNeighbor",
    "SourceSimilarityGraph",
    "UnsafeArtifactKeyError",
    "WrittenArtifact",
    "build_csr",
    "load_als_artifact",
    "load_artifact_bundle",
    "load_content_artifact",
    "load_item_cf_artifact",
    "load_item_metadata_artifact",
    "load_popularity_artifact",
    "load_source_similarity_artifact",
    "resolve_item_mapping",
    "verify_artifact_files",
    "write_artifact",
    "write_embeddings",
    "write_item_cf_neighbors",
    "write_item_factors",
    "write_item_metadata",
    "write_popularity_scores",
    "write_source_similarity_graph",
]
