"""CLI: import the canonical Parquet catalog into PostgreSQL (spec §7.4, §11).

    uv run --project apps/api python -m book_app.cli.import_catalog [options]

or via ``make import-data`` / ``make import-data-dry-run``. Never run at API
startup (spec §7.4) — this is a standalone, explicitly-invoked command.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from book_app.core.config import get_settings
from book_app.core.database import create_db_engine, create_session_factory
from book_app.core.logging import configure_logging, get_logger
from book_app.modules.books import repository
from book_app.modules.books.import_adapter import (
    CanonicalBook,
    CanonicalSimilarityRef,
    RejectedRow,
    read_canonical_books,
)

logger = get_logger("book_app.cli.import_catalog")

# Anchored to the repo root via __file__, not the current working directory
# — `make import-data` runs this from apps/api/, a plain `python -m` might
# run it from the repo root, and a Docker container's WORKDIR differs from
# both. A cwd-relative default would silently break depending on invocation.
_REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_SOURCE = _REPO_ROOT / "data" / "processed" / "books.parquet"
DEFAULT_BATCH_SIZE = 500


@dataclass
class ImportReport:
    source: str
    dry_run: bool
    batch_size: int
    started_at: str
    finished_at: str | None = None
    total_rows: int = 0
    books_upserted: int = 0
    rows_rejected: int = 0
    rejected_samples: list[dict[str, Any]] = field(default_factory=list)
    similarities_resolved: int = 0
    similarities_dangling_or_self: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import the canonical book catalog into PostgreSQL."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Path to books.parquet")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and report without writing"
    )
    parser.add_argument(
        "--report", type=Path, default=None, help="Optional path to write a JSON report"
    )
    parser.add_argument(
        "--max-rejected-samples",
        type=int,
        default=20,
        help="How many rejected-row examples to keep in the report",
    )
    return parser.parse_args(argv)


def run_import(
    session_factory: sessionmaker[Session],
    *,
    source: Path,
    batch_size: int,
    dry_run: bool,
    max_rejected_samples: int,
) -> ImportReport:
    report = ImportReport(
        source=str(source),
        dry_run=dry_run,
        batch_size=batch_size,
        started_at=datetime.now(UTC).isoformat(),
    )

    books: list[CanonicalBook] = []
    for record in read_canonical_books(source):
        report.total_rows += 1
        if isinstance(record, RejectedRow):
            report.rows_rejected += 1
            if len(report.rejected_samples) < max_rejected_samples:
                report.rejected_samples.append(record.model_dump())
            continue
        books.append(record)

    work_id_to_id: dict[str, int] = {}
    source_book_id_to_id: dict[str, int] = {}
    pending_similarities: list[tuple[int, list[CanonicalSimilarityRef]]] = []

    for batch in itertools.batched(books, batch_size):
        with session_factory() as session, session.begin():
            book_ids = repository.upsert_books_batch(session, batch)
            repository.sync_authors_batch(session, batch, book_ids)
            repository.sync_genres_batch(session, batch, book_ids)
            repository.sync_shelf_tags_batch(session, batch, book_ids)

            for b in batch:
                book_id = book_ids[b.work_id]
                work_id_to_id[b.work_id] = book_id
                if b.source_book_id:
                    source_book_id_to_id[b.source_book_id] = book_id
                pending_similarities.append((book_id, b.similarities))
                report.books_upserted += 1

            if dry_run:
                session.rollback()

        logger.info(
            "import_batch_committed",
            books_in_batch=len(batch),
            books_upserted_total=report.books_upserted,
            dry_run=dry_run,
        )

    for sim_batch in itertools.batched(pending_similarities, batch_size):
        batch_book_ids = [book_id for book_id, _ in sim_batch]
        all_rows: list[dict[str, Any]] = []
        for book_id, similarities in sim_batch:
            rows = repository.resolve_similarities(
                similarities, book_id, work_id_to_id, source_book_id_to_id
            )
            report.similarities_resolved += len(rows)
            report.similarities_dangling_or_self += len(similarities) - len(rows)
            all_rows.extend(rows)

        # Dry-run: report what *would* be written, but don't write it — the
        # book rows these edges reference were themselves rolled back above,
        # so an actual insert would fail its foreign key either way.
        if not dry_run:
            with session_factory() as session, session.begin():
                repository.replace_book_similarities_batch(session, batch_book_ids, all_rows)

    report.finished_at = datetime.now(UTC).isoformat()
    return report


def _print_summary(report: ImportReport) -> None:
    mode = "DRY RUN (no changes persisted)" if report.dry_run else "APPLIED"
    print(f"\nImport summary [{mode}]")
    print(f"  source:                 {report.source}")
    print(f"  total rows read:        {report.total_rows}")
    print(f"  books upserted:         {report.books_upserted}")
    print(f"  rows rejected:          {report.rows_rejected}")
    print(f"  similarity edges kept:  {report.similarities_resolved}")
    print(f"  similarity edges dropped (dangling/self): {report.similarities_dangling_or_self}")
    if report.rejected_samples:
        print("  rejected row samples:")
        for sample in report.rejected_samples:
            work_id, reasons = sample["work_id"], sample["reasons"]
            print(f"    - row {sample['row_index']} (work_id={work_id!r}): {reasons}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    configure_logging(settings)

    if not args.source.exists():
        print(f"error: source file not found: {args.source}", file=sys.stderr)
        return 1

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        report = run_import(
            session_factory,
            source=args.source,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            max_rejected_samples=args.max_rejected_samples,
        )
    finally:
        engine.dispose()

    _print_summary(report)

    if args.report:
        args.report.write_text(json.dumps(report.to_dict(), indent=2))
        print(f"\nFull report written to {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
