"""Startup warm-up of the recommendation provider (risk #121).

The pipeline loads six artifacts. Before R9 that ~1 s landed on whichever
reader made the first request after a deploy, once per worker; now the ASGI
lifespan pays it. Two properties matter and neither is visible from a route:
the build has to *happen* at startup, and a build that fails must not stop
the application from serving.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from book_app.core.config import Settings
from book_app.main import create_app
from book_app.modules.recommendations import dependencies


@pytest.fixture
def warm_settings() -> Settings:
    # `pipeline` rather than the `mock` default: the warm-up deliberately
    # skips mock, which has no artifacts to preload.
    return Settings(
        environment="test",
        recommendation_warmup_on_startup=True,
        recommendation_provider="pipeline",
    )


def _app_with_stub(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, build: Any
) -> tuple[FastAPI, list[str]]:
    calls: list[str] = []

    def _build(*args: object, **kwargs: object) -> object:
        calls.append("built")
        return build()

    monkeypatch.setattr(dependencies, "build_recommendation_provider", _build)
    return create_app(settings=settings), calls


def test_the_provider_is_built_during_startup(
    monkeypatch: pytest.MonkeyPatch, warm_settings: Settings
) -> None:
    sentinel = object()
    app, calls = _app_with_stub(monkeypatch, warm_settings, lambda: sentinel)

    with TestClient(app):
        assert calls == ["built"], "the lifespan must build it, not the first request"
        assert app.state.recommendation_provider is sentinel


def test_a_failed_warmup_does_not_stop_the_application(
    monkeypatch: pytest.MonkeyPatch, warm_settings: Settings
) -> None:
    """rec-spec §27: the recommender degrades, it does not take the API down.

    A database that is not up yet is the realistic case, and refusing to
    boot would turn a recommendation outage into a total one.
    """

    def _explode() -> object:
        raise RuntimeError("artifacts are on fire")

    app, calls = _app_with_stub(monkeypatch, warm_settings, _explode)

    with TestClient(app) as client:
        assert calls == ["built"]
        assert getattr(app.state, "recommendation_provider", None) is None
        # The rest of the application is unaffected.
        assert client.get("/api/v1/health/live").status_code == 200


def test_warmup_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The unit suite builds the app without a database on purpose."""
    app, calls = _app_with_stub(
        monkeypatch,
        Settings(
            environment="test",
            recommendation_warmup_on_startup=False,
            recommendation_provider="pipeline",
        ),
        lambda: object(),
    )

    with TestClient(app):
        assert calls == []


def test_the_mock_provider_is_not_warmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Its candidate pool is a live database snapshot, not an artifact.

    Taking it at startup only makes it staler than taking it on first use,
    and it would be captured before any test fixture inserted a book.
    """
    app, calls = _app_with_stub(
        monkeypatch,
        Settings(
            environment="test",
            recommendation_warmup_on_startup=True,
            recommendation_provider="mock",
        ),
        lambda: object(),
    )

    with TestClient(app):
        assert calls == []
