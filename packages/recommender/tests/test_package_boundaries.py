"""Repository-hygiene test: this package must stay free of FastAPI/ORM deps.

See ``docs/adr/0001-modular-monolith.md`` and
``docs/adr/0006-recommender-provider-boundary.md``: the application must be
able to depend on ``book_recommender`` without pulling in FastAPI or the
application's ORM, and the package must never import them itself.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

FORBIDDEN_DEPENDENCY_PREFIXES = ("fastapi", "starlette", "sqlalchemy", "alembic", "psycopg")

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_declares_no_forbidden_dependencies() -> None:
    pyproject = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text())
    declared = pyproject["project"].get("dependencies", [])
    for dependency in declared:
        name = dependency.lower()
        assert not name.startswith(FORBIDDEN_DEPENDENCY_PREFIXES), (
            f"packages/recommender must not depend on {dependency!r} "
            "(see docs/adr/0006-recommender-provider-boundary.md)"
        )


def test_no_forbidden_imports_in_source() -> None:
    source_root = PACKAGE_ROOT / "src"
    for path in source_root.rglob("*.py"):
        text = path.read_text()
        for forbidden in ("import fastapi", "import sqlalchemy", "from fastapi", "from sqlalchemy"):
            assert forbidden not in text, (
                f"{path} must not import FastAPI/SQLAlchemy ({forbidden!r})"
            )


def test_package_is_importable() -> None:
    import book_recommender

    assert book_recommender.__version__
