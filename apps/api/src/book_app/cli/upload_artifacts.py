"""Upload locally-built model artifacts to S3-compatible object storage.

    uv run --project apps/api python -m book_app.cli.upload_artifacts [--dry-run]

The offline half of the artifact lifecycle (ADR-0014, rec-spec §8)::

    build_* CLIs  ->  data/artifacts/  ->  THIS  ->  object storage
                                                        |
                                      API startup sync  v
                                    shared/storage/s3_artifacts.py

Artifacts are built on a machine with the training dependency group and the
full catalog database; the serving container has neither. Object storage is
what connects them, which is why the API never builds and this never serves.

Credentials come from the same ``ARTIFACT_STORAGE_S3_*`` settings the API
reads — but with *different values*: this runs with a read/write token, the
deployed API runs with a read-only one. Same configuration surface, different
privilege per context, which is the point of putting credentials in the
environment rather than in code.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from book_recommender.artifacts.manifest import ArtifactManifest
from book_recommender.config import FAMILIES

from book_app.core.config import get_settings
from book_app.core.logging import configure_logging, get_logger
from book_app.modules.recommendations.artifact_paths import resolve_artifact_root
from book_app.shared.storage.s3_artifacts import (
    MANIFEST_FILENAME,
    ArtifactSyncError,
    _object_key,
    build_s3_client,
)

logger = get_logger("book_app.cli.upload_artifacts")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="List what would be uploaded, upload nothing"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    # Logs to stderr so `--dry-run | grep` stays usable (same reasoning as
    # evaluate_recommender's own --json handling).
    configure_logging(settings, stream=sys.stderr)

    bucket = settings.artifact_storage_s3_bucket
    if not bucket:
        print("error: ARTIFACT_STORAGE_S3_BUCKET is not set", file=sys.stderr)
        return 2

    root = resolve_artifact_root(settings.artifact_storage_local_path)
    if not root.is_dir():
        print(f"error: no local artifact directory at {root}", file=sys.stderr)
        return 2

    client = None if args.dry_run else build_s3_client(settings)
    prefix = settings.artifact_storage_s3_prefix

    planned: list[tuple[Path, str, int]] = []
    for family in FAMILIES.values():
        directory = root / family.directory
        manifest_path = directory / MANIFEST_FILENAME
        if not manifest_path.is_file():
            print(
                f"error: {family.name}: no {MANIFEST_FILENAME} at {directory} "
                f"(run `make build-recommender-artifacts` first)",
                file=sys.stderr,
            )
            return 1
        try:
            manifest = ArtifactManifest.model_validate_json(manifest_path.read_text())
        except ValueError as exc:
            print(f"error: {family.name}: unreadable manifest: {exc}", file=sys.stderr)
            return 1

        # The manifest is uploaded last, deliberately: it is what the sync
        # reads first, so a run interrupted midway leaves the previous
        # manifest pointing at the previous (complete) files rather than
        # advertising files that are not all there yet.
        for entry in manifest.files:
            local = directory / entry.name
            if not local.is_file():
                print(f"error: {family.name}: manifest lists missing {entry.name}", file=sys.stderr)
                return 1
            if local.stat().st_size != entry.size_bytes:
                print(
                    f"error: {family.name}/{entry.name}: size {local.stat().st_size} "
                    f"does not match manifest {entry.size_bytes} — rebuild the artifact",
                    file=sys.stderr,
                )
                return 1
            planned.append(
                (local, _object_key(prefix, family.directory, entry.name), entry.size_bytes)
            )
        planned.append(
            (
                manifest_path,
                _object_key(prefix, family.directory, MANIFEST_FILENAME),
                manifest_path.stat().st_size,
            )
        )

    total_mb = sum(size for _, _, size in planned) / (1024 * 1024)
    print(
        f"{'Would upload' if args.dry_run else 'Uploading'} {len(planned)} objects "
        f"({total_mb:.1f} MB) to s3://{bucket}/"
    )
    for local, key, size in planned:
        print(f"  {size / (1024 * 1024):8.2f} MB  {key}")
        if args.dry_run or client is None:
            continue
        try:
            client.upload_file(Filename=str(local), Bucket=bucket, Key=key)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - surfaced as a CLI error
            raise ArtifactSyncError(f"failed uploading {key}: {exc}") from exc

    print("dry run — nothing uploaded" if args.dry_run else f"done — {total_mb:.1f} MB uploaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
