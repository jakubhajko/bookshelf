"""Password hashing, opaque token generation, and JWT access tokens (spec §14).

- Passwords: Argon2id via argon2-cffi (spec §6.3 — the *id* variant
  specifically, set explicitly rather than relied on as a library default).
- Refresh tokens and CSRF tokens: high-entropy random values, hashed with
  SHA-256 for storage/lookup (spec §6.4/§8.2: "store only refresh token
  hashes" / `csrf_token_hash`). A fast deterministic hash is the right tool
  here — unlike passwords, these values are never human-chosen or
  guessable, so the property needed is "not reversible from the stored
  hash," not "resists offline brute force of a small keyspace."
- Access tokens: a focused JWT (spec §3.2) — one algorithm, one secret, two
  claims (user id, session id). No OAuth/OIDC surface.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import Argon2Error, InvalidHashError

from book_app.core.config import Settings

_password_hasher = PasswordHasher(type=Type.ID)


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except Argon2Error:
        # Wrong password (VerifyMismatchError) or any other verification
        # failure — Argon2Error covers all of these.
        return False
    except InvalidHashError:
        # A malformed/corrupt stored hash — not an Argon2Error subclass
        # (it derives from ValueError), so it needs its own branch. Either
        # way, verification didn't succeed; this must never propagate as an
        # unhandled 500 from the login endpoint.
        return False


def generate_opaque_token() -> str:
    """A high-entropy, URL-safe random token (refresh tokens, CSRF tokens)."""
    return secrets.token_urlsafe(32)


def hash_opaque_token(token: str) -> str:
    """Deterministic hash for storage/lookup of opaque tokens — never for passwords."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: UUID
    session_id: UUID


class InvalidAccessTokenError(Exception):
    """A missing, malformed, expired, or forged access token."""


def create_access_token(*, user_id: UUID, session_id: UUID, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> AccessTokenClaims:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidAccessTokenError(str(exc)) from exc

    try:
        return AccessTokenClaims(user_id=UUID(payload["sub"]), session_id=UUID(payload["sid"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidAccessTokenError("malformed access token claims") from exc
