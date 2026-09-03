"""Upload cover images to S3-compatible object storage.

    uv run --project apps/api python -m book_app.cli.upload_covers [--limit N] [--dry-run]

Covers are the other half of Phase 3's storage move, and the opposite case to
model artifacts. Artifacts are *read by the server* and must end up on a local
filesystem for ``np.load``/mmap; covers are *read by the browser* and should
never touch the server at all. So there is no sync here — only a one-way
upload, after which ``core/covers.py`` redirects to the public origin.

Credentials: the endpoint and key pair come from the ``ARTIFACT_STORAGE_S3_*``
settings — one object-store account, one credential pair, used here with the
read/write token. The destination bucket is ``COVER_STORAGE_S3_BUCKET``.
Production never sets any of this for covers: serving them needs only the
public base URL, because the bytes are public by design (ADR-0011).

Resumable by construction: existing keys are listed first and skipped, so an
interrupted run is restarted by running it again. With ~102k objects that
matters more than it would for six artifact families.
"""

from __future__ import annotations

import argparse
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from book_app.core.config import get_settings
from book_app.core.covers import resolve_cover_storage_root
from book_app.core.logging import configure_logging, get_logger
from book_app.shared.storage.s3_artifacts import build_s3_client

logger = get_logger("book_app.cli.upload_covers")

#: Object storage is latency-bound per request, not bandwidth-bound, for files
#: this small (~11 KB average). Concurrency is what makes 100k uploads finish.
DEFAULT_CONCURRENCY = 32


def _existing_keys(client: object, bucket: str) -> set[str]:
    """Every key already in the bucket, so a re-run skips completed work."""
    keys: set[str] = set()
    paginator = client.get_paginator("list_objects_v2")  # type: ignore[attr-defined]
    for page in paginator.paginate(Bucket=bucket):
        for entry in page.get("Contents", []):
            keys.add(entry["Key"])
    return keys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Upload at most N covers")
    parser.add_argument("--dry-run", action="store_true", help="Count work, upload nothing")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings, stream=sys.stderr)

    bucket = settings.cover_storage_s3_bucket
    if not bucket:
        print("error: COVER_STORAGE_S3_BUCKET is not set", file=sys.stderr)
        return 2

    root = resolve_cover_storage_root(settings.cover_storage_local_path)
    if not root.is_dir():
        print(f"error: no cover directory at {root}", file=sys.stderr)
        return 2

    covers = sorted(p for p in root.iterdir() if p.is_file() and p.suffix == ".jpg")
    if not covers:
        print(f"error: no .jpg files under {root}", file=sys.stderr)
        return 2

    client = build_s3_client(settings)
    print(f"listing existing objects in s3://{bucket}/ …", file=sys.stderr)
    done = set() if args.dry_run else _existing_keys(client, bucket)

    pending = [p for p in covers if p.name not in done]
    if args.limit is not None:
        pending = pending[: args.limit]

    total_mb = sum(p.stat().st_size for p in pending) / (1024 * 1024)
    print(
        f"{len(covers)} covers on disk, {len(done)} already uploaded, "
        f"{len(pending)} to upload ({total_mb:.0f} MB)"
    )
    if args.dry_run or not pending:
        print("dry run — nothing uploaded" if args.dry_run else "nothing to do")
        return 0

    counter = 0
    failures: list[tuple[str, str]] = []
    lock = threading.Lock()

    def upload(path: Path) -> None:
        nonlocal counter
        try:
            client.upload_file(  # type: ignore[attr-defined]
                Filename=str(path),
                Bucket=bucket,
                Key=path.name,
                ExtraArgs={"ContentType": "image/jpeg"},
            )
        except Exception as exc:  # noqa: BLE001 - collected and reported below
            with lock:
                failures.append((path.name, str(exc)))
            return
        with lock:
            counter += 1
            if counter % 2000 == 0 or counter == len(pending):
                print(f"  {counter}/{len(pending)} uploaded", flush=True)

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(upload, p) for p in pending]
        for future in as_completed(futures):
            future.result()

    if failures:
        print(
            f"\n{len(failures)} FAILED (re-run to retry — completed keys are skipped):",
            file=sys.stderr,
        )
        for name, err in failures[:10]:
            print(f"  {name}: {err[:120]}", file=sys.stderr)
        return 1

    print(f"done — {counter} covers uploaded ({total_mb:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
