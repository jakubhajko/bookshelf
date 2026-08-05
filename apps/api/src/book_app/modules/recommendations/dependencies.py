"""FastAPI dependencies for recommendation routes."""

from __future__ import annotations

from book_recommender.contracts.provider import RecommendationProvider
from fastapi import Request

from book_app.modules.recommendations.wiring import build_recommendation_provider


def get_recommendation_provider(request: Request) -> RecommendationProvider:
    """Built once, lazily, on first use — not eagerly in ``create_app()``.

    Spec §10.13 says "load once at startup", but ``main.py`` deliberately
    keeps app construction free of database access (its own docstring:
    tests that have nothing to do with recommendations shouldn't need a
    live database just to build the app). The mock engine's candidate pool
    needs a real query (spec §10.11: it has no DB access of its own, so the
    application must supply real book ids), which would violate that if run
    eagerly. Loading on first request instead is the same "once, cached for
    the process's life" behavior, just triggered a beat later than literal
    process startup — cached on ``app.state`` afterward exactly like
    ``auth_rate_limiter``.
    """
    app_state = request.app.state
    provider: RecommendationProvider | None = getattr(app_state, "recommendation_provider", None)
    if provider is None:
        provider = build_recommendation_provider(app_state.settings, app_state.db_session_factory)
        app_state.recommendation_provider = provider
    return provider
