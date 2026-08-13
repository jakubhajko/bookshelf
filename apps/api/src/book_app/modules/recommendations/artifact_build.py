"""Shared offline artifact-build support (ADR-0014, rec-spec §8).

Three things every artifact builder needs and none of them should reinvent:
a model-version stamp, the ``model_versions`` bookkeeping row, and a report
shape the CLIs can print and the tests can assert on.

Lives beside ``artifact_paths`` in the recommendations module rather than in
``cli/`` because it is domain logic about artifacts, and because
``cli/build_*.py`` should stay thin enough to read as "query, transform,
write, report".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from book_recommender.artifacts import WrittenArtifact
from book_recommender.config import ArtifactFamily
from sqlalchemy.orm import Session

from book_app.modules.recommendations import repository as recommendations_repository
from book_app.shared.enums import ModelVersionStatus

MODEL_VERSION_FORMAT = "%Y%m%dT%H%M%SZ"


def new_model_version(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime(MODEL_VERSION_FORMAT)


@dataclass(frozen=True)
class ArtifactBuildReport:
    """What a build did, in a shape that prints as a CLI summary and asserts
    as a test."""

    model_name: str
    model_version: str
    catalog_version: str
    item_count: int
    dry_run: bool
    #: ``filename -> sha256``. Empty on a dry run. This is what makes
    #: "deterministic artifact build given same input/config" (rec-spec §28)
    #: a testable claim rather than an aspiration — the manifest's own
    #: ``trained_at`` differs between runs by design, the payloads must not.
    checksums: dict[str, str] = field(default_factory=dict)
    #: Free-form per-family counters for the build log (edges exported,
    #: rows dropped, and why).
    stats: dict[str, int | str] = field(default_factory=dict)
    #: A few representative rows, printed so a human running the build can
    #: see it produced something plausible rather than only a row count.
    preview: list[dict[str, Any]] = field(default_factory=list)

    #: Files left over from a previous build of this family, reported by the
    #: writer. Never deleted automatically — see ``WrittenArtifact``.
    stale_files: tuple[str, ...] = ()

    def summary_line(self) -> str:
        prefix = "[DRY RUN] " if self.dry_run else ""
        return (
            f"{prefix}{self.model_name}: {self.item_count} items, "
            f"model_version={self.model_version}, catalog_version={self.catalog_version}"
        )

    def warning_lines(self) -> list[str]:
        if not self.stale_files:
            return []
        return [
            f"  warning: {len(self.stale_files)} file(s) in the artifact directory were not "
            f"written by this build and are safe to delete: {', '.join(self.stale_files)}"
        ]


def register_model_version(
    session: Session,
    family: ArtifactFamily,
    written: WrittenArtifact,
    *,
    provider_name: str = "in_process",
) -> None:
    """Retire the previous active version of this family and record the new
    one. The caller owns the transaction — repositories never commit."""
    recommendations_repository.retire_active_versions(session, model_name=family.name)
    recommendations_repository.create_model_version(
        session,
        model_name=family.name,
        model_version=written.manifest.model_version,
        catalog_version=written.manifest.catalog_version,
        provider_name=provider_name,
        status=ModelVersionStatus.ACTIVE,
        manifest=written.manifest.model_dump(mode="json"),
        activated_at=datetime.now(UTC),
    )
