"""Artifact manifest schema + local storage round trip (spec §10.13)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from book_recommender.artifacts import ArtifactItemMapping, ArtifactManifest, LocalArtifactStorage
from book_recommender.artifacts.local_storage import UnsafeArtifactKeyError
from book_recommender.exceptions import IncompatibleArtifactError


def _manifest() -> ArtifactManifest:
    return ArtifactManifest(
        model_name="popularity",
        model_version="2026-08-05T00:00:00",
        catalog_version="92524:2026-08-05T00:00:00",
        trained_at=datetime.now(UTC),
        item_count=2,
        item_mapping=(
            ArtifactItemMapping(book_id=1, work_id="w1", model_item_index=0),
            ArtifactItemMapping(book_id=2, work_id="w2", model_item_index=1),
        ),
        files=("scores.json",),
    )


def test_manifest_round_trips_through_local_storage(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    manifest = _manifest()
    storage.save_manifest("popularity/v1", manifest)
    loaded = storage.load_manifest("popularity/v1")
    assert loaded == manifest


def test_missing_manifest_raises_incompatible_artifact_error(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    with pytest.raises(IncompatibleArtifactError):
        storage.load_manifest("does/not/exist")


def test_corrupt_manifest_raises_incompatible_artifact_error(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    path = storage.resolve("popularity/v1", "manifest.json")
    path.parent.mkdir(parents=True)
    path.write_text("not valid json{{{")
    with pytest.raises(IncompatibleArtifactError):
        storage.load_manifest("popularity/v1")


def test_artifact_path_cannot_escape_storage_root(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    with pytest.raises(UnsafeArtifactKeyError):
        storage.resolve("../../etc", "passwd")
