"""GET /search/books integration tests against real PostgreSQL (spec §13.3):
the seven-tier ranking (spec §9.6), that Not-Interested/rated/shelved books
stay visible with accurate state, and cursor pagination. ADR-0012.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

USERNAME = "searcher"
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


def test_search_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/search/books?q=dune")
    assert response.status_code == 401


def test_exact_title_match_ranks_first(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    sequel = insert_book(
        title="Dune Messiah", work_id="dune-messiah", ratings_count=100_000
    )
    exact = insert_book(title="Dune", work_id="dune", ratings_count=10)
    _register_and_login(client)

    response = client.get("/api/v1/search/books?q=Dune")
    assert response.status_code == 200
    book_ids = [item["book_id"] for item in response.json()["items"]]
    # Exact title beats a far-more-popular prefix/fuzzy match — tier order
    # dominates the popularity tiebreak, not the other way around.
    assert book_ids[0] == exact
    assert sequel in book_ids


def test_title_prefix_ranks_above_fuzzy_match(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    prefix = insert_book(title="Harry Potter and the Chamber of Secrets", work_id="hp2")
    fuzzy = insert_book(
        title="J. K. Rowling: The Wizard Behind Harry Potter", work_id="hp-bio"
    )
    _register_and_login(client)

    response = client.get("/api/v1/search/books?q=Harry Potter")
    book_ids = [item["book_id"] for item in response.json()["items"]]
    assert book_ids.index(prefix) < book_ids.index(fuzzy)


def test_author_tier_matches_on_author_name_alone(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book = insert_book(
        title="Children of Dune", primary_author_name="Frank Herbert", work_id="cod"
    )
    unrelated = insert_book(
        title="Unrelated Title", primary_author_name="Someone Else", work_id="u1"
    )
    _register_and_login(client)

    response = client.get("/api/v1/search/books?q=Frank Herbert")
    book_ids = [item["book_id"] for item in response.json()["items"]]
    assert book in book_ids
    assert unrelated not in book_ids


def test_description_full_text_match(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    matching = insert_book(
        title="Some Unrelated Title",
        work_id="fts-1",
        description="A thrilling tale of dragons and ancient castles.",
    )
    non_matching = insert_book(
        title="Another Title", work_id="fts-2", description="Nothing relevant."
    )
    _register_and_login(client)

    response = client.get("/api/v1/search/books?q=dragons castles")
    book_ids = [item["book_id"] for item in response.json()["items"]]
    assert matching in book_ids
    assert non_matching not in book_ids


def test_popularity_tiebreaks_within_the_same_tier(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    less_popular = insert_book(
        title="Zeta Chronicles", work_id="zeta-1", ratings_count=5
    )
    more_popular = insert_book(
        title="Zeta Legends", work_id="zeta-2", ratings_count=5_000
    )
    _register_and_login(client)

    response = client.get("/api/v1/search/books?q=Zeta")
    book_ids = [item["book_id"] for item in response.json()["items"]]
    assert book_ids.index(more_popular) < book_ids.index(less_popular)


def test_no_match_returns_an_empty_page(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    insert_book(title="Something Else Entirely", work_id="irrelevant")
    _register_and_login(client)

    response = client.get("/api/v1/search/books?q=zzznomatchzzz")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["next_cursor"] is None


def test_inactive_books_are_excluded(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    hidden = insert_book(
        title="Hidden Exact Match", work_id="hidden-1", catalog_status="HIDDEN"
    )
    _register_and_login(client)

    response = client.get("/api/v1/search/books?q=Hidden Exact Match")
    book_ids = [item["book_id"] for item in response.json()["items"]]
    assert hidden not in book_ids


def test_keeps_rated_not_interested_and_shelved_books_visible_with_accurate_state(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    rated = insert_book(title="Alpha Rated Book", work_id="alpha-rated")
    skipped = insert_book(title="Alpha Skipped Book", work_id="alpha-skipped")
    shelved = insert_book(title="Alpha Shelved Book", work_id="alpha-shelved")
    csrf = _register_and_login(client)

    client.put(
        f"/api/v1/books/{rated}/rating",
        json={"rating": 4.5},
        headers={"X-CSRF-Token": csrf},
    )
    client.put(
        f"/api/v1/books/{skipped}/not-interested", headers={"X-CSRF-Token": csrf}
    )
    shelf_id = client.post(
        "/api/v1/shelves", json={"name": "Alpha Shelf"}, headers={"X-CSRF-Token": csrf}
    ).json()["id"]
    client.put(
        f"/api/v1/shelves/{shelf_id}/books/{shelved}", headers={"X-CSRF-Token": csrf}
    )

    response = client.get("/api/v1/search/books?q=Alpha")
    items_by_id = {item["book_id"]: item for item in response.json()["items"]}

    # Spec §9.6: "search keeps prior user states visible" — none excluded.
    assert set(items_by_id) == {rated, skipped, shelved}
    assert items_by_id[rated]["user_state"]["rating"] == 4.5
    assert items_by_id[rated]["user_state"]["not_interested"] is False
    assert items_by_id[skipped]["user_state"]["not_interested"] is True
    assert items_by_id[skipped]["user_state"]["rating"] is None
    assert items_by_id[shelved]["user_state"]["shelf_ids"] == [shelf_id]


def test_cursor_pagination_has_no_duplicates_or_gaps(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_ids = [
        insert_book(title=f"Beta Book {i}", work_id=f"beta-{i}", ratings_count=i)
        for i in range(12)
    ]
    _register_and_login(client)

    seen: list[int] = []
    cursor: str | None = None
    for _ in range(20):
        url = f"/api/v1/search/books?q=Beta&limit=5{f'&cursor={cursor}' if cursor else ''}"
        response = client.get(url)
        assert response.status_code == 200
        body = response.json()
        seen.extend(item["book_id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == len(book_ids)
    assert set(seen) == set(book_ids)
