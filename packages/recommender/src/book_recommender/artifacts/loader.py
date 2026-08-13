"""Generic artifact loading: manifest → checksums → mapping → resolution
(ADR-0014, rec-spec §8).

Every family loader starts the same way, and before recommender Phase R3
that shared prologue did not exist — the popularity artifact was parsed
inline in ``apps/api``'s ``modules/recommendations/wiring.py``. ADR-0014:
"Artifact loading moves into the recommender package's artifact layer.
``wiring.py`` selects and constructs; it does not parse model file formats."
This module is that shared prologue, and :func:`load_artifact_bundle` is the
single place where "is this artifact safe to serve?" is decided.

The answer is one of three, and the distinction matters because the
responses differ:

- **raise** :class:`~book_recommender.exceptions.IncompatibleArtifactError`
  — the files are missing, corrupt, mutually inconsistent, or written by an
  older schema. A bug or an incomplete build.
- **return a rejected bundle** — the files are fine but describe a catalog
  this process is not serving. An operational state; degrade to the
  fallback.
- **return a bundle** — servable, possibly with items dropped.

Callers degrade rather than crash in all three cases (ADR-0014: "Missing or
corrupt artifacts never fail application startup"), but only the loader can
tell them apart, and the diagnostics differ.
"""

from __future__ import annotations

from dataclasses import dataclass

from book_recommender.artifacts.local_storage import LocalArtifactStorage
from book_recommender.artifacts.manifest import ArtifactManifest
from book_recommender.artifacts.mapping import (
    DEFAULT_MAX_UNRESOLVED_FRACTION,
    CatalogSnapshot,
    ItemMapping,
    MappingResolution,
    MappingStatus,
    resolve_item_mapping,
)
from book_recommender.artifacts.numeric import sha256_file
from book_recommender.exceptions import IncompatibleArtifactError


@dataclass(frozen=True)
class ArtifactBundle:
    """A loaded, validated artifact directory, minus the family-specific
    payload the caller goes on to read."""

    artifact_dir: str
    manifest: ArtifactManifest
    mapping: ItemMapping
    resolution: MappingResolution

    @property
    def is_servable(self) -> bool:
        return self.resolution.is_servable

    @property
    def status(self) -> MappingStatus:
        return self.resolution.status

    def diagnostics(self) -> dict[str, str | int | float]:
        """Structured, log-safe summary. No book titles, no user data, no
        raw vectors — CLAUDE.md's rule that recommendation diagnostics must
        not become an accidental sensitive-data dump applies to startup logs
        as much as to API responses."""
        return {
            "artifact_dir": self.artifact_dir,
            "model_name": self.manifest.model_name,
            "model_version": self.manifest.model_version,
            "catalog_version": self.manifest.catalog_version,
            "status": str(self.resolution.status),
            "item_count": self.resolution.item_count,
            "resolved_count": self.resolution.resolved_count,
            "unresolved_count": self.resolution.unresolved_count,
            "reassigned_count": self.resolution.reassigned_count,
            "reason": self.resolution.reason or "",
        }


def load_artifact_bundle(
    storage: LocalArtifactStorage,
    artifact_dir: str,
    *,
    catalog: CatalogSnapshot,
    expected_model_name: str | None = None,
    verify_checksums: bool = True,
    max_unresolved_fraction: float = DEFAULT_MAX_UNRESOLVED_FRACTION,
) -> ArtifactBundle:
    """Load and validate the parts of an artifact every family shares.

    Raises :class:`IncompatibleArtifactError` for a broken artifact; returns
    a bundle whose ``is_servable`` is ``False`` for an intact one that does
    not match the live catalog.
    """
    manifest = storage.load_manifest(artifact_dir)

    if expected_model_name is not None and manifest.model_name != expected_model_name:
        raise IncompatibleArtifactError(
            f"artifact at {artifact_dir!r} is {manifest.model_name!r}, "
            f"expected {expected_model_name!r}"
        )

    if verify_checksums:
        verify_artifact_files(storage, artifact_dir, manifest)

    mapping_path = storage.resolve(artifact_dir, manifest.mapping_file)
    mapping = ItemMapping.load(mapping_path, expected_item_count=manifest.item_count)
    resolution = resolve_item_mapping(
        mapping, catalog, max_unresolved_fraction=max_unresolved_fraction
    )

    return ArtifactBundle(
        artifact_dir=artifact_dir,
        manifest=manifest,
        mapping=mapping,
        resolution=resolution,
    )


def verify_artifact_files(
    storage: LocalArtifactStorage, artifact_dir: str, manifest: ArtifactManifest
) -> None:
    """Check every declared file exists and still hashes to what the build
    recorded.

    Cheap enough to do unconditionally at startup (a few MB of SHA-256) and
    it converts the one failure mode a manifest cannot otherwise catch — a
    half-written or partially-copied artifact directory — from "serves
    plausible-looking wrong books" into a load error.
    """
    for entry in manifest.files:
        path = storage.resolve(artifact_dir, entry.name)
        if not path.is_file():
            raise IncompatibleArtifactError(
                f"artifact {artifact_dir!r} declares {entry.name!r} but the file is missing"
            )
        actual_size = path.stat().st_size
        if actual_size != entry.size_bytes:
            raise IncompatibleArtifactError(
                f"artifact file {entry.name!r} is {actual_size} bytes, "
                f"manifest declares {entry.size_bytes}"
            )
        actual_sha = sha256_file(path)
        if actual_sha != entry.sha256:
            raise IncompatibleArtifactError(
                f"artifact file {entry.name!r} checksum mismatch: "
                f"{actual_sha[:12]}… != {entry.sha256[:12]}…"
            )
