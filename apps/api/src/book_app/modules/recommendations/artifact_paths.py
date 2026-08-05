"""Shared artifact-location constants for the popularity model — imported
by both ``cli/build_popularity.py`` (the writer) and this module's
``wiring.py`` (the reader), so the two can never disagree about where the
artifact lives.

``Settings.artifact_storage_local_path`` defaults to a bare relative path
(``data/artifacts``). Left as-is, where that resolves depends on the
process's current working directory — ``apps/api/`` for ``make
build-popularity``/``make dev-api``, the repo root for a plain ``python -m``
invocation, a Docker ``WORKDIR`` in production — the same risk
``cli/import_catalog.py``'s own docstring documents for its dataset path.
Anchoring at the repo root instead makes both the CLI that writes the
artifact and the app startup code that loads it agree on the same directory
regardless of invocation style.
"""

from __future__ import annotations

from pathlib import Path

POPULARITY_MODEL_NAME = "popularity"
POPULARITY_ARTIFACT_DIR = "popularity/latest"

_REPO_ROOT = Path(__file__).resolve().parents[6]


def resolve_artifact_root(configured_path: Path) -> Path:
    if configured_path.is_absolute():
        return configured_path
    return (_REPO_ROOT / configured_path).resolve()
