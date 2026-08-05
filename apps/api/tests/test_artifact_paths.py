"""Tests for artifact storage path resolution (spec §10.13)."""

from __future__ import annotations

from pathlib import Path

from book_app.modules.recommendations.artifact_paths import _REPO_ROOT, resolve_artifact_root


def test_relative_path_is_anchored_at_the_repo_root() -> None:
    resolved = resolve_artifact_root(Path("data/artifacts"))
    assert resolved == _REPO_ROOT / "data" / "artifacts"
    assert resolved.is_absolute()


def test_absolute_path_passes_through_unchanged() -> None:
    absolute = Path("/var/artifacts")
    assert resolve_artifact_root(absolute) == absolute


def test_repo_root_actually_contains_the_app_specification() -> None:
    """Confirms the hardcoded ``parents[N]`` index in artifact_paths.py
    still points at the real repo root, not some other ancestor directory —
    a future file move could silently break the index without this."""
    assert (_REPO_ROOT / "APP_SPECIFICATION.md").is_file()
