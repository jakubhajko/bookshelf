"""Tests for security response headers (spec §14)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from book_app.core.config import Settings
from book_app.main import create_app


def test_core_security_headers_are_present(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_hsts_is_absent_when_cookies_are_not_secure(client: TestClient) -> None:
    # Default test Settings has cookie_secure=False (plain HTTP local dev) —
    # HSTS over HTTP is meaningless and browsers ignore it, but asserting
    # its absence keeps the "gated on cookie_secure" behavior honest.
    response = client.get("/api/v1/health/live")
    assert "Strict-Transport-Security" not in response.headers


def test_hsts_is_present_when_cookies_are_secure() -> None:
    settings = Settings(environment="test", cookie_secure=True)
    with TestClient(create_app(settings=settings)) as secure_client:
        response = secure_client.get("/api/v1/health/live")
        assert (
            response.headers["Strict-Transport-Security"] == "max-age=63072000; includeSubDomains"
        )
