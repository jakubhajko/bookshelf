"""FastAPI dependencies for recommendation routes."""

from __future__ import annotations

import time

from book_recommender.contracts.provider import RecommendationProvider
from fastapi import FastAPI, Request

from book_app.core.logging import get_logger
from book_app.modules.recommendations.wiring import build_recommendation_provider

logger = get_logger("book_app.recommendations.dependencies")


def get_recommendation_provider(request: Request) -> RecommendationProvider:
    """The process-wide provider, built at startup and cached on ``app.state``.

    Spec §10.13's "load once at startup" is honoured by
    :func:`warm_recommendation_provider` in the ASGI lifespan. This
    remains a lazy fallback rather than an assertion, for the two cases
    where the warm-up legitimately did not run: a worker whose startup
    build failed (a database that was not up yet, say) and an app
    constructed without the lifespan, which is how much of the unit suite
    builds it.

    ``create_app()`` itself still does no database work — that constraint
    is about *constructing* the app, and the lifespan runs after
    construction, at real process startup.
    """
    app_state = request.app.state
    provider: RecommendationProvider | None = getattr(app_state, "recommendation_provider", None)
    if provider is None:
        provider = build_recommendation_provider(app_state.settings, app_state.db_session_factory)
        app_state.recommendation_provider = provider
    return provider


def warm_recommendation_provider(app: FastAPI) -> None:
    """Build the provider during startup so no reader pays for it (risk #121).

    The pipeline loads six artifacts — ~1 s of work that used to land on
    whichever reader made the first request after a deploy, once per
    worker. Startup is where that belongs.

    **A failure here is logged, not raised.** rec-spec §27's whole posture
    is that the recommender degrades rather than takes the application
    down, and refusing to boot the API because an artifact is stale would
    invert that. The lazy path above then retries on first use, which is
    the pre-R9 behaviour — so the worst case of a failed warm-up is exactly
    what every request used to do.
    """
    settings = app.state.settings
    if not settings.recommendation_warmup_on_startup:
        return
    if settings.recommendation_provider == "mock":
        # The mock engine has nothing to preload. Its "artifacts" are a
        # snapshot of 2,000 live book ids, and taking that snapshot earlier
        # only makes it staler — a fixture that inserts books after the app
        # starts would be served from a pool that predates them, which is
        # exactly what the integration suite caught when this ran for every
        # provider. Risk #121 is about artifact loading; `mock` loads none.
        return

    started = time.perf_counter()
    try:
        app.state.recommendation_provider = build_recommendation_provider(
            settings, app.state.db_session_factory
        )
    except Exception as exc:  # noqa: BLE001 - startup must not depend on this
        logger.warning(
            "recommendation_provider_warmup_failed",
            provider=settings.recommendation_provider,
            error=type(exc).__name__,
        )
        return
    logger.info(
        "recommendation_provider_warmed",
        provider=settings.recommendation_provider,
        elapsed_ms=round((time.perf_counter() - started) * 1000.0, 1),
    )
