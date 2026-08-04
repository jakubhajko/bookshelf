"""Tests for password hashing, opaque tokens, and JWT access tokens (spec §14)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from book_app.core.config import Settings
from book_app.core.security import (
    AccessTokenClaims,
    InvalidAccessTokenError,
    create_access_token,
    decode_access_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    verify_password,
)


def test_hash_password_is_not_the_plaintext() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$argon2id$")


def test_verify_password_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_verify_password_rejects_garbage_hash_without_raising() -> None:
    assert verify_password("anything", "not-a-real-argon2-hash") is False


def test_generate_opaque_token_is_high_entropy_and_unique() -> None:
    tokens = {generate_opaque_token() for _ in range(200)}
    assert len(tokens) == 200
    assert all(len(t) >= 32 for t in tokens)


def test_hash_opaque_token_is_deterministic() -> None:
    token = generate_opaque_token()
    assert hash_opaque_token(token) == hash_opaque_token(token)


def test_hash_opaque_token_differs_for_different_tokens() -> None:
    assert hash_opaque_token(generate_opaque_token()) != hash_opaque_token(generate_opaque_token())


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="test")


def test_access_token_round_trip(settings: Settings) -> None:
    user_id, session_id = uuid.uuid4(), uuid.uuid4()
    token = create_access_token(user_id=user_id, session_id=session_id, settings=settings)
    claims = decode_access_token(token, settings)
    assert claims == AccessTokenClaims(user_id=user_id, session_id=session_id)


def test_garbage_token_is_rejected(settings: Settings) -> None:
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token("not.a.jwt", settings)


def test_token_signed_with_different_secret_is_rejected(settings: Settings) -> None:
    other_settings = Settings(
        environment="test", jwt_secret_key="a-totally-different-secret-value-here"
    )
    token = create_access_token(
        user_id=uuid.uuid4(), session_id=uuid.uuid4(), settings=other_settings
    )
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, settings)


def test_expired_token_is_rejected(settings: Settings) -> None:
    payload = {
        "sub": str(uuid.uuid4()),
        "sid": str(uuid.uuid4()),
        "iat": datetime.now(UTC) - timedelta(hours=1),
        "exp": datetime.now(UTC) - timedelta(minutes=1),
    }
    expired_token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(expired_token, settings)


def test_token_missing_claims_is_rejected(settings: Settings) -> None:
    token = jwt.encode(
        {"sub": "not-even-a-uuid"}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token, settings)
