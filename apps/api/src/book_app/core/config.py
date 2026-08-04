"""Typed environment configuration (APP_SPECIFICATION.md §11).

Every category the spec requires — database, JWT/session, cookie, CORS,
CSRF, cover storage, artifact storage, provider selection, logs, demo
toggle — is declared here from Phase 1 even though most fields aren't
consumed by application behavior until a later phase. This keeps the typed
config surface stable so later phases wire behavior to existing fields
instead of growing the settings model piecemeal. Fields not yet used are
annotated with the phase that will consume them.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEV_SECRET = "dev-insecure-change-me"  # noqa: S105 - placeholder, not a real credential


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"

    # --- Database ---
    database_url: str = "postgresql+psycopg://book_app:book_app@localhost:5434/book_app"
    database_pool_size: int = 5
    database_pool_max_overflow: int = 10

    # --- JWT / sessions (behavior lands in Phase 3) ---
    jwt_secret_key: str = _INSECURE_DEV_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30

    # --- Cookies (behavior lands in Phase 3) ---
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None

    # --- CORS (wired in Phase 1 middleware) ---
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- CSRF (behavior lands in Phase 3) ---
    csrf_secret_key: str = _INSECURE_DEV_SECRET

    # --- Cover storage (behavior lands in Phase 2) ---
    cover_storage_backend: Literal["local", "s3"] = "local"
    cover_storage_local_path: Path = Path("data/processed/covers")
    cover_storage_s3_bucket: str | None = None

    # --- Artifact storage (behavior lands in Phase 5) ---
    artifact_storage_backend: Literal["local", "s3"] = "local"
    artifact_storage_local_path: Path = Path("data/artifacts")
    artifact_storage_s3_bucket: str | None = None

    # --- Recommendation provider selection (behavior lands in Phase 5) ---
    recommendation_provider: Literal["mock", "popularity", "future_pipeline"] = "mock"

    # --- Demo toggle (behavior lands in Phase 4/9); must never be true in production ---
    demo_mode_enabled: bool = False

    @model_validator(mode="after")
    def _reject_insecure_production_defaults(self) -> Self:
        """Fail startup rather than run production on placeholder secrets (spec §14)."""
        if self.environment is not Environment.PRODUCTION:
            return self

        insecure: list[str] = []
        if self.jwt_secret_key == _INSECURE_DEV_SECRET:
            insecure.append("jwt_secret_key")
        if self.csrf_secret_key == _INSECURE_DEV_SECRET:
            insecure.append("csrf_secret_key")
        if not self.cookie_secure:
            insecure.append("cookie_secure")
        if self.demo_mode_enabled:
            insecure.append("demo_mode_enabled")

        if insecure:
            raise ValueError(
                "Refusing to start with insecure defaults in production: " + ", ".join(insecure)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings instance for FastAPI dependency injection."""
    return Settings()
