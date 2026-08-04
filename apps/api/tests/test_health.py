"""Tests for GET /api/v1/health/live and /api/v1/health/ready (spec §9.7)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from book_app.core import health as health_module


def test_live_always_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_live_has_no_database_dependency(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(engine: Any) -> None:
        raise AssertionError("live must not touch the database")

    monkeypatch.setattr(health_module, "check_database_ready", _boom)
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200


def test_ready_ok_when_database_reachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health_module, "check_database_ready", lambda engine: None)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_ready_returns_error_envelope_when_database_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(engine: Any) -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(health_module, "check_database_ready", _raise)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert body["error"]["request_id"]


def test_response_carries_request_id_header(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")
    assert response.headers.get("X-Request-ID")


def test_request_id_is_echoed_back(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"X-Request-ID": "test-fixed-id"})
    assert response.headers.get("X-Request-ID") == "test-fixed-id"
