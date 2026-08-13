"""CLI: build the content-embedding artifact (rec-spec §11, ADR-0018).

    uv run --project apps/api --group training \\
        python -m book_app.cli.build_content_embeddings [options]

or via ``make build-content``. Needs the ``training`` group
(``make setup-training``) — it downloads and runs a 0.6B transformer.

**This is the slowest build in the system.** Measured on this catalog and
this hardware: 17.6 books/s on Apple MPS at 512 tokens and batch 16, so the
full 92,524-book pass takes about 88 minutes. ``--limit`` exists for
development; the encoder itself is a one-time ~1.2 GB download.

The output is one L2-normalized ``float32`` matrix plus a manifest recording
every input to its meaning — encoder name and resolved revision, dimension,
sequence cap, prompt version, text-template version, tag-cleaning version.
rec-spec §11.1 asks for exactly that list, because changing any of them
changes every vector.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from book_recommender.artifacts import LocalArtifactStorage, write_artifact
from book_recommender.artifacts.content import (
    DIMENSION_CONFIG_KEY,
    EMBEDDINGS_FILENAME,
    ENCODER_CONFIG_KEY,
    ENCODER_REVISION_CONFIG_KEY,
    NORMALIZED_CONFIG_KEY,
    PROMPT_VERSION_CONFIG_KEY,
    TAGS_VERSION_CONFIG_KEY,
    TEXT_TEMPLATE_CONFIG_KEY,
    write_embeddings,
)
from book_recommender.config import CONTENT, ENCODER_DEFAULT, EncoderConfig
from book_recommender.content.tags import TAG_CLEANING_VERSION
from book_recommender.content.text_builder import TEXT_TEMPLATE_VERSION
from sqlalchemy.orm import Session, sessionmaker

from book_app.core.config import get_settings
from book_app.core.database import create_db_engine, create_session_factory
from book_app.core.logging import configure_logging, get_logger
from book_app.modules.books import repository as books_repository
from book_app.modules.recommendations.artifact_build import (
    ArtifactBuildReport,
    new_model_version,
    register_model_version,
)
from book_app.modules.recommendations.artifact_paths import resolve_artifact_root
from book_app.modules.recommendations.content_source import encoder_texts, read_content_rows

logger = get_logger("book_app.cli.build_content_embeddings")

PREVIEW_SIZE = 3


def run_build(
    session_factory: sessionmaker[Session],
    *,
    artifact_root: Path,
    encoder_config: EncoderConfig = ENCODER_DEFAULT,
    device: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    show_progress: bool = False,
) -> ArtifactBuildReport:
    with session_factory() as session:
        catalog_version = books_repository.get_catalog_version(session)
        model_version = new_model_version()

        started = time.perf_counter()
        rows, source_report = read_content_rows(session, limit=limit)
        read_seconds = time.perf_counter() - started

        stats: dict[str, int | str] = dict(source_report.as_stats())
        stats["text_template_version"] = TEXT_TEMPLATE_VERSION
        stats["tags_version"] = TAG_CLEANING_VERSION
        stats["read_seconds"] = f"{read_seconds:.1f}"

        preview = [
            {"book_id": row.book_id, "title": row.title, "tags": ", ".join(row.tags[:6])}
            for row in rows[:PREVIEW_SIZE]
        ]

        if not rows:
            return ArtifactBuildReport(
                model_name=CONTENT.name,
                model_version=model_version,
                catalog_version=catalog_version,
                item_count=0,
                dry_run=dry_run,
                stats=stats,
            )

        if dry_run:
            # A dry run deliberately does not load the model: the thing worth
            # checking cheaply is the *text*, and building it is where the
            # tag rules and template actually apply.
            stats["sample_text"] = rows[0].text.text[:300]
            return ArtifactBuildReport(
                model_name=CONTENT.name,
                model_version=model_version,
                catalog_version=catalog_version,
                item_count=len(rows),
                dry_run=True,
                stats=stats,
                preview=preview,
            )

        # Imported here rather than at module scope so that `--dry-run` and
        # the tests that exercise the text pipeline do not need torch.
        from book_app.modules.recommendations.content_encoding import TextEncoder, select_device

        resolved_device = select_device(device)
        encoder = TextEncoder(config=encoder_config, device=resolved_device)
        stats["device"] = resolved_device
        stats["encoder"] = encoder_config.name
        stats["dimension"] = encoder.resolved_dimension
        resolved_revision = encoder.resolved_revision
        stats["encoder_revision"] = resolved_revision or "unpinned"

        started = time.perf_counter()
        embeddings = encoder.encode(encoder_texts(rows), show_progress=show_progress)
        encode_seconds = time.perf_counter() - started
        stats["encode_seconds"] = f"{encode_seconds:.1f}"
        stats["books_per_second"] = f"{len(rows) / max(encode_seconds, 1e-9):.1f}"

        written = write_artifact(
            LocalArtifactStorage(artifact_root),
            CONTENT,
            model_version=model_version,
            catalog_version=catalog_version,
            items=[(row.book_id, row.work_id) for row in rows],
            payloads={EMBEDDINGS_FILENAME: lambda path: write_embeddings(path, embeddings)},
            config={
                ENCODER_CONFIG_KEY: encoder_config.name,
                ENCODER_REVISION_CONFIG_KEY: resolved_revision,
                DIMENSION_CONFIG_KEY: encoder.resolved_dimension,
                NORMALIZED_CONFIG_KEY: True,
                PROMPT_VERSION_CONFIG_KEY: encoder_config.prompt_version,
                TEXT_TEMPLATE_CONFIG_KEY: TEXT_TEMPLATE_VERSION,
                TAGS_VERSION_CONFIG_KEY: TAG_CLEANING_VERSION,
                "max_sequence_length": encoder_config.max_sequence_length,
                "batch_size": encoder_config.batch_size,
                "device": resolved_device,
            },
        )
        register_model_version(session, CONTENT, written)
        session.commit()

        return ArtifactBuildReport(
            model_name=CONTENT.name,
            model_version=model_version,
            catalog_version=catalog_version,
            item_count=len(rows),
            dry_run=False,
            checksums=written.checksums,
            stats=stats,
            preview=preview,
            stale_files=written.stale_files,
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the content-embedding artifact.")
    parser.add_argument("--limit", type=int, help="Embed only the first N books (development)")
    parser.add_argument("--device", help="Force a torch device (default: mps > cuda > cpu)")
    parser.add_argument("--encoder", default=ENCODER_DEFAULT.name)
    parser.add_argument("--dimension", type=int, default=ENCODER_DEFAULT.dimension)
    parser.add_argument(
        "--max-sequence-length", type=int, default=ENCODER_DEFAULT.max_sequence_length
    )
    parser.add_argument("--batch-size", type=int, default=ENCODER_DEFAULT.batch_size)
    parser.add_argument("--revision", default=ENCODER_DEFAULT.revision)
    parser.add_argument("--progress", action="store_true", help="Show the encoder progress bar")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and report the text without loading the model or writing",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    configure_logging(settings)

    encoder_config = EncoderConfig(
        name=args.encoder,
        dimension=args.dimension,
        max_sequence_length=args.max_sequence_length,
        batch_size=args.batch_size,
        revision=args.revision,
        prompt=ENCODER_DEFAULT.prompt,
        prompt_version=ENCODER_DEFAULT.prompt_version,
    )

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        report = run_build(
            session_factory,
            artifact_root=resolve_artifact_root(settings.artifact_storage_local_path),
            encoder_config=encoder_config,
            device=args.device,
            limit=args.limit,
            dry_run=args.dry_run,
            show_progress=args.progress,
        )
    finally:
        engine.dispose()

    print(report.summary_line())
    for line in report.warning_lines():
        print(line)
    for key, value in report.stats.items():
        print(f"  {key}: {value}")
    for row in report.preview:
        print(f"  #{row['book_id']}: {row['title'][:48]!r}  tags=[{row['tags']}]")

    logger.info("build_content_embeddings_completed", **report.stats, dry_run=report.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
