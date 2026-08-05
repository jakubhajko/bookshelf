"""Shelf integration tests against real PostgreSQL (spec §13.3): CRUD,
membership, ownership, and collage data (spec §9.3, §5.4).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

USERNAME = "shelf_owner"
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


def test_shelves_require_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/shelves")
    assert response.status_code == 401


def test_shelf_list_is_empty_for_a_new_user(client: TestClient) -> None:
    _register_and_login(client)
    response = client.get("/api/v1/shelves")
    assert response.status_code == 200
    assert response.json() == []


def test_get_owned_shelf_returns_its_detail(client: TestClient) -> None:
    csrf = _register_and_login(client)
    created = client.post(
        "/api/v1/shelves",
        json={"name": "Detail Check", "description": "desc"},
        headers={"X-CSRF-Token": csrf},
    ).json()

    response = client.get(f"/api/v1/shelves/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_create_and_list_shelves(client: TestClient) -> None:
    csrf = _register_and_login(client)

    create_response = client.post(
        "/api/v1/shelves",
        json={"name": "Summer Reading", "description": "Beach books"},
        headers={"X-CSRF-Token": csrf},
    )
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["name"] == "Summer Reading"
    assert body["description"] == "Beach books"
    assert body["book_count"] == 0
    assert body["cover_object_keys"] == []

    list_response = client.get("/api/v1/shelves")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
    assert list_response.json()[0]["id"] == body["id"]


def test_empty_shelf_name_is_rejected(client: TestClient) -> None:
    csrf = _register_and_login(client)
    response = client.post(
        "/api/v1/shelves", json={"name": "   "}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SHELF_NAME_INVALID"


def test_shelf_names_are_unique_per_user_after_case_and_unicode_folding(
    client: TestClient,
) -> None:
    csrf = _register_and_login(client)
    first = client.post(
        "/api/v1/shelves", json={"name": "Café Reads"}, headers={"X-CSRF-Token": csrf}
    )
    assert first.status_code == 201

    duplicate = client.post(
        "/api/v1/shelves", json={"name": "CAFÉ READS"}, headers={"X-CSRF-Token": csrf}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "SHELF_NAME_TAKEN"


def test_two_users_can_each_have_a_shelf_with_the_same_name(client: TestClient) -> None:
    csrf_a = _register_and_login(client, username="reader_a")
    response_a = client.post(
        "/api/v1/shelves", json={"name": "Favorites"}, headers={"X-CSRF-Token": csrf_a}
    )
    assert response_a.status_code == 201

    csrf_b = _register_and_login(client, username="reader_b")
    response_b = client.post(
        "/api/v1/shelves", json={"name": "Favorites"}, headers={"X-CSRF-Token": csrf_b}
    )
    assert response_b.status_code == 201


def test_rename_shelf_and_partial_update_semantics(client: TestClient) -> None:
    csrf = _register_and_login(client)
    shelf = client.post(
        "/api/v1/shelves",
        json={"name": "Original Name", "description": "Original description"},
        headers={"X-CSRF-Token": csrf},
    ).json()

    rename_only = client.patch(
        f"/api/v1/shelves/{shelf['id']}",
        json={"name": "New Name"},
        headers={"X-CSRF-Token": csrf},
    )
    assert rename_only.status_code == 200
    assert rename_only.json()["name"] == "New Name"
    # description absent from the request body -> untouched (PATCH semantics).
    assert rename_only.json()["description"] == "Original description"

    clear_description = client.patch(
        f"/api/v1/shelves/{shelf['id']}",
        json={"description": None},
        headers={"X-CSRF-Token": csrf},
    )
    assert clear_description.status_code == 200
    assert clear_description.json()["name"] == "New Name"
    assert clear_description.json()["description"] is None


def test_renaming_shelf_to_an_existing_name_is_rejected(client: TestClient) -> None:
    csrf = _register_and_login(client)
    client.post(
        "/api/v1/shelves", json={"name": "Alpha"}, headers={"X-CSRF-Token": csrf}
    )
    beta = client.post(
        "/api/v1/shelves", json={"name": "Beta"}, headers={"X-CSRF-Token": csrf}
    ).json()

    response = client.patch(
        f"/api/v1/shelves/{beta['id']}",
        json={"name": "Alpha"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SHELF_NAME_TAKEN"


def test_delete_shelf_preserves_ratings_and_other_shelves(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    """Spec §5.4: "Deleting a shelf deletes current memberships but leaves
    ratings, Not Interested states, other shelves, books, and historical
    events intact."."""
    book_id = insert_book()
    csrf = _register_and_login(client)
    client.put(
        f"/api/v1/books/{book_id}/rating",
        json={"rating": 4.0},
        headers={"X-CSRF-Token": csrf},
    )
    keep = client.post(
        "/api/v1/shelves", json={"name": "Keep"}, headers={"X-CSRF-Token": csrf}
    ).json()
    doomed = client.post(
        "/api/v1/shelves", json={"name": "Doomed"}, headers={"X-CSRF-Token": csrf}
    ).json()
    client.put(
        f"/api/v1/books/{book_id}/shelves/{doomed['id']}",
        headers={"X-CSRF-Token": csrf},
    )

    delete_response = client.delete(
        f"/api/v1/shelves/{doomed['id']}", headers={"X-CSRF-Token": csrf}
    )
    assert delete_response.status_code == 204

    assert client.get("/api/v1/shelves").json() == [keep]
    detail = client.get(f"/api/v1/books/{book_id}").json()
    assert detail["user_state"]["rating"] == 4.0
    assert detail["user_state"]["shelf_ids"] == []

    with test_engine.connect() as conn:
        membership_count = conn.execute(
            text("SELECT count(*) FROM shelf_books WHERE shelf_id = :id"),
            {"id": doomed["id"]},
        ).scalar_one()
    assert membership_count == 0


