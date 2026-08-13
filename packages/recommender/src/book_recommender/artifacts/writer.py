"""Builder-side artifact writing (ADR-0014, rec-spec §8).

The offline builders live in ``apps/api`` (they read PostgreSQL, which this
package may not), but the *format* must have one definition or the writer and
the reader drift. ADR-0014: "Offline build code and runtime serving code read
the same artifacts through the same loaders, so a format change cannot drift
between writer and reader." :func:`write_artifact` is the writer half of
:func:`~book_recommender.artifacts.loader.load_artifact_bundle`.

It also removes a whole class of build bug: the manifest's checksums are
computed *from the files that were actually written*, after they are written,
rather than declared by the builder. A builder cannot claim a checksum it did
not produce.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from book_recommender.artifacts.local_storage import MANIFEST_FILENAME, LocalArtifactStorage
from book_recommender.artifacts.manifest import ArtifactFile, ArtifactManifest, ConfigValue
from book_recommender.artifacts.mapping import MAPPING_FILENAME, ItemMapping
from book_recommender.artifacts.numeric import sha256_file
from book_recommender.config import ArtifactFamily

#: A payload writer receives the resolved path it should write and nothing
#: else — path resolution (and therefore the storage-root escape check) stays
#: with the storage object.
PayloadWriter = Callable[[Path], None]


@dataclass(frozen=True)
class WrittenArtifact:
    artifact_dir: str
    manifest: ArtifactManifest
    #: ``filename -> sha256``, for build reports and determinism tests.
    checksums: dict[str, str]
    #: Files left in the directory that this build did not write — a previous
    #: format's payload, usually. Reported rather than deleted: the loader
    #: reads only what the manifest declares, so a leftover is inert, and a
    #: builder that deletes unrecognized files in a directory it was merely
    #: pointed at is a worse failure than a stale one.
    stale_files: tuple[str, ...] = ()


def write_artifact(
    storage: LocalArtifactStorage,
    family: ArtifactFamily,
    *,
    model_version: str,
    catalog_version: str,
    items: Sequence[tuple[int, str]],
    payloads: Mapping[str, PayloadWriter],
    config: Mapping[str, ConfigValue] | None = None,
    training_transform_version: str | None = None,
    trained_at: datetime | None = None,
    artifact_dir: str | None = None,
) -> WrittenArtifact:
    """Write one artifact directory: mapping, payload files, then manifest.

    ``items`` are ``(book_id, work_id)`` in model-item-index order — the
    order is the contract, since every payload column is positional.

    The manifest is written **last** on purpose. A crash mid-build leaves a
    directory with no manifest, which the loader treats as "no artifact" and
    degrades past; writing it first would leave a manifest describing files
    that do not exist yet, which is a harder failure to reason about.
    """
    directory = artifact_dir if artifact_dir is not None else family.directory

    mapping_path = storage.resolve(directory, MAPPING_FILENAME)
    ItemMapping.build(items).save(mapping_path)

    for filename, write_payload in payloads.items():
        write_payload(storage.resolve(directory, filename))

    files = tuple(
        _describe(storage.resolve(directory, filename))
        for filename in sorted([MAPPING_FILENAME, *payloads])
    )
    manifest = ArtifactManifest(
        model_name=family.name,
        model_version=model_version,
        catalog_version=catalog_version,
        trained_at=trained_at if trained_at is not None else datetime.now(UTC),
        item_count=len(items),
        preprocessing_version=family.preprocessing_version,
        training_transform_version=training_transform_version,
        config=dict(config or {}),
        mapping_file=MAPPING_FILENAME,
        files=files,
    )
    storage.save_manifest(directory, manifest)

    expected = set(artifact_filenames(list(payloads)))
    directory_path = storage.resolve(directory, MANIFEST_FILENAME).parent
    stale = tuple(
        sorted(
            entry.name
            for entry in directory_path.iterdir()
            if entry.is_file() and entry.name not in expected
        )
    )

    return WrittenArtifact(
        artifact_dir=directory,
        manifest=manifest,
        checksums={entry.name: entry.sha256 for entry in files},
        stale_files=stale,
    )


def artifact_filenames(payload_names: Sequence[str]) -> tuple[str, ...]:
    """Every file an artifact directory should contain, manifest included —
    used by build reports and cleanup."""
    return (MANIFEST_FILENAME, MAPPING_FILENAME, *sorted(payload_names))


def _describe(path: Path) -> ArtifactFile:
    return ArtifactFile(name=path.name, sha256=sha256_file(path), size_bytes=path.stat().st_size)
