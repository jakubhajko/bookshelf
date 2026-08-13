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


def test_repo_root_index_points_at_the_real_repo_root() -> None:
    """Confirms the hardcoded ``parents[N]`` index in artifact_paths.py
    still points at the real repo root, not some other ancestor directory —
    a future file move could silently break the index without this.

    Anchored on the workspace's *structural* markers (the Makefile, the
    workspace-root ``pyproject.toml``, and the two member directories it
    declares) rather than on a specification document. The original version
    of this check used root ``APP_SPECIFICATION.md`` as its sentinel and
    broke the moment that document was reorganized into
    ``archive_of_structural_prompts/`` — a documentation move that says
    nothing about whether this path index is still correct. The monorepo
    layout below is non-negotiable architecture (CLAUDE.md), so it is a
    sentinel that only changes when the thing being asserted really does.
    """
    assert (_REPO_ROOT / "Makefile").is_file()
    assert (_REPO_ROOT / "pyproject.toml").is_file()
    assert (_REPO_ROOT / "apps").is_dir()
    assert (_REPO_ROOT / "packages").is_dir()
