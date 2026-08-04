"""Generate the small books.parquet + covers fixture used by integration tests (spec §13.3).

Run manually when the fixture needs regenerating (uses apps/api's
environment, since it's the only place pandas/pyarrow are already a
dependency):

    uv run --project apps/api python scripts/data_import/build_sample_fixture.py

Reads data/processed/books.parquet + data/processed/covers/, writes
data/sample/books.parquet + data/sample/covers/. Deterministic (fixed seed)
so the fixture is stable across runs unless the source dataset changes.

Cover files are placeholders, NOT copies of the real cover art: the real
files are copyrighted book covers scraped from Goodreads/Open Library (see
data/README.md's provenance note), and this fixture is committed to git —
shipping real cover images in the repo would mean redistributing copyrighted
material. tests/integration/test_local_covers.py only asserts that
LocalFileStorage resolves the right filename to an existing, safely-scoped
path; it never reads image bytes, so a placeholder is exactly as good a test
fixture as the real file.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_BOOKS = REPO_ROOT / "data" / "processed" / "books.parquet"
SAMPLE_BOOKS = REPO_ROOT / "data" / "sample" / "books.parquet"
SAMPLE_COVERS = REPO_ROOT / "data" / "sample" / "covers"

SAMPLE_SIZE = 300
RANDOM_SEED = 20260804  # arbitrary, fixed for a deterministic fixture


def main() -> None:
    df = pd.read_parquet(SOURCE_BOOKS)

    # Deliberately keep the one known-bad row (empty work_id, see
    # docs/implementation/plan.md) so integration tests exercise the
    # importer's rejection path against the same fixture as everything
    # else, instead of a hand-crafted special case.
    bad_rows = df[df["work_id"] == ""]
    valid = df[df["work_id"] != ""]

    covered = valid[valid["has_cover"]]
    uncovered = valid[~valid["has_cover"]]

    covered_sample = covered.sample(n=min(150, len(covered)), random_state=RANDOM_SEED)
    remaining = SAMPLE_SIZE - len(covered_sample)
    uncovered_sample = uncovered.sample(
        n=min(remaining, len(uncovered)), random_state=RANDOM_SEED
    )

    sample = (
        pd.concat([bad_rows, covered_sample, uncovered_sample])
        .drop_duplicates(subset=["work_id"])
        .reset_index(drop=True)
    )

    SAMPLE_COVERS.mkdir(parents=True, exist_ok=True)
    placeholder_count = 0
    for cover_file in sample["cover_file"].dropna():
        placeholder = SAMPLE_COVERS / cover_file
        placeholder.write_bytes(
            f"placeholder fixture, not real cover art: {cover_file}\n".encode()
        )
        placeholder_count += 1

    SAMPLE_BOOKS.parent.mkdir(parents=True, exist_ok=True)
    sample.to_parquet(SAMPLE_BOOKS, index=False)

    print(
        f"Sample: {len(sample)} rows ({len(bad_rows)} deliberately invalid), "
        f"{placeholder_count} placeholder cover files written"
    )
    print(f"Written to {SAMPLE_BOOKS} and {SAMPLE_COVERS}")


if __name__ == "__main__":
    main()
