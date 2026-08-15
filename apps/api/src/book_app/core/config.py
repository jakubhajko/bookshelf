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

_INSECURE_DEV_SECRET = "dev-insecure-change-me-before-deploying"  # noqa: S105 - placeholder
# 39 bytes: above PyJWT's 32-byte recommended HS256 key length, so the local
# dev default doesn't trigger InsecureKeyLengthWarning on every request —
# still just as "obviously fake," still just as rejected in production by
# the validator below.


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

    # --- JWT / sessions (Phase 3) ---
    jwt_secret_key: str = _INSECURE_DEV_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30

    # --- Cookies (Phase 3) ---
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None

    # --- CORS (wired in Phase 1 middleware) ---
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- CSRF (Phase 3) ---
    # No separate CSRF secret: spec §8.2 stores `csrf_token_hash` on
    # auth_sessions, which only makes sense for a random-token-hashed-at-rest
    # design (an HMAC-derived token wouldn't need storing at all) — see
    # docs/implementation/plan.md §6. Phase 1 provisioned an unused
    # `csrf_secret_key` field anticipating an HMAC design; removed here now
    # that CSRF is actually implemented and doesn't need one.

    # --- Auth rate limiting (Phase 3) --- pluggable per spec §14; the
    # in-process default is documented as local-only, see shared/rate_limit.py.
    auth_rate_limit_max_attempts: int = 10
    auth_rate_limit_window_seconds: float = 300.0

    # --- General request limits (Phase 9) --- spec §14's "request limits",
    # distinct from the auth-specific boundary above: a coarse per-IP
    # backstop across every route, not a business rule. Generous by design
    # — a single masonry page load can easily fire 20+ concurrent cover
    # requests, and a shared/NAT IP aggregates many real visitors — this is
    # meant to catch abusive/broken clients, not normal enthusiastic
    # browsing. See core/request_limits.py.
    general_rate_limit_max_requests: int = 600
    general_rate_limit_window_seconds: float = 60.0
    max_request_body_bytes: int = 1_000_000

    # --- Cover storage (Phase 2) ---
    cover_storage_backend: Literal["local", "s3"] = "local"
    cover_storage_local_path: Path = Path("data/processed/covers")
    cover_storage_s3_bucket: str | None = None

    # --- Artifact storage (behavior lands in Phase 5) ---
    artifact_storage_backend: Literal["local", "s3"] = "local"
    artifact_storage_local_path: Path = Path("data/artifacts")
    artifact_storage_s3_bucket: str | None = None

    # --- Recommendation provider selection ---
    #: ``pipeline`` is the real funnel (R8). It replaced the
    #: ``future_pipeline`` placeholder, which raised on every call and
    #: existed only to reserve the seam. ``mock`` and ``popularity`` remain
    #: for development and as the standalone fallback respectively.
    recommendation_provider: Literal["mock", "popularity", "pipeline"] = "mock"

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
