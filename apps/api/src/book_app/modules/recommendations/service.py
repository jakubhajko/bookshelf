"""Recommendation use cases (spec §11's ten-step workflow). Owns
transactions — repositories never commit (spec §4.2). No recommendation
algorithms here (spec §20) — this orchestrates product eligibility (spec
§5.5) and the typed provider boundary (spec §10), nothing scores or ranks
anything itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from book_recommender.contracts.context import (
    HomeContext,
    ShelfContext,
    SimilarBooksContext,
    UserContext,
)
from book_recommender.contracts.provider import RecommendationProvider
from book_recommender.contracts.provider import RecommendationRequest as ProviderRequest
from book_recommender.exceptions import ProviderError
from sqlalchemy.orm import Session

from book_app.modules.books import repository as books_repository
from book_app.modules.books.exceptions import BookNotFoundError
from book_app.modules.books.repository import CatalogCardRow
from book_app.modules.recommendations import context_builder, eligibility
from book_app.modules.recommendations import repository as recommendations_repository
from book_app.modules.recommendations.exceptions import (
    RecommendationCursorInvalidError,
    RecommendationUnavailableError,
)
from book_app.modules.recommendations.models import (
    RecommendationRequest as RecommendationRequestRow,
)
from book_app.modules.recommendations.repository import ResultRow
from book_app.modules.recommendations.surfaces import Surface
from book_app.modules.shelves import repository as shelves_repository
from book_app.modules.shelves.exceptions import ShelfNotFoundError
from book_app.shared.pagination import InvalidCursorError, decode_cursor, encode_cursor

DEFAULT_PAGE_SIZE = 20
BATCH_SIZE = 60  # "a larger ordered batch than one page needs" (spec §9.9)
BATCH_TTL_MINUTES = 30


@dataclass(frozen=True)
class RecommendationItemView:
    book: CatalogCardRow
    rank: int
    score: float | None
    reason_code: str


@dataclass(frozen=True)
class RecommendationPage:
    request_id: UUID
    surface: str
    model_name: str
    model_version: str
    fallback_used: bool
    items: list[RecommendationItemView]
    next_cursor: str | None


async def get_home_recommendations(
    session: Session,
    *,
    user_id: UUID,
    limit: int,
    cursor_str: str | None,
    exclude_ids: frozenset[int],
    provider: RecommendationProvider,
) -> RecommendationPage:
    if cursor_str is not None:
        return _read_cursor_page(
            session,
            cursor_str=cursor_str,
            user_id=user_id,
            expected_surface=Surface.HOME,
            limit=limit,
        )

    user_context = context_builder.build_user_context(session, user_id=user_id)
    hard_exclusions = eligibility.home_exclusions(user_context)
    return await _generate_first_page(
        session,
        user_id=user_id,
        surface=Surface.HOME,
        surface_context=HomeContext(),
        shelf_id=None,
        source_book_id=None,
        user_context=user_context,
        hard_exclusions=hard_exclusions,
        session_exclusions=exclude_ids,
        limit=limit,
        provider=provider,
    )


async def get_shelf_recommendations(
    session: Session,
    *,
    user_id: UUID,
    shelf_id: UUID,
    limit: int,
    cursor_str: str | None,
    exclude_ids: frozenset[int],
    provider: RecommendationProvider,
) -> RecommendationPage:
    if cursor_str is not None:
        return _read_cursor_page(
            session,
            cursor_str=cursor_str,
            user_id=user_id,
            expected_surface=Surface.SHELF,
            limit=limit,
        )

    shelf = shelves_repository.get_owned(session, user_id=user_id, shelf_id=shelf_id)
    if shelf is None:
        raise ShelfNotFoundError()

    shelf_book_ids = shelves_repository.get_book_ids_in_shelf(session, shelf_id=shelf_id)
    user_context = context_builder.build_user_context(session, user_id=user_id)
    hard_exclusions = eligibility.shelf_exclusions(
        user_context, shelf_book_ids=frozenset(shelf_book_ids)
    )
    surface_context = ShelfContext(
        shelf_id=shelf.id,
        shelf_name=shelf.name,
        shelf_description=shelf.description,
        shelf_book_ids=frozenset(shelf_book_ids),
    )
    return await _generate_first_page(
        session,
        user_id=user_id,
        surface=Surface.SHELF,
        surface_context=surface_context,
        shelf_id=shelf.id,
        source_book_id=None,
        user_context=user_context,
        hard_exclusions=hard_exclusions,
        session_exclusions=exclude_ids,
        limit=limit,
        provider=provider,
    )


async def get_similar_recommendations(
    session: Session,
    *,
    user_id: UUID,
    source_book_id: int,
    limit: int,
    cursor_str: str | None,
    exclude_ids: frozenset[int],
    provider: RecommendationProvider,
) -> RecommendationPage:
    if cursor_str is not None:
        return _read_cursor_page(
            session,
            cursor_str=cursor_str,
            user_id=user_id,
            expected_surface=Surface.SIMILAR,
            limit=limit,
        )

    if books_repository.get_by_id(session, source_book_id) is None:
        raise BookNotFoundError()

    user_context = context_builder.build_user_context(session, user_id=user_id)
    hard_exclusions = eligibility.similar_exclusions(user_context, source_book_id=source_book_id)
    return await _generate_first_page(
        session,
        user_id=user_id,
        surface=Surface.SIMILAR,
        surface_context=SimilarBooksContext(source_book_id=source_book_id),
        shelf_id=None,
        source_book_id=source_book_id,
        user_context=user_context,
        hard_exclusions=hard_exclusions,
        session_exclusions=exclude_ids,
        limit=limit,
        provider=provider,
    )


async def _generate_first_page(
    session: Session,
    *,
    user_id: UUID,
    surface: Surface,
    surface_context: HomeContext | ShelfContext | SimilarBooksContext,
    shelf_id: UUID | None,
    source_book_id: int | None,
    user_context: UserContext,
    hard_exclusions: frozenset[int],
    session_exclusions: frozenset[int],
    limit: int,
    provider: RecommendationProvider,
) -> RecommendationPage:
    request_id = uuid4()
    catalog_version = books_repository.get_catalog_version(session)

    provider_request = ProviderRequest(
        request_id=request_id,
        user_context=user_context,
        surface_context=surface_context,
        requested_count=BATCH_SIZE,
        hard_exclusions=hard_exclusions,
        session_exclusions=session_exclusions,
        catalog_version=catalog_version,
    )

    # spec §11 step 3: end the read transaction before calling the provider
    # — nothing above this line mutated anything, so this just closes the
    # read cleanly (CLAUDE.md: "no open DB transaction during recommendation
    # inference").
    session.commit()

    try:
        batch = await provider.recommend(provider_request)
    except ProviderError as exc:
        raise RecommendationUnavailableError() from exc

    # spec §10.8: validate defensively regardless of what the provider
    # promised — get_catalog_cards only returns currently-active, existent
    # books, so anything else is silently dropped here.
    candidate_book_ids = [c.book_id for c in batch.candidates]
    cards = books_repository.get_catalog_cards(session, candidate_book_ids)
    valid_candidates = [c for c in batch.candidates if c.book_id in cards]

    expires_at = datetime.now(UTC) + timedelta(minutes=BATCH_TTL_MINUTES)
    context_summary = {
        "rated_count": len(user_context.ratings),
        "shelf_count": len(user_context.shelf_ids),
        "not_interested_count": len(user_context.not_interested_book_ids),
        "saved_book_count": len(user_context.saved_book_ids),
    }
    recommendations_repository.create_request(
        session,
        request_id=request_id,
        user_id=user_id,
        surface=surface,
        shelf_id=shelf_id,
        source_book_id=source_book_id,
        provider_name=batch.provider_name,
        model_name=batch.model_name,
        model_version=batch.model_version,
        catalog_version=batch.catalog_version,
        fallback_used=batch.fallback_used,
        context_summary=context_summary,
        expires_at=expires_at,
    )
    recommendations_repository.create_results(
        session,
        request_id=request_id,
        rows=[
            ResultRow(
                position=position,
                book_id=c.book_id,
                score=c.score,
                candidate_sources=list(c.candidate_sources),
                reason_code=c.reason_code,
                reason_context=c.reason_context,
                diagnostics=c.diagnostics,
            )
            for position, c in enumerate(valid_candidates)
        ],
    )

    page_candidates = valid_candidates[:limit]
    has_more = len(valid_candidates) > limit
    next_cursor = (
        encode_cursor({"request_id": str(request_id), "position": limit}) if has_more else None
    )

    if page_candidates:
        recommendations_repository.create_impressions(
            session,
            request_id=request_id,
            book_ids_and_positions=[(c.book_id, i) for i, c in enumerate(page_candidates)],
            page_cursor=None,  # first page has no incoming cursor
        )
    session.commit()

    items = [
        RecommendationItemView(
            book=cards[c.book_id], rank=i, score=c.score, reason_code=c.reason_code
        )
        for i, c in enumerate(page_candidates)
    ]
    return RecommendationPage(
        request_id=request_id,
        surface=surface,
        model_name=batch.model_name,
        model_version=batch.model_version,
        fallback_used=batch.fallback_used,
        items=items,
        next_cursor=next_cursor,
    )


def _read_cursor_page(
    session: Session,
    *,
    cursor_str: str,
    user_id: UUID,
    expected_surface: Surface,
    limit: int,
) -> RecommendationPage:
    """Spec §9.9: "Subsequent pages read the same batch" — no provider call,
    no eligibility recomputation, just further positions from what the
    first request already persisted."""
    try:
        payload = decode_cursor(cursor_str)
        request_id = UUID(str(payload["request_id"]))
        start_position = int(payload["position"])
    except (InvalidCursorError, KeyError, ValueError, TypeError) as exc:
        raise RecommendationCursorInvalidError() from exc

    request: RecommendationRequestRow | None = recommendations_repository.get_request(
        session, request_id
    )
    now = datetime.now(UTC)
    if (
        request is None
        or request.user_id != user_id
        or request.surface != expected_surface
        or request.expires_at < now
    ):
        # Same error whether the batch never existed, belongs to someone
        # else, or expired — a more specific error would leak which case
        # applies (spec §6.6's existence-hiding principle).
        raise RecommendationCursorInvalidError()

    rows = recommendations_repository.get_results_page(
        session, request_id=request_id, start_position=start_position, limit=limit + 1
    )
    page_rows = rows[:limit]
    has_more = len(rows) > limit

    book_ids = [row.book_id for row in page_rows]
    cards = books_repository.get_catalog_cards(session, book_ids)
    items = [
        RecommendationItemView(
            book=cards[row.book_id], rank=row.position, score=row.score, reason_code=row.reason_code
        )
        for row in page_rows
        if row.book_id in cards
    ]

    next_cursor = None
    if has_more and page_rows:
        next_position = page_rows[-1].position + 1
        next_cursor = encode_cursor({"request_id": str(request_id), "position": next_position})

    if items:
        recommendations_repository.create_impressions(
            session,
            request_id=request_id,
            book_ids_and_positions=[(item.book.book_id, item.rank) for item in items],
            page_cursor=cursor_str,
        )
    session.commit()

    return RecommendationPage(
        request_id=request_id,
        surface=request.surface,
        model_name=request.model_name,
        model_version=request.model_version,
        fallback_used=request.fallback_used,
        items=items,
        next_cursor=next_cursor,
    )
