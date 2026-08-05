"""CLI: export the FastAPI OpenAPI schema to a JSON file (spec §16:
"Generate frontend types/client from FastAPI OpenAPI").

    uv run --project apps/api python -m book_app.cli.export_openapi [options]

or via `make generate-api-client`, which also runs the frontend's
``openapi-typescript`` step against this file's output. Doesn't need a live
database — constructing the app and introspecting its routes never touches
Postgres (see ``main.py``'s own docstring on why that's true, and this is
the same property Phase 5's test suite already relies on).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from book_app.main import create_app

_REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_OUTPUT = _REPO_ROOT / "apps" / "web" / "openapi.json"


def run_export(output: Path) -> dict[str, Any]:
    app = create_app()
    schema: dict[str, Any] = app.openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, indent=2) + "\n")
    return schema


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the FastAPI OpenAPI schema to a JSON file."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    schema = run_export(args.output)
    print(f"export_openapi: wrote {len(schema['paths'])} paths to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
