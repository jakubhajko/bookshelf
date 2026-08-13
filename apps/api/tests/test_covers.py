"""Tests for GET /api/v1/covers/{object_key} (spec §7.3, §14, §20)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from book_app.core.config import Settings
from book_app.core.covers import _REPO_ROOT, resolve_cover_storage_root
from book_app.shared.storage.base import UnsafeObjectKeyError
from book_app.shared.storage.local import LocalFileStorage

_FAKE_JPEG_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-bytes-for-testing"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    cover_dir = tmp_path / "covers"
    cover_dir.mkdir()
    (cover_dir / "0000000000.jpg").write_bytes(_FAKE_JPEG_BYTES)
    return Settings(environment="test", cover_storage_local_path=cover_dir)


def test_returns_cover_bytes_for_a_known_key(client: TestClient) -> None:
    response = client.get("/api/v1/covers/0000000000.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == _FAKE_JPEG_BYTES


def test_returns_404_error_envelope_for_a_missing_key(client: TestClient) -> None:
    response = client.get("/api/v1/covers/does-not-exist.jpg")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "COVER_NOT_FOUND"
    assert body["error"]["request_id"]


def test_unsafe_object_key_maps_to_404_not_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise_unsafe(self: LocalFileStorage, object_key: str) -> Path:
        raise UnsafeObjectKeyError(f"object key escapes storage root: {object_key!r}")

    monkeypatch.setattr(LocalFileStorage, "resolve", _raise_unsafe)
    response = client.get("/api/v1/covers/anything.jpg")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "COVER_NOT_FOUND"


def test_does_not_require_authentication(client: TestClient) -> None:
    # No cookies attached — must still resolve, never 401. Cover art is
    # public; see core/covers.py's module docstring for why this route is
    # deliberately the one unauthenticated surface in the app.
    response = client.get("/api/v1/covers/0000000000.jpg")
    assert response.status_code != 401


def test_relative_configured_path_is_anchored_at_the_repo_root() -> None:
    # Regression test: a relative `cover_storage_local_path` (the
    # documented default) resolved against the process's CWD instead of the
    # repo root, so `make dev-api`'s own `cd apps/api &&` launch convention
    # made every cover 404 — caught by live-smoke-testing this route
    # against a real dev server, not by the fixture-based tests above
    # (`tmp_path` is always absolute, so they never exercised this branch).
    resolved = resolve_cover_storage_root(Path("data/processed/covers"))
    assert resolved == _REPO_ROOT / "data" / "processed" / "covers"
    assert resolved.is_absolute()


def test_absolute_configured_path_passes_through_unchanged() -> None:
    absolute = Path("/var/covers")
    assert resolve_cover_storage_root(absolute) == absolute


def test_repo_root_index_points_at_the_real_repo_root() -> None:
    """Confirms the hardcoded `parents[N]` index in core/covers.py still
    points at the real repo root, not some other ancestor directory — a
    future file move could silently break the index without this (same
    check, and the same structural-marker rationale, as
    `tests/test_artifact_paths.py`'s equivalent)."""
    assert (_REPO_ROOT / "Makefile").is_file()
    assert (_REPO_ROOT / "pyproject.toml").is_file()
    assert (_REPO_ROOT / "apps").is_dir()
    assert (_REPO_ROOT / "packages").is_dir()
