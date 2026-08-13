"""Where artifacts live on disk, and how the application reads the catalog
identity table the loaders resolve against (ADR-0014).

``Settings.artifact_storage_local_path`` defaults to a bare relative path
(``data/artifacts``). Left as-is, where that resolves depends on the
process's current working directory — ``apps/api/`` for ``make
build-recommender-artifacts``/``make dev-api``, the repo root for a plain
``python -m`` invocation, a Docker ``WORKDIR`` in production — the same risk
``cli/import_catalog.py``'s own docstring documents for its dataset path.
Anchoring at the repo root instead makes the CLIs that write artifacts and
the app startup code that loads them agree on the same directory regardless
of invocation style.

The *names* of the artifact families deliberately do not live here any more.
They moved to ``book_recommender.config`` in recommender Phase R3, next to
the loaders that consume them: ADR-0014 puts artifact format knowledge in the
recommender package, and a directory name is part of that format.
"""

from __future__ import annotations

from pathlib import Path

from book_recommender.artifacts import CatalogSnapshot, LocalArtifactStorage
from sqlalchemy.orm import Session

from book_app.modules.books import repository as books_repository

_REPO_ROOT = Path(__file__).resolve().parents[6]


def resolve_artifact_root(configured_path: Path) -> Path:
    if configured_path.is_absolute():
        return configured_path
    return (_REPO_ROOT / configured_path).resolve()


def build_artifact_storage(configured_path: Path) -> LocalArtifactStorage:
    return LocalArtifactStorage(resolve_artifact_root(configured_path))


def read_catalog_snapshot(session: Session) -> CatalogSnapshot:
    """The live catalog's ``work_id`` → ``book_id`` table plus its version.

    Both halves come from the same session so they describe the same instant:
    a version string paired with a mapping read a moment later could claim
    compatibility with a catalog that had already changed.
    """
    return CatalogSnapshot.from_rows(
        catalog_version=books_repository.get_catalog_version(session),
        rows=books_repository.get_active_catalog_identities(session),
    )
