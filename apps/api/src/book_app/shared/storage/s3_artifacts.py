"""Materialise remote model artifacts onto local disk before the loaders read them.

Why a *sync* and not an ``ObjectStorage`` implementation
-------------------------------------------------------
The obvious design — an ``S3ArtifactStorage`` alongside ``LocalArtifactStorage``
— cannot work, and the reason is worth writing down so nobody tries it again.
Every artifact loader ultimately calls::

    np.load(path, allow_pickle=False, mmap_mode="r" if mmap else None)

``np.load`` needs a real filesystem path: ``.npz`` is a zip read with random
access, and ``mmap_mode`` requires a file the kernel can map. Neither is
expressible over HTTP range requests without rewriting all six loaders into
streaming readers and giving up mmap. ``LocalArtifactStorage.resolve() -> Path``
is therefore *correct* for artifacts; remoteness simply does not belong in it.

So this module does the one thing that does work: fetch the objects to a local
directory first, then hand the unchanged ``LocalArtifactStorage`` that
directory. It is the same cache-then-load pattern HuggingFace and MLflow use.
The provider seam is this file — pointing at real AWS S3 instead of R2 is a
change of endpoint URL, not of any loader.

Failure is loud
---------------
A deployment that asked for remote artifacts and cannot get them is
*misconfigured*, not *degraded*. Every failure here raises
:class:`ArtifactSyncError`. The recommender's own per-family degradation
(rec-spec §27) stays for the case it was designed for — an artifact that is
genuinely absent or stale — and does not get quietly overloaded to mean
"someone fat-fingered a secret".
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from book_recommender.artifacts.manifest import ArtifactManifest
from book_recommender.config import FAMILIES, ArtifactFamily

from book_app.core.logging import get_logger

if TYPE_CHECKING:
    from book_app.core.config import Settings

logger = get_logger("book_app.storage.s3_artifacts")

MANIFEST_FILENAME = "manifest.json"
#: Read in chunks rather than whole: the content embeddings are 181 MB and on
#: Cloud Run the destination is a tmpfs, so a second full copy in memory during
#: hashing would be 181 MB of the instance's memory limit for no reason.
_HASH_CHUNK_BYTES = 1024 * 1024
#: Six families, at most a couple of files each — enough workers that no
#: transfer waits on another, few enough that we are not opening dozens of TLS
#: connections on a container that is trying to start quickly.
_SYNC_CONCURRENCY = 8


class ArtifactSyncError(RuntimeError):
    """Remote artifacts could not be materialised. Never fall back silently."""


class _ObjectGetter(Protocol):
    """The slice of the S3 client this module uses (keeps tests boto3-free)."""

    def download_file(self, Bucket: str, Key: str, Filename: str) -> None: ...  # noqa: N803


def build_s3_client(settings: Settings) -> _ObjectGetter:
    """An S3 client pointed at whichever S3-compatible store is configured.

    ``endpoint_url=None`` is real AWS S3; set it for Cloudflare R2, MinIO, or
    anything else that speaks the protocol. ``region_name="auto"`` is what R2
    expects and is harmless for S3, which reads the region from the endpoint.
    """
    import boto3  # imported lazily: nothing imports this module in local mode
    from botocore.config import Config

    return boto3.client(  # type: ignore[no-any-return]
        "s3",
        endpoint_url=settings.artifact_storage_s3_endpoint_url,
        aws_access_key_id=settings.artifact_storage_s3_access_key_id,
        aws_secret_access_key=settings.artifact_storage_s3_secret_access_key,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
            # botocore defaults to 10 pooled connections. The artifact sync is
            # serial and never notices, but cli/upload_covers.py pushes ~102k
            # small objects across a thread pool — with the default, every
            # thread beyond the tenth opens and discards a fresh TLS
            # connection ("Connection pool is full, discarding connection"),
            # which is pure handshake overhead on a latency-bound workload.
            max_pool_connections=64,
        ),
    )


def _run_all[T, R](work: Callable[[T], R], items: Sequence[T]) -> list[R]:
    """Run ``work`` over ``items`` concurrently, preserving input order.

    Every task is awaited before anything is raised, so a failure cannot leave
    sibling downloads writing into the cache directory after the caller has
    already given up on the sync. The first failure is the one re-raised —
    later ones are almost always the same root cause (a bad credential, a
    missing prefix) reported six times.
    """
    if not items:
        return []
    results: list[R | None] = [None] * len(items)
    errors: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=min(_SYNC_CONCURRENCY, len(items))) as pool:
        futures = {pool.submit(work, item): index for index, item in enumerate(items)}
        for future in as_completed(futures):
            try:
                results[futures[future]] = future.result()
            except BaseException as exc:  # noqa: BLE001 - re-raised below, in order
                errors.append(exc)
    if errors:
        raise errors[0]
    return cast("list[R]", results)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _object_key(prefix: str, directory: str, filename: str) -> str:
    """Join into an S3 *key*, not a filesystem path.

    A key is one flat string; the slashes are ordinary characters that consoles
    render as folders. There is no ``..`` to resolve and nothing to escape, so
    this is deliberately plain joining rather than ``Path`` arithmetic — the
    filenames themselves are already constrained by the manifest's
    ``plain_filename`` validator.
    """
    return "/".join(part for part in (prefix.strip("/"), directory, filename) if part)


def _download(
    client: _ObjectGetter, bucket: str, key: str, destination: Path, *, expected_sha256: str | None
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(Bucket=bucket, Key=key, Filename=str(destination))
    except Exception as exc:  # noqa: BLE001 - re-raised as a domain error below
        raise ArtifactSyncError(f"could not download s3://{bucket}/{key}: {exc}") from exc
    if expected_sha256 is None:
        return
    actual = _sha256(destination)
    if actual != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ArtifactSyncError(
            f"checksum mismatch for s3://{bucket}/{key}: "
            f"manifest says {expected_sha256[:12]}…, downloaded {actual[:12]}…"
        )


def sync_artifacts(settings: Settings, client: _ObjectGetter | None = None) -> Path:
    """Download every artifact family into ``settings.artifact_cache_dir``.

    Returns the local root to hand to ``LocalArtifactStorage``. Files already
    present with the checksum their manifest claims are left alone, so a warm
    container re-entering this function does no network I/O — which matters
    because Cloud Run may call it again on a lazily-rebuilt provider.

    Raises :class:`ArtifactSyncError` for anything that goes wrong.
    """
    bucket = settings.artifact_storage_s3_bucket
    if not bucket:
        raise ArtifactSyncError("artifact_storage_s3_bucket is not set")

    resolved = client if client is not None else build_s3_client(settings)
    root = settings.artifact_cache_dir
    root.mkdir(parents=True, exist_ok=True)
    prefix = settings.artifact_storage_s3_prefix

    # --- Pass 1: manifests, in parallel -------------------------------------
    # Always re-fetched: ~4 KB each, and each is what proves the much larger
    # files beside it are current.
    def fetch_manifest(family: ArtifactFamily) -> tuple[ArtifactFamily, ArtifactManifest]:
        manifest_path = root / family.directory / MANIFEST_FILENAME
        _download(
            resolved,
            bucket,
            _object_key(prefix, family.directory, MANIFEST_FILENAME),
            manifest_path,
            expected_sha256=None,
        )
        try:
            return family, ArtifactManifest.model_validate_json(manifest_path.read_text())
        except ValueError as exc:
            raise ArtifactSyncError(f"unreadable manifest for {family.name}: {exc}") from exc

    manifests = _run_all(fetch_manifest, list(FAMILIES.values()))

    # --- Pass 2: decide what is actually missing ----------------------------
    pending: list[tuple[ArtifactFamily, str, str, int]] = []
    reused = 0
    for family, manifest in manifests:
        for entry in manifest.files:
            destination = root / family.directory / entry.name
            if destination.is_file() and _sha256(destination) == entry.sha256:
                reused += 1
                continue
            pending.append((family, entry.name, entry.sha256, entry.size_bytes))

    # --- Pass 3: download everything missing, in parallel -------------------
    # Serially, one slow transfer stalls the whole startup: in production the
    # 45.7 MB ALS factors took 60 s while the 181 MB content matrix took 3 s
    # on the same cold start — a connection problem, not a size one. Six
    # concurrent transfers mean a single slow one no longer sets the floor for
    # how long a visitor waits for the first request after a scale-to-zero.
    def fetch_file(item: tuple[ArtifactFamily, str, str, int]) -> None:
        family, name, sha256, _size = item
        _download(
            resolved,
            bucket,
            _object_key(prefix, family.directory, name),
            root / family.directory / name,
            expected_sha256=sha256,
        )

    _run_all(fetch_file, pending)
    downloaded = len(pending)
    total_bytes = sum(size for _, _, _, size in pending)

    for family, manifest in manifests:
        logger.info(
            "artifact_family_synced",
            family=family.name,
            model_version=manifest.model_version,
            files=len(manifest.files),
        )

    logger.info(
        "artifact_sync_complete",
        families=len(FAMILIES),
        downloaded=downloaded,
        reused_from_cache=reused,
        downloaded_mb=round(total_bytes / (1024 * 1024), 1),
        cache_dir=str(root),
    )
    return root
