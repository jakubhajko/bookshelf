"""LocalFileStorage against the real sample cover files (spec §13.3: "local covers").

Complements apps/api/tests/test_local_file_storage.py, which covers the
safety logic in isolation with synthetic tmp_path fixtures. This proves the
same class resolves genuine ``cover_file`` values from the dataset against
the actual files shipped in data/sample/covers/.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from book_app.shared.storage import LocalFileStorage

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_BOOKS = REPO_ROOT / "data" / "sample" / "books.parquet"
SAMPLE_COVERS = REPO_ROOT / "data" / "sample" / "covers"


def test_sample_covers_directory_exists() -> None:
    assert SAMPLE_COVERS.is_dir(), (
        "data/sample/covers/ is missing - regenerate with "
        "`uv run --project apps/api python scripts/data_import/build_sample_fixture.py`"
    )


def test_every_covered_sample_row_resolves_to_a_real_file() -> None:
    df = pd.read_parquet(SAMPLE_BOOKS)
    cover_files = df["cover_file"].dropna().tolist()
    assert cover_files, "sample fixture has no covered rows to test against"

    storage = LocalFileStorage(root=SAMPLE_COVERS)
    missing = [key for key in cover_files if not storage.exists(key)]

    assert missing == [], (
        f"{len(missing)} cover_file values have no matching file in the sample fixture"
    )


def test_resolved_path_stays_under_the_covers_root() -> None:
    df = pd.read_parquet(SAMPLE_BOOKS)
    sample_key = df["cover_file"].dropna().iloc[0]

    storage = LocalFileStorage(root=SAMPLE_COVERS)
    resolved = storage.resolve(sample_key)

    assert resolved.is_relative_to(SAMPLE_COVERS.resolve())
    assert resolved.is_file()
