"""Tests for the OpenAPI schema export CLI (spec §16: "Generate frontend
types/client from FastAPI OpenAPI"). No database needed — constructing the
app and introspecting its routes never touches Postgres.
"""

from __future__ import annotations

import json
from pathlib import Path

from book_app.cli.export_openapi import run_export


def test_run_export_writes_a_valid_openapi_document(tmp_path: Path) -> None:
    output = tmp_path / "openapi.json"
    schema = run_export(output)

    assert output.is_file()
    written = json.loads(output.read_text())
    assert written == schema
    assert schema["openapi"].startswith("3.")
    assert "/api/v1/auth/login" in schema["paths"]
    assert "/api/v1/recommendations/home" in schema["paths"]


def test_run_export_creates_missing_parent_directories(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "dir" / "openapi.json"
    run_export(output)
    assert output.is_file()
