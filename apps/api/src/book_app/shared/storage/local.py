"""Local filesystem object storage."""

from __future__ import annotations

from pathlib import Path

from book_app.shared.storage.base import UnsafeObjectKeyError


class LocalFileStorage:
    """Resolves an object key to a path under a configured root, safely.

    Same class serves cover images (root: ``COVER_STORAGE_LOCAL_PATH``,
    default ``data/processed/covers``) and, later, model artifacts (root:
    ``ARTIFACT_STORAGE_LOCAL_PATH``) — the access pattern is identical.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def resolve(self, object_key: str) -> Path:
        candidate = (self._root / object_key).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError as exc:
            raise UnsafeObjectKeyError(f"object key escapes storage root: {object_key!r}") from exc
        return candidate

    def exists(self, object_key: str) -> bool:
        try:
            return self.resolve(object_key).is_file()
        except UnsafeObjectKeyError:
            return False
