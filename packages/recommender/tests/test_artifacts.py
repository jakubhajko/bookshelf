"""Artifact manifest, storage and the shared write/load round trip
(rec-spec §8, ADR-0014)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from book_recommender.artifacts import (
    ArtifactFile,
    ArtifactManifest,
    CatalogSnapshot,
    LocalArtifactStorage,
    MappingStatus,
    load_artifact_bundle,
    write_artifact,
)
from book_recommender.artifacts.local_storage import UnsafeArtifactKeyError
from book_recommender.artifacts.numeric import save_arrays
from book_recommender.config import ArtifactFamily
from book_recommender.exceptions import IncompatibleArtifactError

FAMILY = ArtifactFamily(name="testmodel", directory="testmodel/latest", preprocessing_version="p1")

ITEMS = [(1, "w-a"), (2, "w-b"), (3, "w-c")]
CATALOG = CatalogSnapshot.from_rows("3:2026-08-13T00:00:00", ITEMS)


def _manifest() -> ArtifactManifest:
    return ArtifactManifest(
        model_name="popularity",
        model_version="20260805T000000Z",
        catalog_version="92524:2026-08-05T00:00:00",
        trained_at=datetime.now(UTC),
        item_count=2,
        preprocessing_version="popularity-bayesian-shrink-v1",
        files=(ArtifactFile(name="scores.npz", sha256="00" * 32, size_bytes=17),),
    )


def _write(storage: LocalArtifactStorage, **overrides: object) -> None:
    payload = {"values": np.array([1, 2, 3], dtype=np.int64)}
    kwargs: dict[str, object] = {
        "model_version": "20260813T120000Z",
        "catalog_version": CATALOG.catalog_version,
        "items": ITEMS,
        "payloads": {"payload.npz": lambda path: save_arrays(path, payload)},
    }
    kwargs.update(overrides)
    write_artifact(storage, FAMILY, **kwargs)  # type: ignore[arg-type]


# --- Manifest schema --------------------------------------------------------


def test_manifest_round_trips_through_local_storage(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    manifest = _manifest()
    storage.save_manifest("popularity/v1", manifest)
    assert storage.load_manifest("popularity/v1") == manifest


def test_missing_manifest_raises_incompatible_artifact_error(tmp_path: Path) -> None:
    with pytest.raises(IncompatibleArtifactError):
        LocalArtifactStorage(tmp_path).load_manifest("does/not/exist")


def test_corrupt_manifest_raises_incompatible_artifact_error(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    path = storage.resolve("popularity/v1", "manifest.json")
    path.parent.mkdir(parents=True)
    path.write_text("not valid json{{{")
    with pytest.raises(IncompatibleArtifactError):
        storage.load_manifest("popularity/v1")


def test_schema_version_1_manifest_is_rejected(tmp_path: Path) -> None:
    """The pre-R3 format inlined one object per catalog item. It must fail
    as an unreadable artifact — which degrades to the fallback and prompts a
    rebuild — rather than being half-understood."""
    storage = LocalArtifactStorage(tmp_path)
    path = storage.resolve("popularity/latest", "manifest.json")
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "model_name": "popularity",
                "model_version": "20260805T000000Z",
                "catalog_version": "92524:2026-08-05T00:00:00",
                "trained_at": "2026-08-05T00:00:00Z",
                "item_count": 1,
                "item_mapping": [{"book_id": 1, "work_id": "w-a", "model_item_index": 0}],
                "files": ["scores.json"],
            }
        )
    )
    with pytest.raises(IncompatibleArtifactError):
        storage.load_manifest("popularity/latest")


# --- Path safety ------------------------------------------------------------


def test_artifact_path_cannot_escape_storage_root(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    with pytest.raises(UnsafeArtifactKeyError):
        storage.resolve("../../etc", "passwd")


def test_artifact_filename_cannot_escape_storage_root(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    with pytest.raises(UnsafeArtifactKeyError):
        storage.resolve("popularity/latest", "../../../../etc/passwd")


@pytest.mark.parametrize("name", ["../scores.npz", "sub/scores.npz", "..", "..\\scores.npz", ""])
def test_a_manifest_cannot_declare_a_file_outside_its_own_directory(name: str) -> None:
    """``LocalArtifactStorage`` only refuses escapes from the storage *root*,
    so ``../popularity/latest/scores.npz`` would stay inside it while reading
    a sibling artifact's files. The manifest format forbids separators
    outright instead."""
    with pytest.raises(ValidationError):
        ArtifactFile(name=name, sha256="00" * 32, size_bytes=1)


def test_a_hostile_manifest_on_disk_is_rejected_at_load(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    path = storage.resolve(FAMILY.directory, "manifest.json")
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "model_name": FAMILY.name,
                "model_version": "v",
                "catalog_version": CATALOG.catalog_version,
                "trained_at": "2026-08-13T00:00:00Z",
                "item_count": 0,
                "preprocessing_version": "p1",
                "mapping_file": "../../../../etc/passwd",
                "files": [],
            }
        )
    )
    with pytest.raises(IncompatibleArtifactError):
        storage.load_manifest(FAMILY.directory)


# --- Write/load round trip --------------------------------------------------


def test_written_artifact_loads_back(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    _write(storage)

    bundle = load_artifact_bundle(storage, FAMILY.directory, catalog=CATALOG)

    assert bundle.status is MappingStatus.OK
    assert bundle.manifest.preprocessing_version == "p1"
    assert bundle.manifest.schema_version == 2
    assert bundle.resolution.book_ids.tolist() == [1, 2, 3]


def test_manifest_records_checksums_of_the_files_actually_written(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    _write(storage)

    manifest = storage.load_manifest(FAMILY.directory)

    assert {entry.name for entry in manifest.files} == {"mapping.npz", "payload.npz"}
    for entry in manifest.files:
        path = storage.resolve(FAMILY.directory, entry.name)
        assert entry.size_bytes == path.stat().st_size
        assert len(entry.sha256) == 64


def test_a_tampered_payload_fails_verification(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    _write(storage)
    # Same-length tamper, so the cheap size check cannot be what catches it.
    payload_path = storage.resolve(FAMILY.directory, "payload.npz")
    raw = bytearray(payload_path.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    payload_path.write_bytes(bytes(raw))

    with pytest.raises(IncompatibleArtifactError, match="checksum mismatch"):
        load_artifact_bundle(storage, FAMILY.directory, catalog=CATALOG)


def test_a_deleted_payload_fails_verification(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    _write(storage)
    storage.resolve(FAMILY.directory, "payload.npz").unlink()

    with pytest.raises(IncompatibleArtifactError, match="the file is missing"):
        load_artifact_bundle(storage, FAMILY.directory, catalog=CATALOG)


def test_loading_the_wrong_family_is_rejected(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    _write(storage)

    with pytest.raises(IncompatibleArtifactError, match="expected 'als'"):
        load_artifact_bundle(storage, FAMILY.directory, catalog=CATALOG, expected_model_name="als")


def test_incompatible_catalog_is_reported_rather_than_raised(tmp_path: Path) -> None:
    """An intact artifact describing a catalog this process is not serving is
    an operational state, not a broken file — the caller degrades."""
    storage = LocalArtifactStorage(tmp_path)
    _write(storage)
    other_catalog = CatalogSnapshot.from_rows("3:2027", [(1, "x-a"), (2, "x-b"), (3, "x-c")])

    bundle = load_artifact_bundle(storage, FAMILY.directory, catalog=other_catalog)

    assert not bundle.is_servable
    assert bundle.status is MappingStatus.REJECTED


def test_diagnostics_are_log_safe_scalars(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    _write(storage)

    diagnostics = load_artifact_bundle(storage, FAMILY.directory, catalog=CATALOG).diagnostics()

    assert diagnostics["model_name"] == FAMILY.name
    assert diagnostics["resolved_count"] == 3
    assert all(isinstance(value, str | int | float) for value in diagnostics.values())
    # No titles, ids or work_ids: startup logs are not a data dump.
    assert "w-a" not in json.dumps(diagnostics)


def test_rebuilding_with_identical_input_produces_identical_payloads(tmp_path: Path) -> None:
    """rec-spec §28. ``trained_at`` and ``model_version`` differ per build by
    design, so determinism is asserted on the payload checksums."""
    first = LocalArtifactStorage(tmp_path / "first")
    second = LocalArtifactStorage(tmp_path / "second")
    payload = {"values": np.array([1, 2, 3], dtype=np.int64)}

    written_first = write_artifact(
        first,
        FAMILY,
        model_version="20260813T120000Z",
        catalog_version=CATALOG.catalog_version,
        items=ITEMS,
        payloads={"payload.npz": lambda path: save_arrays(path, payload)},
    )
    written_second = write_artifact(
        second,
        FAMILY,
        model_version="20260814T235959Z",
        catalog_version=CATALOG.catalog_version,
        items=ITEMS,
        payloads={"payload.npz": lambda path: save_arrays(path, payload)},
    )

    assert written_first.checksums == written_second.checksums


def test_config_is_preserved_for_reproducibility(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    _write(storage, config={"prior_strength": 50.0, "sources": ["goodreads"]})

    manifest = storage.load_manifest(FAMILY.directory)

    assert manifest.config == {"prior_strength": 50.0, "sources": ["goodreads"]}
