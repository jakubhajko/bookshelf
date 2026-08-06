"""Tests for general (non-auth) request limits (spec §14): a per-IP rate
limit across every route, and a request-body size cap. Each test builds
its own `TestClient` (rather than the shared `client` fixture) since each
needs a different, deliberately tiny limit to exercise without sending
hundreds of requests.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from book_app.core.config import Settings
from book_app.main import create_app


def test_general_rate_limit_returns_429_once_exceeded() -> None:
    settings = Settings(
        environment="test", general_rate_limit_max_requests=2, general_rate_limit_window_seconds=60
    )
    with TestClient(create_app(settings=settings)) as client:
        # /auth/me isn't exempt (only /health/* is) and needs no body/auth
        # setup to reach the general-limit check — an unauthenticated 401
        # still counts as "a request" for this limit's purposes.
        assert client.get("/api/v1/auth/me").status_code == 401
        assert client.get("/api/v1/auth/me").status_code == 401

        limited = client.get("/api/v1/auth/me")
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "RATE_LIMITED"


def test_health_checks_are_exempt_from_the_general_rate_limit() -> None:
    settings = Settings(
        environment="test", general_rate_limit_max_requests=1, general_rate_limit_window_seconds=60
    )
    with TestClient(create_app(settings=settings)) as client:
        # Exhaust the tiny budget on a non-exempt route first...
        assert client.get("/api/v1/auth/me").status_code == 401
        assert client.get("/api/v1/auth/me").status_code == 429
        # ...but health/live keeps working regardless — it must never be
        # the thing that makes infra health checks start failing.
        for _ in range(5):
            assert client.get("/api/v1/health/live").status_code == 200


def test_oversized_request_body_returns_413() -> None:
    settings = Settings(environment="test", max_request_body_bytes=10)
    with TestClient(create_app(settings=settings)) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "someone",
                "password": "correct horse battery staple",
                "password_confirmation": "correct horse battery staple",
            },
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_request_within_the_body_size_limit_is_not_rejected_for_size() -> None:
    settings = Settings(environment="test", max_request_body_bytes=1_000_000)
    with TestClient(create_app(settings=settings)) as client:
        response = client.get("/api/v1/health/live")
        assert response.status_code == 200
