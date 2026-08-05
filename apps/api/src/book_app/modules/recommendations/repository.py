"""Recommendation persistence: no HTTP concerns, no commits (spec §4.2) —
the caller's service owns the transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from book_app.modules.recommendations.models import (
    ModelVersion,
    RecommendationImpression,
    RecommendationRequest,
    RecommendationResult,
)
from book_app.shared.enums import ModelVersionStatus


def create_request(
    session: Session,
    *,
    request_id: UUID,
    user_id: UUID,
    surface: str,
    shelf_id: UUID | None,
    source_book_id: int | None,
    provider_name: str,
    model_name: str,
    model_version: str,
    catalog_version: str,
    fallback_used: bool,
    context_summary: dict[str, Any],
    expires_at: datetime,
) -> RecommendationRequest:
    """``request_id`` is caller-supplied, not left to the model's default —
    it must match the id the provider was already given (spec §10.6) before
    this row existed, since ``RecommendationBatch.candidates`` are generated
    off the same id (spec §11: the read transaction ends *before* the
    provider is called, so this insert happens strictly after)."""
    request = RecommendationRequest(
        id=request_id,
        user_id=user_id,
        surface=surface,
        shelf_id=shelf_id,
        source_book_id=source_book_id,
        provider_name=provider_name,
        model_name=model_name,
        model_version=model_version,
        catalog_version=catalog_version,
        fallback_used=fallback_used,
        context_summary=context_summary,
        expires_at=expires_at,
    )
    session.add(request)
    session.flush()
    return request


@dataclass(frozen=True)
class ResultRow:
    position: int
    book_id: int
    score: float | None
    candidate_sources: list[str]
    reason_code: str
    reason_context: dict[str, Any]
    diagnostics: dict[str, Any]


def create_results(session: Session, *, request_id: UUID, rows: list[ResultRow]) -> None:
    session.add_all(
        RecommendationResult(
            request_id=request_id,
            position=row.position,
            book_id=row.book_id,
            score=row.score,
            candidate_sources=row.candidate_sources,
            reason_code=row.reason_code,
            reason_context=row.reason_context,
            diagnostics=row.diagnostics,
        )
        for row in rows
    )
    session.flush()


def create_impressions(
    session: Session,
    *,
    request_id: UUID,
    book_ids_and_positions: list[tuple[int, int]],
    page_cursor: str | None,
) -> None:
    session.add_all(
        RecommendationImpression(
            request_id=request_id,
            book_id=book_id,
            rank_position=rank_position,
            page_cursor=page_cursor,
        )
        for book_id, rank_position in book_ids_and_positions
    )
    session.flush()


def get_request(session: Session, request_id: UUID) -> RecommendationRequest | None:
    return session.get(RecommendationRequest, request_id)


def get_results_page(
    session: Session, *, request_id: UUID, start_position: int, limit: int
) -> list[RecommendationResult]:
    stmt = (
        select(RecommendationResult)
        .where(
            RecommendationResult.request_id == request_id,
            RecommendationResult.position >= start_position,
        )
        .order_by(RecommendationResult.position)
        .limit(limit)
    )
    return list(session.execute(stmt).scalars())


def retire_active_versions(session: Session, *, model_name: str) -> None:
    """Called right before activating a freshly-built version, so at most
    one version per model_name is ever ACTIVE at a time."""
    stmt = select(ModelVersion).where(
        ModelVersion.model_name == model_name, ModelVersion.status == ModelVersionStatus.ACTIVE
    )
    for version in session.execute(stmt).scalars():
        version.status = ModelVersionStatus.RETIRED
    session.flush()


def create_model_version(
    session: Session,
    *,
    model_name: str,
    model_version: str,
    catalog_version: str,
    provider_name: str,
    status: ModelVersionStatus,
    manifest: dict[str, Any],
    activated_at: datetime | None,
) -> ModelVersion:
    row = ModelVersion(
        model_name=model_name,
        model_version=model_version,
        catalog_version=catalog_version,
        provider_name=provider_name,
        status=status,
        manifest=manifest,
        activated_at=activated_at,
    )
    session.add(row)
    session.flush()
    return row
