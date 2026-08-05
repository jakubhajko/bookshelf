"""Book detail and preference-state integration tests against real
PostgreSQL (spec §13.3): GET /books/{id}, PUT/DELETE rating,
PUT/DELETE not-interested, PUT shelves (spec §9.2, §5.2-§5.3).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

USERNAME = "book_reader"
PASSWORD = "correct horse battery staple"


def _register_and_login(client: TestClient, username: str = USERNAME) -> str:
    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        },
    )
    assert register_response.status_code == 201, register_response.text
    login_response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert login_response.status_code == 200, login_response.text
    csrf: str = client.cookies["csrf_token"]
    return csrf


def test_book_detail_requires_authentication(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_id = insert_book()
    response = client.get(f"/api/v1/books/{book_id}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_book_detail_for_unknown_book_is_404(client: TestClient) -> None:
    _register_and_login(client)
    response = client.get("/api/v1/books/999999999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BOOK_NOT_FOUND"


def test_book_detail_assembles_catalog_and_neutral_user_state(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    book_id = insert_book(title="The Neutral Book", primary_author_name="Ann Author")
    with test_engine.begin() as conn:
        genre_id = conn.execute(
            text(
                "INSERT INTO genres (name, normalized_name) VALUES ('Fantasy', 'fantasy') "
                "RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO book_genres (book_id, genre_id, position) "
                "VALUES (:book_id, :genre_id, 0)"
            ),
            {"book_id": book_id, "genre_id": genre_id},
        )

    _register_and_login(client)
    response = client.get(f"/api/v1/books/{book_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == book_id
    assert body["title"] == "The Neutral Book"
    assert body["genres"] == ["Fantasy"]
    assert body["user_state"] == {
        "rating": None,
        "not_interested": False,
        "shelf_ids": [],
    }


def test_set_rating_then_get_reflects_it(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)

    put_response = client.put(
        f"/api/v1/books/{book_id}/rating",
        json={"rating": 4.5},
        headers={"X-CSRF-Token": csrf},
    )
    assert put_response.status_code == 200
    assert put_response.json() == {"rating": 4.5, "not_interested": False}

    detail = client.get(f"/api/v1/books/{book_id}")
    assert detail.json()["user_state"]["rating"] == 4.5


def test_rating_must_be_an_exact_half_step(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)

    response = client.put(
        f"/api/v1/books/{book_id}/rating",
        json={"rating": 3.3},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "RATING_INVALID"


def test_rating_without_csrf_header_is_rejected(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_id = insert_book()
    _register_and_login(client)

    response = client.put(f"/api/v1/books/{book_id}/rating", json={"rating": 4.5})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_INVALID"


def test_changing_rating_appends_rating_changed_event(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)

    client.put(
        f"/api/v1/books/{book_id}/rating",
        json={"rating": 3.0},
        headers={"X-CSRF-Token": csrf},
    )
    response = client.put(
        f"/api/v1/books/{book_id}/rating",
        json={"rating": 4.5},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert response.json()["rating"] == 4.5

    with test_engine.connect() as conn:
        event_types = [
            row.event_type
            for row in conn.execute(
                text("SELECT event_type FROM interaction_events ORDER BY id")
            )
        ]
    assert event_types == ["rating_set", "rating_changed"]


def test_remove_rating_returns_to_neutral_and_is_idempotent(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)
    client.put(
        f"/api/v1/books/{book_id}/rating",
        json={"rating": 2.0},
        headers={"X-CSRF-Token": csrf},
    )

    first = client.delete(
        f"/api/v1/books/{book_id}/rating", headers={"X-CSRF-Token": csrf}
    )
    assert first.status_code == 204
    assert client.get(f"/api/v1/books/{book_id}").json()["user_state"]["rating"] is None

    # Removing an already-absent rating is a no-op, not an error (spec §5.3).
    second = client.delete(
        f"/api/v1/books/{book_id}/rating", headers={"X-CSRF-Token": csrf}
    )
    assert second.status_code == 204


def test_setting_rating_clears_not_interested(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)

    client.put(
        f"/api/v1/books/{book_id}/not-interested", headers={"X-CSRF-Token": csrf}
    )
    response = client.put(
        f"/api/v1/books/{book_id}/rating",
        json={"rating": 5.0},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert response.json() == {"rating": 5.0, "not_interested": False}


def test_setting_not_interested_clears_rating(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)

    client.put(
        f"/api/v1/books/{book_id}/rating",
        json={"rating": 1.0},
        headers={"X-CSRF-Token": csrf},
    )
    response = client.put(
        f"/api/v1/books/{book_id}/not-interested", headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 200
    assert response.json() == {"rating": None, "not_interested": True}


def test_rating_and_not_interested_are_never_simultaneously_true(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    """Belt-and-suspenders check on the spec §5.2 invariant: service logic
    prevents it, and the DB CheckConstraint would reject it even if service
    logic had a bug — this only exercises the service path, but confirms the
    end state the constraint also guards."""
    book_id = insert_book()
    csrf = _register_and_login(client)

    client.put(
        f"/api/v1/books/{book_id}/rating",
        json={"rating": 3.5},
        headers={"X-CSRF-Token": csrf},
    )
    client.put(
        f"/api/v1/books/{book_id}/not-interested", headers={"X-CSRF-Token": csrf}
    )

    with test_engine.connect() as conn:
        row = conn.execute(
            text("SELECT rating_value, not_interested FROM user_book_states")
        ).one()
    assert not (row.rating_value is not None and row.not_interested)


def test_remove_not_interested_returns_to_neutral_and_is_idempotent(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)
    client.put(
        f"/api/v1/books/{book_id}/not-interested", headers={"X-CSRF-Token": csrf}
    )

    first = client.delete(
        f"/api/v1/books/{book_id}/not-interested", headers={"X-CSRF-Token": csrf}
    )
    assert first.status_code == 204
    assert (
        client.get(f"/api/v1/books/{book_id}").json()["user_state"]["not_interested"]
        is False
    )

    second = client.delete(
        f"/api/v1/books/{book_id}/not-interested", headers={"X-CSRF-Token": csrf}
    )
    assert second.status_code == 204


def test_not_interested_never_removes_shelves(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    """Spec §12.7: "Not Interested confirms if clearing a rating and never
    removes shelves." / spec §5.3: "A Not Interested book may remain in
    shelves."."""
    book_id = insert_book()
    csrf = _register_and_login(client)

    shelf_response = client.post(
        "/api/v1/shelves", json={"name": "To Read"}, headers={"X-CSRF-Token": csrf}
    )
    shelf_id = shelf_response.json()["id"]
    client.put(
        f"/api/v1/shelves/{shelf_id}/books/{book_id}", headers={"X-CSRF-Token": csrf}
    )

    client.put(
        f"/api/v1/books/{book_id}/not-interested", headers={"X-CSRF-Token": csrf}
    )

    detail = client.get(f"/api/v1/books/{book_id}").json()
    assert detail["user_state"]["not_interested"] is True
    assert detail["user_state"]["shelf_ids"] == [shelf_id]