def test_another_users_shelf_is_404_not_403(client: TestClient) -> None:
    """Spec §6.6: ownership violations read identically to nonexistence, so
    a 404 never confirms "it exists but isn't yours"."""
    csrf_a = _register_and_login(client, username="owner")
    shelf = client.post(
        "/api/v1/shelves", json={"name": "Private"}, headers={"X-CSRF-Token": csrf_a}
    ).json()

    csrf_b = _register_and_login(client, username="intruder")
    response = client.get(f"/api/v1/shelves/{shelf['id']}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SHELF_NOT_FOUND"

    patch_response = client.patch(
        f"/api/v1/shelves/{shelf['id']}",
        json={"name": "Hijacked"},
        headers={"X-CSRF-Token": csrf_b},
    )
    assert patch_response.status_code == 404

    delete_response = client.delete(
        f"/api/v1/shelves/{shelf['id']}", headers={"X-CSRF-Token": csrf_b}
    )
    assert delete_response.status_code == 404


def test_unknown_shelf_id_is_404(client: TestClient) -> None:
    _register_and_login(client)
    response = client.get("/api/v1/shelves/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SHELF_NOT_FOUND"


def test_add_and_remove_book_from_shelf_is_idempotent(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)
    shelf = client.post(
        "/api/v1/shelves", json={"name": "Reading"}, headers={"X-CSRF-Token": csrf}
    ).json()

    first_add = client.put(
        f"/api/v1/shelves/{shelf['id']}/books/{book_id}", headers={"X-CSRF-Token": csrf}
    )
    assert first_add.status_code == 204
    second_add = client.put(
        f"/api/v1/shelves/{shelf['id']}/books/{book_id}", headers={"X-CSRF-Token": csrf}
    )
    assert second_add.status_code == 204

    books_response = client.get(f"/api/v1/shelves/{shelf['id']}/books")
    assert books_response.status_code == 200
    assert len(books_response.json()["items"]) == 1

    first_remove = client.delete(
        f"/api/v1/shelves/{shelf['id']}/books/{book_id}", headers={"X-CSRF-Token": csrf}
    )
    assert first_remove.status_code == 204
    second_remove = client.delete(
        f"/api/v1/shelves/{shelf['id']}/books/{book_id}", headers={"X-CSRF-Token": csrf}
    )
    assert second_remove.status_code == 204

    assert client.get(f"/api/v1/shelves/{shelf['id']}/books").json()["items"] == []


def test_shelf_list_includes_collage_cover_data(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    csrf = _register_and_login(client)
    shelf = client.post(
        "/api/v1/shelves", json={"name": "Covers"}, headers={"X-CSRF-Token": csrf}
    ).json()

    book_with_cover = insert_book(
        title="Has Cover", work_id="work-cover", cover_object_key="covers/has-cover.jpg"
    )
    book_without_cover = insert_book(title="No Cover", work_id="work-no-cover")
    for book_id in (book_with_cover, book_without_cover):
        client.put(
            f"/api/v1/shelves/{shelf['id']}/books/{book_id}",
            headers={"X-CSRF-Token": csrf},
        )

    listing = client.get("/api/v1/shelves").json()
    assert listing[0]["book_count"] == 2
    assert listing[0]["cover_object_keys"] == ["covers/has-cover.jpg"]


def test_shelf_list_collage_covers_are_capped(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    """Spec §9.3: "enough cover data for a collage without N+1 frontend
    requests" — bounded, not the whole shelf, so a large shelf's response
    stays small."""
    csrf = _register_and_login(client)
    shelf = client.post(
        "/api/v1/shelves", json={"name": "Big Shelf"}, headers={"X-CSRF-Token": csrf}
    ).json()

    for i in range(5):
        book_id = insert_book(
            title=f"Cover {i}",
            work_id=f"work-cap-{i}",
            cover_object_key=f"covers/cap-{i}.jpg",
        )
        client.put(
            f"/api/v1/shelves/{shelf['id']}/books/{book_id}",
            headers={"X-CSRF-Token": csrf},
        )

    listing = client.get("/api/v1/shelves").json()
    assert listing[0]["book_count"] == 5
    assert len(listing[0]["cover_object_keys"]) == 4


def test_shelf_books_pagination_cursor_advances(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    csrf = _register_and_login(client)
    shelf = client.post(
        "/api/v1/shelves", json={"name": "Big Shelf"}, headers={"X-CSRF-Token": csrf}
    ).json()

    for i in range(3):
        book_id = insert_book(title=f"Book {i}", work_id=f"work-{i}")
        client.put(
            f"/api/v1/shelves/{shelf['id']}/books/{book_id}",
            headers={"X-CSRF-Token": csrf},
        )

    first_page = client.get(f"/api/v1/shelves/{shelf['id']}/books?limit=2").json()
    assert len(first_page["items"]) == 2
    assert first_page["next_cursor"] is not None

    second_page = client.get(
        f"/api/v1/shelves/{shelf['id']}/books?limit=2&cursor={first_page['next_cursor']}"
    ).json()
    assert len(second_page["items"]) == 1
    assert second_page["next_cursor"] is None

    first_ids = {item["book_id"] for item in first_page["items"]}
    second_ids = {item["book_id"] for item in second_page["items"]}
    assert first_ids.isdisjoint(second_ids)


def test_adding_unknown_book_to_shelf_is_404(client: TestClient) -> None:
    csrf = _register_and_login(client)
    shelf = client.post(
        "/api/v1/shelves", json={"name": "Reading"}, headers={"X-CSRF-Token": csrf}
    ).json()
    response = client.put(
        f"/api/v1/shelves/{shelf['id']}/books/999999999", headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BOOK_NOT_FOUND"
