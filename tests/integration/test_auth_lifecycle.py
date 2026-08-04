"""Auth lifecycle integration tests against real PostgreSQL (spec §13.3:
"auth lifecycle and persistence").
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from book_app.core.config import Settings
from fastapi.testclient import TestClient
from httpx2 import (
    Response,
)  # apps/api uses httpx2, not httpx - see apps/api/pyproject.toml
from sqlalchemy import Engine, text

USERNAME = "integration_user"
PASSWORD = "correct horse battery staple"


def _register(
    client: TestClient, username: str = USERNAME, password: str = PASSWORD
) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": password,
            "password_confirmation": password,
        },
    )
    assert response.status_code == 201, response.text


def _login(
    client: TestClient, username: str = USERNAME, password: str = PASSWORD
) -> Response:
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


def test_full_register_login_me_refresh_logout_flow(client: TestClient) -> None:
    _register(client)

    login_response = _login(client)
    assert login_response.status_code == 200
    assert login_response.json()["username"] == USERNAME
    assert "access_token" in client.cookies
    assert "refresh_token" in client.cookies
    assert "csrf_token" in client.cookies

    me_response = client.get("/api/v1/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["username"] == USERNAME

    old_csrf = client.cookies["csrf_token"]
    refresh_response = client.post("/api/v1/auth/refresh")
    assert refresh_response.status_code == 200
    assert client.cookies["csrf_token"] != old_csrf  # rotated on refresh (spec §6.5)

    logout_response = client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": client.cookies["csrf_token"]}
    )
    assert logout_response.status_code == 204

    # TestClient behaves like a real browser: the Set-Cookie deletions from
    # logout's response removed the cookies from its jar entirely, so this
    # request carries none at all — NOT_AUTHENTICATED, not SESSION_INVALID.
    me_after_logout = client.get("/api/v1/auth/me")
    assert me_after_logout.status_code == 401
    assert me_after_logout.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_replayed_access_token_is_rejected_immediately_after_logout(
    client: TestClient,
) -> None:
    """A *captured* access token (e.g. stolen before logout, or held by a
    second tab whose own cookie clear never ran) must stop working the
    moment the session is revoked — not linger for its ~15-minute natural
    lifetime. This is the property fixed by making get_current_user check
    session validity, not just JWT signature/expiry (see dependencies.py).
    """
    _register(client)
    _login(client)
    captured_access_token = client.cookies["access_token"]
    csrf = client.cookies["csrf_token"]

    logout_response = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert logout_response.status_code == 204

    # logout cleared the client's cookie jar; set the captured (now-revoked)
    # token back directly to simulate a replay, instead of the deprecated
    # per-request `cookies=` override.
    client.cookies.set("access_token", captured_access_token)
    replay_response = client.get("/api/v1/auth/me")
    assert replay_response.status_code == 401
    assert replay_response.json()["error"]["code"] == "SESSION_INVALID"


def test_logout_without_csrf_header_is_rejected(client: TestClient) -> None:
    _register(client)
    _login(client)

    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_INVALID"


def test_logout_with_wrong_csrf_header_is_rejected(client: TestClient) -> None:
    _register(client)
    _login(client)

    response = client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": "not-the-real-token"}
    )
    assert response.status_code == 403


def test_duplicate_username_registration_is_rejected(client: TestClient) -> None:
    _register(client)
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": USERNAME,
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USERNAME_TAKEN"


def test_reserved_username_registration_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "admin",
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USERNAME_RESERVED"


def test_login_with_wrong_password_is_rejected(client: TestClient) -> None:
    _register(client)
    response = _login(client, password="totally the wrong password")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_with_unknown_username_gives_the_same_generic_error(
    client: TestClient,
) -> None:
    response = _login(client, username="nobody_registered_this")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_refresh_and_csrf_tokens_are_stored_only_as_hashes(
    client: TestClient, test_engine: Engine
) -> None:
    _register(client)
    _login(client)

    raw_refresh_token = client.cookies["refresh_token"]
    raw_csrf_token = client.cookies["csrf_token"]

    with test_engine.connect() as conn:
        row = conn.execute(
            text("SELECT refresh_token_hash, csrf_token_hash FROM auth_sessions")
        ).one()

    assert row.refresh_token_hash != raw_refresh_token
    assert row.csrf_token_hash != raw_csrf_token
    assert raw_refresh_token not in row.refresh_token_hash
    assert raw_csrf_token not in row.csrf_token_hash


def test_password_is_stored_only_as_an_argon2_hash(
    client: TestClient, test_engine: Engine
) -> None:
    _register(client)
    with test_engine.connect() as conn:
        password_hash = conn.execute(
            text("SELECT password_hash FROM users")
        ).scalar_one()
    assert password_hash != PASSWORD
    assert password_hash.startswith("$argon2id$")


def test_session_expiry_matches_configured_refresh_lifetime(
    client: TestClient, test_engine: Engine, test_settings: Settings
) -> None:
    _register(client)
    _login(client)

    with test_engine.connect() as conn:
        expires_at = conn.execute(
            text("SELECT expires_at FROM auth_sessions")
        ).scalar_one()

    expected = datetime.now(UTC) + timedelta(days=test_settings.refresh_token_days)
    actual = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
    assert abs((actual - expected).total_seconds()) < 60


def test_disabled_account_cannot_log_in(
    client: TestClient, test_engine: Engine
) -> None:
    _register(client)
    with test_engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET account_status = 'DISABLED' WHERE username = :u"),
            {"u": USERNAME},
        )

    response = _login(client)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_DISABLED"


def test_change_password_requires_correct_current_password(client: TestClient) -> None:
    _register(client)
    _login(client)
    csrf = client.cookies["csrf_token"]

    response = client.post(
        "/api/v1/auth/change-password",
        headers={"X-CSRF-Token": csrf},
        json={
            "current_password": "wrong-current-password",
            "new_password": "some new password value",
            "new_password_confirmation": "some new password value",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "PASSWORD_INCORRECT"


def test_change_password_then_old_password_no_longer_works(client: TestClient) -> None:
    _register(client)
    _login(client)
    csrf = client.cookies["csrf_token"]
    new_password = "brand new correct horse battery"

    response = client.post(
        "/api/v1/auth/change-password",
        headers={"X-CSRF-Token": csrf},
        json={
            "current_password": PASSWORD,
            "new_password": new_password,
            "new_password_confirmation": new_password,
        },
    )
    assert response.status_code == 204

    assert _login(client, password=PASSWORD).status_code == 401
    assert _login(client, password=new_password).status_code == 200