def test_shelf_sync_replaces_membership_atomically(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)

    shelf_a = client.post(
        "/api/v1/shelves", json={"name": "Shelf A"}, headers={"X-CSRF-Token": csrf}
    ).json()["id"]
    shelf_b = client.post(
        "/api/v1/shelves", json={"name": "Shelf B"}, headers={"X-CSRF-Token": csrf}
    ).json()["id"]

    sync_response = client.put(
        f"/api/v1/books/{book_id}/shelves",
        json={"shelf_ids": [shelf_a, shelf_b]},
        headers={"X-CSRF-Token": csrf},
    )
    assert sync_response.status_code == 200
    assert sorted(sync_response.json()["shelf_ids"]) == sorted([shelf_a, shelf_b])

    replace_response = client.put(
        f"/api/v1/books/{book_id}/shelves",
        json={"shelf_ids": [shelf_b]},
        headers={"X-CSRF-Token": csrf},
    )
    assert replace_response.status_code == 200
    assert replace_response.json()["shelf_ids"] == [shelf_b]


def test_shelf_sync_with_any_foreign_shelf_id_changes_nothing(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    """Spec §6.6/§9.2: ownership is validated for *all* shelf_ids before any
    change is made — a sync that names one shelf the user doesn't own must
    leave existing memberships untouched, not partially apply."""
    book_id = insert_book()
    csrf = _register_and_login(client)
    owned_shelf = client.post(
        "/api/v1/shelves", json={"name": "Mine"}, headers={"X-CSRF-Token": csrf}
    ).json()["id"]
    client.put(
        f"/api/v1/shelves/{owned_shelf}/books/{book_id}", headers={"X-CSRF-Token": csrf}
    )

    other_csrf = _register_and_login(client, username="someone_else")
    foreign_shelf = client.post(
        "/api/v1/shelves", json={"name": "Theirs"}, headers={"X-CSRF-Token": other_csrf}
    ).json()["id"]

    # _register_and_login's register call would 409 for an existing
    # username, so log back in as the original user directly instead —
    # this replaces the client's cookie jar with their session again.
    login_response = client.post(
        "/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD}
    )
    assert login_response.status_code == 200
    csrf = client.cookies["csrf_token"]

    response = client.put(
        f"/api/v1/books/{book_id}/shelves",
        json={"shelf_ids": [owned_shelf, foreign_shelf]},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SHELF_NOT_FOUND"

    detail = client.get(f"/api/v1/books/{book_id}").json()
    assert detail["user_state"]["shelf_ids"] == [owned_shelf]


def test_shelf_sync_to_empty_list_removes_all_memberships(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)
    shelf = client.post(
        "/api/v1/shelves", json={"name": "Temporary"}, headers={"X-CSRF-Token": csrf}
    ).json()
    client.put(
        f"/api/v1/shelves/{shelf['id']}/books/{book_id}", headers={"X-CSRF-Token": csrf}
    )

    response = client.put(
        f"/api/v1/books/{book_id}/shelves",
        json={"shelf_ids": []},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert response.json()["shelf_ids"] == []
    assert (
        client.get(f"/api/v1/books/{book_id}").json()["user_state"]["shelf_ids"] == []
    )


def test_shelf_sync_for_unknown_book_is_404(client: TestClient) -> None:
    csrf = _register_and_login(client)
    response = client.put(
        "/api/v1/books/999999999/shelves",
        json={"shelf_ids": []},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BOOK_NOT_FOUND"
