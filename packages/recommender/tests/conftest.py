"""Shared fixtures for recommender contract tests."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest

from book_recommender.contracts.context import HomeContext, SurfaceContext, UserContext
from book_recommender.contracts.engine import RecommendationEngineRequest
from book_recommender.contracts.provider import RecommendationRequest

DEFAULT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _user_context(user_id: UUID = DEFAULT_USER_ID) -> UserContext:
    """An empty-but-valid context. ``profile_version`` is required (see
    ``UserContext``) — the literal here stands in for what the application's
    context builder computes; these engine/provider tests only care that a
    context is well-formed, never what its fingerprint is."""
    return UserContext(
        user_id=user_id,
        ratings=(),
        saved_book_ids=frozenset(),
        shelf_ids=(),
        not_interested_book_ids=frozenset(),
        recent_interactions=(),
        shelf_summaries=(),
        profile_version="test-profile-v1",
    )


@pytest.fixture
def make_engine_request() -> Callable[..., RecommendationEngineRequest]:
    def _make(
        *,
        surface: SurfaceContext | None = None,
        requested_count: int = 10,
        hard_exclusions: frozenset[int] = frozenset(),
        session_exclusions: frozenset[int] = frozenset(),
        user_context: UserContext | None = None,
        request_id: UUID | None = None,
        catalog_version: str = "test-catalog-v1",
    ) -> RecommendationEngineRequest:
        return RecommendationEngineRequest(
            request_id=request_id or uuid4(),
            user_context=user_context or _user_context(),
            surface_context=surface or HomeContext(),
            requested_count=requested_count,
            hard_exclusions=hard_exclusions,
            session_exclusions=session_exclusions,
            catalog_version=catalog_version,
        )

    return _make


@pytest.fixture
def make_provider_request() -> Callable[..., RecommendationRequest]:
    def _make(
        *,
        surface: SurfaceContext | None = None,
        requested_count: int = 10,
        hard_exclusions: frozenset[int] = frozenset(),
        session_exclusions: frozenset[int] = frozenset(),
        user_context: UserContext | None = None,
        request_id: UUID | None = None,
        catalog_version: str = "test-catalog-v1",
    ) -> RecommendationRequest:
        return RecommendationRequest(
            request_id=request_id or uuid4(),
            user_context=user_context or _user_context(),
            surface_context=surface or HomeContext(),
            requested_count=requested_count,
            hard_exclusions=hard_exclusions,
            session_exclusions=session_exclusions,
            catalog_version=catalog_version,
        )

    return _make
