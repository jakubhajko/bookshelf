"""GET /me/ratings integration tests against real PostgreSQL (spec §13.3):
sort modes, rating-range/genre filters, and cursor pagination (spec §9.4).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

USERNAME = "rater"
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


def _rate(client: TestClient, csrf: str, book_id: int, rating: float) -> None:
    response = client.put(
        f"/api/v1/books/{book_id}/rating",
        json={"rating": rating},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text


def test_ratings_feed_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/me/ratings")
    assert response.status_code == 401


def test_ratings_feed_only_includes_rated_books(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    rated = insert_book(title="Rated", work_id="rated")
    not_interested = insert_book(title="Skipped", work_id="skipped")
    neutral = insert_book(title="Neutral", work_id="neutral")
    csrf = _register_and_login(client)

    _rate(client, csrf, rated, 4.0)
    client.put(
        f"/api/v1/books/{not_interested}/not-interested", headers={"X-CSRF-Token": csrf}
    )

    response = client.get("/api/v1/me/ratings")
    assert response.status_code == 200
    book_ids = [item["book_id"] for item in response.json()["items"]]
    assert book_ids == [rated]
    assert neutral not in book_ids


def test_sort_highest_and_lowest(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    low = insert_book(title="Low", work_id="low")
    mid = insert_book(title="Mid", work_id="mid")
    high = insert_book(title="High", work_id="high")
    csrf = _register_and_login(client)
    _rate(client, csrf, low, 1.0)
    _rate(client, csrf, mid, 3.0)
    _rate(client, csrf, high, 5.0)

    highest = client.get("/api/v1/me/ratings?sort=highest").json()["items"]
    assert [item["book_id"] for item in highest] == [high, mid, low]

    lowest = client.get("/api/v1/me/ratings?sort=lowest").json()["items"]
    assert [item["book_id"] for item in lowest] == [low, mid, high]


def test_sort_title_is_alphabetical(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    zeta = insert_book(title="Zeta", work_id="zeta")
    alpha = insert_book(title="Alpha", work_id="alpha")
    mid = insert_book(title="Mid", work_id="mid")
    csrf = _register_and_login(client)
    for book_id in (zeta, alpha, mid):
        _rate(client, csrf, book_id, 3.0)

    response = client.get("/api/v1/me/ratings?sort=title").json()["items"]
    assert [item["book_id"] for item in response] == [alpha, mid, zeta]


def test_sort_author_is_alphabetical(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    zeta = insert_book(title="Book Z", work_id="zw", primary_author_name="Zeta Author")
    alpha = insert_book(
        title="Book A", work_id="aw", primary_author_name="Alpha Author"
    )
    csrf = _register_and_login(client)
    _rate(client, csrf, zeta, 3.0)
    _rate(client, csrf, alpha, 3.0)

    response = client.get("/api/v1/me/ratings?sort=author").json()["items"]
    assert [item["book_id"] for item in response] == [alpha, zeta]


def test_sort_recent_reflects_last_rated_at(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    first = insert_book(title="First", work_id="first")
    second = insert_book(title="Second", work_id="second")
    csrf = _register_and_login(client)
    _rate(client, csrf, first, 3.0)
    _rate(client, csrf, second, 3.0)

    # Force a deterministic ordering: back-date `first`'s updated_at so
    # `second` is unambiguously the more-recent rating regardless of how
    # close together the two PUTs above landed in wall-clock time.
    with test_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE user_book_states SET updated_at = now() - interval '1 day' "
                "WHERE book_id = :book_id"
            ),
            {"book_id": first},
        )

    response = client.get("/api/v1/me/ratings?sort=recent").json()["items"]
    assert [item["book_id"] for item in response] == [second, first]


def test_sort_recent_pagination_round_trips_the_datetime_cursor(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    """The ``recent`` cursor stores ``rated_at`` as an ISO string (JSON has
    no datetime type) and must parse it back before comparing against the
    TIMESTAMPTZ column — regression coverage for a real bug caught during
    Phase 4 development, where that parse step was missing."""
    csrf = _register_and_login(client)
    book_ids = []
    for i in range(3):
        book_id = insert_book(title=f"Book {i}", work_id=f"recent-page-{i}")
        book_ids.append(book_id)
        _rate(client, csrf, book_id, 3.0)

    first_page = client.get("/api/v1/me/ratings?sort=recent&limit=2").json()
    assert len(first_page["items"]) == 2
    assert first_page["next_cursor"] is not None

    second_page = client.get(
        f"/api/v1/me/ratings?sort=recent&limit=2&cursor={first_page['next_cursor']}"
    ).json()
    assert len(second_page["items"]) == 1
    assert second_page["next_cursor"] is None

    all_ids = [item["book_id"] for item in first_page["items"] + second_page["items"]]
    assert sorted(all_ids) == sorted(book_ids)


def test_rating_range_filter(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    low = insert_book(title="Low", work_id="low")
    high = insert_book(title="High", work_id="high")
    csrf = _register_and_login(client)
    _rate(client, csrf, low, 1.5)
    _rate(client, csrf, high, 4.5)

    response = client.get("/api/v1/me/ratings?min_rating=4.0&max_rating=5.0").json()[
        "items"
    ]
    assert [item["book_id"] for item in response] == [high]


def test_genre_filter(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    fantasy_book = insert_book(title="Fantasy Book", work_id="fantasy-book")
    scifi_book = insert_book(title="Scifi Book", work_id="scifi-book")
    with test_engine.begin() as conn:
        fantasy_genre_id = conn.execute(
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
            {"book_id": fantasy_book, "genre_id": fantasy_genre_id},
        )
    csrf = _register_and_login(client)
    _rate(client, csrf, fantasy_book, 3.0)
    _rate(client, csrf, scifi_book, 3.0)

    response = client.get("/api/v1/me/ratings?genre=Fantasy").json()["items"]
    assert [item["book_id"] for item in response] == [fantasy_book]


def test_ratings_feed_pagination_cursor_advances(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    csrf = _register_and_login(client)
    book_ids = []
    for i in range(3):
        book_id = insert_book(title=f"Book {i}", work_id=f"paginated-{i}")
        book_ids.append(book_id)
        _rate(client, csrf, book_id, 3.0)

    first_page = client.get("/api/v1/me/ratings?sort=title&limit=2").json()
    assert len(first_page["items"]) == 2
    assert first_page["next_cursor"] is not None

    second_page = client.get(
        f"/api/v1/me/ratings?sort=title&limit=2&cursor={first_page['next_cursor']}"
    ).json()
    assert len(second_page["items"]) == 1
    assert second_page["next_cursor"] is None

    all_ids = [item["book_id"] for item in first_page["items"] + second_page["items"]]
    assert sorted(all_ids) == sorted(book_ids)


def test_invalid_cursor_is_rejected(client: TestClient) -> None:
    _register_and_login(client)
    response = client.get("/api/v1/me/ratings?cursor=not-valid-base64!!")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CURSOR"
