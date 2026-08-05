"""Artifact manifest schema (spec §10.13, §7.5).

An artifact is model-produced data (e.g. a popularity ranking, later a real
embedding/ranking model) plus this manifest describing it. The manifest
alone is enough to decide whether an artifact is safe to load — the actual
model/config files it references are opaque to this package.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ArtifactItemMapping(BaseModel):
    """Spec §7.5: "Every model artifact explicitly stores: book_id, work_id,
    model_item_index" — the three-way translation between PostgreSQL's
    internal id, the dataset's stable id, and whatever index the model
    itself uses internally (e.g. a row in an embedding matrix)."""

    model_config = ConfigDict(frozen=True)

    book_id: int
    work_id: str
    model_item_index: int


class ArtifactManifest(BaseModel):
    """Spec §10.13's exact field list, minus ``model/config files`` (that's
    ``files`` here — the artifact's own data, opaque to this package)."""

    model_config = ConfigDict(frozen=True)

    model_name: str
    model_version: str
    catalog_version: str
    trained_at: datetime
    item_count: int
    item_mapping: tuple[ArtifactItemMapping, ...]
    files: tuple[str, ...]
