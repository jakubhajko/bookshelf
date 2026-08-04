"""Tests for LocalFileStorage's path-traversal safety (spec §14: "safe local cover paths")."""

from __future__ import annotations

from pathlib import Path

import pytest

from book_app.shared.storage import LocalFileStorage, UnsafeObjectKeyError


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    (tmp_path / "0001234567.jpg").write_bytes(b"fake-cover-bytes")
    return LocalFileStorage(root=tmp_path)


def test_resolves_a_plain_key(storage: LocalFileStorage, tmp_path: Path) -> None:
    resolved = storage.resolve("0001234567.jpg")
    assert resolved == (tmp_path / "0001234567.jpg").resolve()


def test_exists_true_for_a_real_file(storage: LocalFileStorage) -> None:
    assert storage.exists("0001234567.jpg") is True


def test_exists_false_for_a_missing_file(storage: LocalFileStorage) -> None:
    assert storage.exists("0009999999.jpg") is False


@pytest.mark.parametrize(
    "malicious_key",
    [
        "../../../etc/passwd",
        "../outside.jpg",
        "sub/../../outside.jpg",
        "/etc/passwd",
    ],
)
def test_rejects_path_traversal(storage: LocalFileStorage, malicious_key: str) -> None:
    with pytest.raises(UnsafeObjectKeyError):
        storage.resolve(malicious_key)


def test_exists_is_false_rather_than_raising_for_traversal(storage: LocalFileStorage) -> None:
    assert storage.exists("../../../etc/passwd") is False
