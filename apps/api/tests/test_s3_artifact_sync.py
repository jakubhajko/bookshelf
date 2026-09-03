"""Tests for remote artifact synchronisation.

The behaviour worth protecting here is not "does boto3 work" — it is that a
*corrupt or wrong* artifact is refused rather than loaded, and that a
misconfigured remote backend fails loudly instead of silently serving the
degraded fallback. Both are the difference between a deployment that is
visibly broken and one that is quietly worse than it should be.

No boto3 involved: ``sync_artifacts`` takes a client conforming to the
``_ObjectGetter`` protocol, so a fake that copies from a directory exercises
every branch.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from book_recommender.config import FAMILIES

from book_app.core.config import Settings
from book_app.shared.storage.s3_artifacts import (
    ArtifactSyncError,
    _object_key,
    sync_artifacts,
)


class FakeS3:
    """Serves objects from a local directory, counting downloads."""

    def __init__(self, source: Path) -> None:
        self.source = source
        self.downloads: list[str] = []

    def download_file(self, Bucket: str, Key: str, Filename: str) -> None:  # noqa: N803
        origin = self.source / Key
        if not origin.is_file():
            raise FileNotFoundError(f"no such key: {Key}")
        self.downloads.append(Key)
        Path(Filename).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, Filename)


def _write_family(bucket: Path, directory: str, payload: bytes, *, sha: str | None = None) -> None:
    """Write one artifact family into the fake bucket, manifest included."""
    target = bucket / directory
    target.mkdir(parents=True, exist_ok=True)
    (target / "mapping.npz").write_bytes(payload)
    manifest = {
        "schema_version": 2,
        "model_name": directory.split("/")[0],
        "model_version": "20260101T000000Z",
        "catalog_version": "1:2026-01-01T00:00:00+00:00",
        "trained_at": "2026-01-01T00:00:00Z",
        "item_count": 1,
        "preprocessing_version": "test-v1",
        "training_transform_version": None,
        "config": {},
        "mapping_file": "mapping.npz",
        "files": [
            {
                "name": "mapping.npz",
                "sha256": sha or hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            }
        ],
    }
    (target / "manifest.json").write_text(json.dumps(manifest))


@pytest.fixture
def bucket(tmp_path: Path) -> Path:
    root = tmp_path / "bucket"
    for family in FAMILIES.values():
        _write_family(root, family.directory, f"payload-{family.name}".encode())
    return root


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        artifact_storage_backend="s3",
        artifact_storage_s3_bucket="test-bucket",
        artifact_storage_s3_access_key_id="key",
        artifact_storage_s3_secret_access_key="secret",
        artifact_cache_dir=tmp_path / "cache",
    )


def test_object_key_joins_flatly_and_skips_empty_prefix() -> None:
    assert _object_key("", "als/latest", "x.npy") == "als/latest/x.npy"
    assert _object_key("v2", "als/latest", "x.npy") == "v2/als/latest/x.npy"
    assert _object_key("/v2/", "als/latest", "x.npy") == "v2/als/latest/x.npy"


def test_sync_downloads_every_family(tmp_path: Path, bucket: Path) -> None:
    settings = _settings(tmp_path)
    client = FakeS3(bucket)

    root = sync_artifacts(settings, client)

    assert root == settings.artifact_cache_dir
    for family in FAMILIES.values():
        assert (root / family.directory / "manifest.json").is_file()
        assert (root / family.directory / "mapping.npz").is_file()


def test_second_sync_reuses_cache_and_refetches_only_manifests(
    tmp_path: Path, bucket: Path
) -> None:
    """A warm container must not re-download 244 MB it already has."""
    settings = _settings(tmp_path)
    client = FakeS3(bucket)
    sync_artifacts(settings, client)
    first = len(client.downloads)

    client.downloads.clear()
    sync_artifacts(settings, client)

    # Manifests are always refetched (they are what proves the rest is current);
    # the payloads beside them are not.
    assert len(client.downloads) == len(FAMILIES)
    assert all(key.endswith("manifest.json") for key in client.downloads)
    assert first > len(FAMILIES)


def test_checksum_mismatch_raises_and_removes_the_bad_file(tmp_path: Path) -> None:
    """A file whose bytes disagree with its manifest must never be loaded."""
    root = tmp_path / "bucket"
    for family in FAMILIES.values():
        _write_family(
            root, family.directory, b"payload", sha=hashlib.sha256(b"different").hexdigest()
        )
    settings = _settings(tmp_path)

    with pytest.raises(ArtifactSyncError, match="checksum mismatch"):
        sync_artifacts(settings, FakeS3(root))

    corrupted = list(settings.artifact_cache_dir.rglob("mapping.npz"))
    assert corrupted == [], "a failed download must not be left on disk to be loaded later"


def test_missing_object_raises_rather_than_degrading(tmp_path: Path, bucket: Path) -> None:
    """The whole point: a configured remote backend that cannot deliver is an
    error, not a quiet fall back to the popularity engine."""
    first = next(iter(FAMILIES.values()))
    (bucket / first.directory / "manifest.json").unlink()

    with pytest.raises(ArtifactSyncError, match="could not download"):
        sync_artifacts(_settings(tmp_path), FakeS3(bucket))


def test_unreadable_manifest_raises(tmp_path: Path, bucket: Path) -> None:
    first = next(iter(FAMILIES.values()))
    (bucket / first.directory / "manifest.json").write_text("{not json")

    with pytest.raises(ArtifactSyncError, match="unreadable manifest"):
        sync_artifacts(_settings(tmp_path), FakeS3(bucket))


def test_s3_backend_without_credentials_is_rejected_at_config_time() -> None:
    with pytest.raises(ValueError, match="ARTIFACT_STORAGE_S3_BUCKET"):
        Settings(artifact_storage_backend="s3")
