"""Tests for Settings production-safety validation (spec §14 / §11)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from book_app.core.config import Settings


def test_development_allows_insecure_defaults() -> None:
    settings = Settings(environment="development")
    assert settings.jwt_secret_key == "dev-insecure-change-me-before-deploying"


def test_production_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="jwt_secret_key"):
        Settings(environment="production", cookie_secure=True)


def test_production_rejects_insecure_cookie() -> None:
    with pytest.raises(ValidationError, match="cookie_secure"):
        Settings(
            environment="production",
            jwt_secret_key="a-real-secret",
            cookie_secure=False,
        )


def test_production_rejects_demo_mode() -> None:
    with pytest.raises(ValidationError, match="demo_mode_enabled"):
        Settings(
            environment="production",
            jwt_secret_key="a-real-secret",
            cookie_secure=True,
            demo_mode_enabled=True,
        )


def test_production_accepts_secure_configuration() -> None:
    settings = Settings(
        environment="production",
        jwt_secret_key="a-real-secret",
        cookie_secure=True,
        demo_mode_enabled=False,
    )
    assert settings.environment.value == "production"
