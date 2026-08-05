"""Artifact manifest schema and local-disk storage (spec §10.13).

An S3-backed implementation of the same storage shape is a later addition
(spec §10.13: "local and S3 storage abstractions") — deferred, not built
speculatively, matching the same precedent as cover storage (spec §7.3,
``apps/api``'s ``shared/storage/``)."""

from __future__ import annotations

from book_recommender.artifacts.local_storage import LocalArtifactStorage, UnsafeArtifactKeyError
from book_recommender.artifacts.manifest import ArtifactItemMapping, ArtifactManifest

__all__ = [
    "ArtifactItemMapping",
    "ArtifactManifest",
    "LocalArtifactStorage",
    "UnsafeArtifactKeyError",
]
