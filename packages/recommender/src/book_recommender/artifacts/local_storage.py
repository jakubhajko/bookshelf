"""Local-disk artifact storage — no FastAPI/ORM imports (spec §10.1).

Deliberately duplicates the shape of ``book_app.shared.storage.LocalFileStorage``
rather than depending on it: importing an apps/api module from here would
invert the intended dependency direction (apps/api depends on this package,
never the other way around).
"""

from __future__ import annotations

from pathlib import Path

from book_recommender.artifacts.manifest import ArtifactManifest
from book_recommender.exceptions import IncompatibleArtifactError

MANIFEST_FILENAME = "manifest.json"


class UnsafeArtifactKeyError(ValueError):
    """An artifact path would resolve outside the storage root."""


class LocalArtifactStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def resolve(self, artifact_dir: str, filename: str) -> Path:
        candidate = self._root.joinpath(artifact_dir, filename).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError as exc:
            raise UnsafeArtifactKeyError(
                f"artifact path escapes storage root: {artifact_dir!r}/{filename!r}"
            ) from exc
        return candidate

    def save_manifest(self, artifact_dir: str, manifest: ArtifactManifest) -> None:
        path = self.resolve(artifact_dir, MANIFEST_FILENAME)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(manifest.model_dump_json(indent=2))

    def load_manifest(self, artifact_dir: str) -> ArtifactManifest:
        path = self.resolve(artifact_dir, MANIFEST_FILENAME)
        if not path.is_file():
            raise IncompatibleArtifactError(f"no manifest at {artifact_dir!r}")
        try:
            return ArtifactManifest.model_validate_json(path.read_text())
        except ValueError as exc:
            raise IncompatibleArtifactError(
                f"unreadable manifest at {artifact_dir!r}: {exc}"
            ) from exc
