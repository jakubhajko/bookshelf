"""Recommendation integration tests against real PostgreSQL (spec §13.3):
all three surfaces, cursor pagination, eligibility exclusion, and
authorization (spec §9.5, §5.5).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from book_app.modules.recommendations.dependencies import get_recommendation_provider
from book_recommender.contracts.provider import (
    RecommendationBatch,
    RecommendationRequest,
)
from book_recommender.exceptions import ProviderError
from fastapi import FastAPI
from fastapi.testclient import TestClient

USERNAME = "recs_user"
PASSWORD = "correct horse battery staple"


class _AlwaysFailingProvider:
    """Test double for the 503-mapping test below — the fallback chain
    itself is already covered by packages/recommender's own provider tests;
    this only confirms the apps/api boundary maps a fully-exhausted
    provider failure to the right HTTP status."""

    async def recommend(self, request: RecommendationRequest) -> RecommendationBatch:
        raise ProviderError("simulated total failure")


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


def _insert_books(
    insert_book: Callable[..., int], count: int, prefix: str = "book"
) -> list[int]:
    return [
        insert_book(title=f"{prefix} {i}", work_id=f"{prefix}-{i}")
        for i in range(count)
    ]


def test_home_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/recommendations/home")
    assert response.status_code == 401


def test_home_returns_enriched_books(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_ids = _insert_books(insert_book, 10)
    _register_and_login(client)

    response = client.get("/api/v1/recommendations/home")
    assert response.status_code == 200
    body = response.json()
    assert body["surface"] == "home"
    assert body["model_version"]
    assert "request_id" in body
    assert 0 < len(body["items"]) <= 10
    for item in body["items"]:
        assert item["book_id"] in book_ids
        assert item["title"]
        assert item["reason_text"]
        assert item["reason_code"]


def test_home_with_no_books_in_catalog_returns_an_empty_page(
    client: TestClient,
) -> None:
    _register_and_login(client)
    response = client.get("/api/v1/recommendations/home")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["next_cursor"] is None


def test_home_excludes_rated_not_interested_and_shelved_books(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    all_books = _insert_books(insert_book, 6)
    rated, not_interested, shelved, *_eligible = all_books
    csrf = _register_and_login(client)

    client.put(
        f"/api/v1/books/{rated}/rating",
        json={"rating": 4.0},
        headers={"X-CSRF-Token": csrf},
    )
    client.put(
        f"/api/v1/books/{not_interested}/not-interested", headers={"X-CSRF-Token": csrf}
    )
    shelf = client.post(
        "/api/v1/shelves", json={"name": "Shelf"}, headers={"X-CSRF-Token": csrf}
    ).json()
    client.put(
        f"/api/v1/shelves/{shelf['id']}/books/{shelved}", headers={"X-CSRF-Token": csrf}
    )

    response = client.get("/api/v1/recommendations/home?limit=60")
    returned_ids = {item["book_id"] for item in response.json()["items"]}
    assert rated not in returned_ids
    assert not_interested not in returned_ids
    assert shelved not in returned_ids


def test_home_respects_the_exclude_param(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_ids = _insert_books(insert_book, 5)
    _register_and_login(client)
    exclude_id = book_ids[0]

    response = client.get(f"/api/v1/recommendations/home?limit=60&exclude={exclude_id}")
    assert response.status_code == 200
    returned_ids = {item["book_id"] for item in response.json()["items"]}
    assert exclude_id not in returned_ids


def test_home_pagination_cursor_returns_disjoint_pages(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    _insert_books(insert_book, 10)
    _register_and_login(client)

    first = client.get("/api/v1/recommendations/home?limit=4").json()
    assert len(first["items"]) == 4
    assert first["next_cursor"] is not None

    second = client.get(
        f"/api/v1/recommendations/home?limit=4&cursor={first['next_cursor']}"
    ).json()
    assert len(second["items"]) > 0
    assert second["request_id"] == first["request_id"]

    first_ids = {item["book_id"] for item in first["items"]}
    second_ids = {item["book_id"] for item in second["items"]}
    assert first_ids.isdisjoint(second_ids)


def test_invalid_cursor_is_rejected(client: TestClient) -> None:
    _register_and_login(client)
    response = client.get("/api/v1/recommendations/home?cursor=not-a-real-cursor!!")
    assert response.status_code == 400


def test_cursor_from_another_user_is_rejected(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    _insert_books(insert_book, 10)
    _register_and_login(client, username="owner_a")
    first = client.get("/api/v1/recommendations/home?limit=2").json()
    cursor = first["next_cursor"]
    assert cursor is not None

    _register_and_login(client, username="owner_b")
    response = client.get(f"/api/v1/recommendations/home?limit=2&cursor={cursor}")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "RECOMMENDATION_CURSOR_INVALID"


def test_shelf_recommendations_ownership_is_hidden_as_not_found(
    client: TestClient,
) -> None:
    csrf_a = _register_and_login(client, username="owner_a")
    shelf = client.post(
        "/api/v1/shelves", json={"name": "Mine"}, headers={"X-CSRF-Token": csrf_a}
    ).json()

    _register_and_login(client, username="intruder")
    response = client.get(f"/api/v1/recommendations/shelves/{shelf['id']}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SHELF_NOT_FOUND"


def test_shelf_recommendations_for_unknown_shelf_is_404(client: TestClient) -> None:
    _register_and_login(client)
    response = client.get(
        "/api/v1/recommendations/shelves/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SHELF_NOT_FOUND"


def test_shelf_recommendations_excludes_this_shelf_but_not_other_shelves(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_ids = _insert_books(insert_book, 8)
    in_this_shelf, in_other_shelf, *_rest = book_ids
    csrf = _register_and_login(client)

    shelf_a = client.post(
        "/api/v1/shelves", json={"name": "A"}, headers={"X-CSRF-Token": csrf}
    ).json()
    shelf_b = client.post(
        "/api/v1/shelves", json={"name": "B"}, headers={"X-CSRF-Token": csrf}
    ).json()
    client.put(
        f"/api/v1/shelves/{shelf_a['id']}/books/{in_this_shelf}",
        headers={"X-CSRF-Token": csrf},
    )
    client.put(
        f"/api/v1/shelves/{shelf_b['id']}/books/{in_other_shelf}",
        headers={"X-CSRF-Token": csrf},
    )

    response = client.get(f"/api/v1/recommendations/shelves/{shelf_a['id']}?limit=60")
    assert response.status_code == 200
    returned_ids = {item["book_id"] for item in response.json()["items"]}
    assert in_this_shelf not in returned_ids
    assert in_other_shelf in returned_ids


def test_similar_recommendations_for_unknown_book_is_404(client: TestClient) -> None:
    _register_and_login(client)
    response = client.get("/api/v1/recommendations/books/999999999/similar")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BOOK_NOT_FOUND"


def test_similar_recommendations_excludes_the_source_book(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_ids = _insert_books(insert_book, 6)
    source_book_id = book_ids[0]
    _register_and_login(client)

    response = client.get(
        f"/api/v1/recommendations/books/{source_book_id}/similar?limit=60"
    )
    assert response.status_code == 200
    returned_ids = {item["book_id"] for item in response.json()["items"]}
    assert source_book_id not in returned_ids


def test_similar_recommendations_may_include_saved_books(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_ids = _insert_books(insert_book, 6)
    source_book_id, saved_book_id, *_rest = book_ids
    csrf = _register_and_login(client)
    shelf = client.post(
        "/api/v1/shelves", json={"name": "Saved"}, headers={"X-CSRF-Token": csrf}
    ).json()
    client.put(
        f"/api/v1/shelves/{shelf['id']}/books/{saved_book_id}",
        headers={"X-CSRF-Token": csrf},
    )

    response = client.get(
        f"/api/v1/recommendations/books/{source_book_id}/similar?limit=60"
    )
    assert response.status_code == 200
    returned_ids = {item["book_id"] for item in response.json()["items"]}
    # Spec §5.5: "Saved books may appear" in similar-books results.
    assert saved_book_id in returned_ids


def test_shelf_recommendations_pagination_cursor_returns_disjoint_pages(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    _insert_books(insert_book, 10)
    csrf = _register_and_login(client)
    shelf = client.post(
        "/api/v1/shelves", json={"name": "Discover"}, headers={"X-CSRF-Token": csrf}
    ).json()

    first = client.get(f"/api/v1/recommendations/shelves/{shelf['id']}?limit=4").json()
    assert len(first["items"]) == 4
    assert first["next_cursor"] is not None

    second = client.get(
        f"/api/v1/recommendations/shelves/{shelf['id']}?limit=4&cursor={first['next_cursor']}"
    ).json()
    assert len(second["items"]) > 0
    assert second["surface"] == "shelf"

    first_ids = {item["book_id"] for item in first["items"]}
    second_ids = {item["book_id"] for item in second["items"]}
    assert first_ids.isdisjoint(second_ids)


def test_similar_recommendations_pagination_cursor_returns_disjoint_pages(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_ids = _insert_books(insert_book, 10)
    source_book_id = book_ids[0]
    _register_and_login(client)

    first = client.get(
        f"/api/v1/recommendations/books/{source_book_id}/similar?limit=4"
    ).json()
    assert len(first["items"]) == 4
    assert first["next_cursor"] is not None

    second = client.get(
        f"/api/v1/recommendations/books/{source_book_id}/similar"
        f"?limit=4&cursor={first['next_cursor']}"
    ).json()
    assert len(second["items"]) > 0
    assert second["surface"] == "similar"

    first_ids = {item["book_id"] for item in first["items"]}
    second_ids = {item["book_id"] for item in second["items"]}
    assert first_ids.isdisjoint(second_ids)
    assert source_book_id not in second_ids


def test_exclude_param_silently_skips_malformed_ids(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_ids = _insert_books(insert_book, 5)
    _register_and_login(client)

    response = client.get(
        f"/api/v1/recommendations/home?limit=60&exclude=abc,{book_ids[0]},,xyz"
    )
    assert response.status_code == 200
    returned_ids = {item["book_id"] for item in response.json()["items"]}
    assert book_ids[0] not in returned_ids
    assert book_ids[1] in returned_ids


def test_provider_failure_maps_to_503(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    """Exercises the ProviderError -> RecommendationUnavailableError mapping
    (spec §10.10's terminal "failure -> 503")."""
    _insert_books(insert_book, 5)
    _register_and_login(client)

    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_recommendation_provider] = _AlwaysFailingProvider
    try:
        response = client.get("/api/v1/recommendations/home")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "RECOMMENDATION_UNAVAILABLE"
    finally:
        app.dependency_overrides.pop(get_recommendation_provider, None)
