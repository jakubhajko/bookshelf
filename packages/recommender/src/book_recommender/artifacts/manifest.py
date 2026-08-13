"""Artifact manifest schema (rec-spec §8, ADR-0014).

An artifact is model-produced data plus this manifest describing it. The
manifest alone is enough to decide whether an artifact is *worth* loading —
which model produced it, against which catalog, with which preprocessing —
and its checksums are enough to decide whether the files beside it are
intact.

Schema version 2 (recommender Phase R3) moved the item mapping *out* of the
manifest and into a compact ``mapping.npz`` beside it. Version 1 inlined one
Pydantic model per catalog item, which measured at 8.9 MB of JSON, 0.22 s of
parse time and ~55 MB of resident objects for the single popularity artifact
— per family, per worker process. Five families would have made startup cost
roughly a second and a quarter of a gigabyte before serving a request, and
the same object graph was being written into the ``model_versions.manifest``
JSONB column as an 8.9 MB row. See :mod:`book_recommender.artifacts.mapping`.

A version 1 manifest therefore fails validation here, which surfaces as the
ordinary "artifact unreadable, degrade to the fallback" path. Artifacts are
regeneratable by design (``make build-recommender-artifacts``), so this is a
rebuild prompt, not data loss.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MANIFEST_SCHEMA_VERSION = 2

#: Serializable build configuration (rec-spec §26: "Configuration must be
#: serializable into build metadata so an artifact can be reproduced"). Held
#: as a JSON-ish mapping rather than a per-family typed model so the manifest
#: schema does not have to change every time a family gains a knob.
ConfigValue = str | int | float | bool | None | list[str] | list[int] | list[float]


def plain_filename(value: str) -> str:
    """An artifact file is a plain filename inside its own directory.

    ``LocalArtifactStorage.resolve`` already refuses paths that escape the
    storage *root*, but a name like ``../popularity/latest/scores.npz`` stays
    inside the root while reaching into a sibling artifact — so the root check
    alone would not catch it. Nothing legitimate needs a separator here, so
    the manifest format forbids one.
    """
    if not value or "/" in value or "\\" in value or value in {".", ".."}:
        raise ValueError(f"artifact filename must be a plain filename, got {value!r}")
    return value


class ArtifactFile(BaseModel):
    """One data file belonging to an artifact, with the checksum that proves
    it is the file the build wrote (rec-spec §8: "file list/checksums if the
    current artifact contract supports it")."""

    model_config = ConfigDict(frozen=True)

    name: str
    sha256: str
    size_bytes: int

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return plain_filename(value)


class ArtifactManifest(BaseModel):
    """rec-spec §8's field list. The item mapping it references lives in
    ``mapping_file``; ``files`` covers the family's own numeric payloads."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[2] = 2
    model_name: str
    model_version: str
    catalog_version: str
    trained_at: datetime
    item_count: int
    #: Version of the deterministic transform that turned catalog rows into
    #: this artifact's payload. Bump it when the *meaning* of the numbers
    #: changes, independently of the model version.
    preprocessing_version: str
    #: Version of the interaction-data transform, for families trained on
    #: ``interactions.parquet`` (rec-spec §7.2). ``None`` for families built
    #: from the catalog alone.
    training_transform_version: str | None = None
    config: dict[str, ConfigValue] = Field(default_factory=dict)
    mapping_file: str = "mapping.npz"
    files: tuple[ArtifactFile, ...] = ()

    @field_validator("mapping_file")
    @classmethod
    def _validate_mapping_file(cls, value: str) -> str:
        return plain_filename(value)

    def file(self, name: str) -> ArtifactFile | None:
        return next((entry for entry in self.files if entry.name == name), None)
