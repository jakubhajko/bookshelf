"""Recommender Phase R1: raw interaction instrumentation and attribution
against real PostgreSQL (rec-spec §4, ADR-0015).

These tests are about what ends up in `interaction_events`,
`shelf_books.source_surface`, `search_queries` and
`recommendation_impressions` — the evidence every later recommender phase
trains on. Assertions are on persisted rows, not just HTTP status codes:
a 204 proves the request was accepted, not that the right provenance was
recorded.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

USERNAME = "attribution_user"
PASSWORD = "correct horse battery staple"

SESSION_ID = "11111111-2222-3333-4444-555555555555"


def _register_and_login(client: TestClient, username: str = USERNAME) -> str:
    register = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        },
    )
    assert register.status_code == 201, register.text
    login = client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    csrf: str = client.cookies["csrf_token"]
    return csrf


def _events(engine: Engine, event_type: str | None = None) -> list[dict[str, Any]]:
    sql = (
        "SELECT event_type, book_id, shelf_id, surface, session_id, "
        "recommendation_request_id, search_query_id, source_book_id, rank_position, payload "
        "FROM interaction_events"
    )
    params: dict[str, Any] = {}
    if event_type is not None:
        sql += " WHERE event_type = :event_type"
        params["event_type"] = event_type
    sql += " ORDER BY id"
    with engine.begin() as conn:
        return [dict(row) for row in conn.execute(text(sql), params).mappings()]


def _search_queries(engine: Engine) -> list[dict[str, Any]]:
    with engine.begin() as conn:
        return [
            dict(row)
            for row in conn.execute(
                text(
                    "SELECT id, user_id, session_id, query_text, surface "
                    "FROM search_queries ORDER BY occurred_at"
                )
            ).mappings()
        ]


# --- book_opened (rec-spec §4.2) --------------------------------------------


def test_book_opened_writes_every_raw_attribution_field(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    book_id = insert_book(title="Opened Book")
    source_id = insert_book(title="Source Book")
    csrf = _register_and_login(client)
    request_id = str(uuid4())

    response = client.post(
        f"/api/v1/books/{book_id}/opened",
        headers={"X-CSRF-Token": csrf},
        json={
            "attribution": {
                "surface": "similar",
                "session_id": SESSION_ID,
                "recommendation_request_id": request_id,
                "source_book_id": source_id,
                "rank_position": 3,
            }
        },
    )
    assert response.status_code == 204, response.text

    events = _events(test_engine, "book_opened")
    assert len(events) == 1
    event = events[0]
    assert event["book_id"] == book_id
    assert event["surface"] == "similar"
    assert str(event["session_id"]) == SESSION_ID
    assert str(event["recommendation_request_id"]) == request_id
    assert event["source_book_id"] == source_id
    assert event["rank_position"] == 3
    assert event["search_query_id"] is None


def test_book_opened_without_attribution_still_records_the_open(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    """ADR-0015: an action from a surface with no known provenance is a
    complete record, not a degraded one — it must not be rejected."""
    book_id = insert_book()
    csrf = _register_and_login(client)

    response = client.post(
        f"/api/v1/books/{book_id}/opened", headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 204, response.text

    events = _events(test_engine, "book_opened")
    assert len(events) == 1
    assert events[0]["book_id"] == book_id
    assert events[0]["surface"] is None
    assert events[0]["session_id"] is None


def test_book_opened_does_not_change_preference_state(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    """rec-spec §7.1: an open is weak attention, not preference. It must
    not create a `user_book_states` row, or a reader browsing would
    silently accumulate state they never expressed."""
    book_id = insert_book()
    csrf = _register_and_login(client)

    client.post(f"/api/v1/books/{book_id}/opened", headers={"X-CSRF-Token": csrf})

    with test_engine.begin() as conn:
        count = conn.execute(text("SELECT count(*) FROM user_book_states")).scalar_one()
    assert count == 0


def test_repeated_opens_append_repeated_events(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    """Frequency is the signal — de-duplicating opens would discard it."""
    book_id = insert_book()
    csrf = _register_and_login(client)

    for _ in range(3):
        client.post(f"/api/v1/books/{book_id}/opened", headers={"X-CSRF-Token": csrf})

    assert len(_events(test_engine, "book_opened")) == 3


def test_get_book_detail_remains_side_effect_free(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    """The whole reason `POST /opened` exists (ADR-0015). If reading a book
    ever starts writing an event, prefetches and refreshes become
    indistinguishable from intent."""
    book_id = insert_book()
    _register_and_login(client)

    assert client.get(f"/api/v1/books/{book_id}").status_code == 200
    assert _events(test_engine) == []


def test_book_opened_requires_csrf(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    book_id = insert_book()
    _register_and_login(client)

    response = client.post(f"/api/v1/books/{book_id}/opened")
    assert response.status_code == 403
    assert _events(test_engine) == []


def test_book_opened_for_unknown_book_is_404(
    client: TestClient, test_engine: Engine
) -> None:
    csrf = _register_and_login(client)
    response = client.post(
        "/api/v1/books/987654321/opened", headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 404
    assert _events(test_engine) == []


def test_unknown_surface_value_is_rejected(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    """`InteractionSurface` is a closed set on purpose (ADR-0015): a typo'd
    surface is a silently-wrong training row no database constraint would
    ever catch, so it has to fail at the API edge."""
    book_id = insert_book()
    csrf = _register_and_login(client)

    response = client.post(
        f"/api/v1/books/{book_id}/opened",
        headers={"X-CSRF-Token": csrf},
        json={"attribution": {"surface": "hom"}},
    )
    assert response.status_code == 422
    assert _events(test_engine) == []


# --- attribution on strong signals (rec-spec §4.3) --------------------------


def test_rating_carries_attribution(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)
    request_id = str(uuid4())

    response = client.put(
        f"/api/v1/books/{book_id}/rating",
        headers={"X-CSRF-Token": csrf},
        json={
            "rating": 4.5,
            "attribution": {
                "surface": "home",
                "session_id": SESSION_ID,
                "recommendation_request_id": request_id,
                "rank_position": 7,
            },
        },
    )
    assert response.status_code == 200, response.text

    events = _events(test_engine, "rating_set")
    assert len(events) == 1
    assert events[0]["surface"] == "home"
    assert str(events[0]["recommendation_request_id"]) == request_id
    assert events[0]["rank_position"] == 7
    # The rating itself is unaffected by the extra field.
    assert events[0]["payload"]["rating"] == 9


def test_rating_without_attribution_still_works(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    """The pre-R1 request shape must keep working verbatim — attribution is
    additive, never required."""
    book_id = insert_book()
    csrf = _register_and_login(client)

    response = client.put(
        f"/api/v1/books/{book_id}/rating",
        headers={"X-CSRF-Token": csrf},
        json={"rating": 3.0},
    )
    assert response.status_code == 200, response.text

    events = _events(test_engine, "rating_set")
    assert len(events) == 1
    assert events[0]["surface"] is None
    assert events[0]["recommendation_request_id"] is None


def test_not_interested_carries_attribution(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    """The strongest explicit negative (rec-spec §7.1) — knowing which
    surface provoked it is the point."""
    book_id = insert_book()
    csrf = _register_and_login(client)
    request_id = str(uuid4())

    response = client.put(
        f"/api/v1/books/{book_id}/not-interested",
        headers={"X-CSRF-Token": csrf},
        json={
            "attribution": {
                "surface": "home",
                "recommendation_request_id": request_id,
                "rank_position": 0,
            }
        },
    )
    assert response.status_code == 200, response.text

    events = _events(test_engine, "not_interested_set")
    assert len(events) == 1
    assert events[0]["surface"] == "home"
    assert str(events[0]["recommendation_request_id"]) == request_id
    assert events[0]["rank_position"] == 0


def test_not_interested_without_body_still_works(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    """This route took no body at all before R1."""
    book_id = insert_book()
    csrf = _register_and_login(client)

    response = client.put(
        f"/api/v1/books/{book_id}/not-interested", headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 200, response.text
    assert response.json()["not_interested"] is True


def test_repeat_rating_of_same_value_records_nothing(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    """A no-op PUT appends no event, so it records no attribution either —
    nothing happened to attribute."""
    book_id = insert_book()
    csrf = _register_and_login(client)
    body = {"rating": 4.0, "attribution": {"surface": "home"}}

    client.put(
        f"/api/v1/books/{book_id}/rating", headers={"X-CSRF-Token": csrf}, json=body
    )
    client.put(
        f"/api/v1/books/{book_id}/rating", headers={"X-CSRF-Token": csrf}, json=body
    )

    assert len(_events(test_engine, "rating_set")) == 1


# --- shelf saves and source_surface (rec-spec §4.3) -------------------------


def _create_shelf(client: TestClient, csrf: str, name: str = "Sci-fi") -> str:
    response = client.post(
        "/api/v1/shelves", headers={"X-CSRF-Token": csrf}, json={"name": name}
    )
    assert response.status_code == 201, response.text
    shelf_id: str = response.json()["id"]
    return shelf_id


def _shelf_books(engine: Engine) -> list[dict[str, Any]]:
    with engine.begin() as conn:
        return [
            dict(row)
            for row in conn.execute(
                text(
                    "SELECT shelf_id, book_id, source_surface FROM shelf_books ORDER BY added_at"
                )
            ).mappings()
        ]


def test_shelf_sync_populates_source_surface(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    """`shelf_books.source_surface` has existed since Phase 4 with every
    caller omitting it. R1 is where it finally carries a value."""
    book_id = insert_book()
    csrf = _register_and_login(client)
    shelf_id = _create_shelf(client, csrf)

    response = client.put(
        f"/api/v1/books/{book_id}/shelves",
        headers={"X-CSRF-Token": csrf},
        json={"shelf_ids": [shelf_id], "attribution": {"surface": "similar"}},
    )
    assert response.status_code == 200, response.text

    memberships = _shelf_books(test_engine)
    assert len(memberships) == 1
    assert memberships[0]["source_surface"] == "similar"

    events = _events(test_engine, "shelf_book_added")
    assert len(events) == 1
    assert events[0]["surface"] == "similar"
    assert str(events[0]["shelf_id"]) == shelf_id


def test_direct_shelf_add_populates_source_surface(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)
    shelf_id = _create_shelf(client, csrf)

    response = client.put(
        f"/api/v1/shelves/{shelf_id}/books/{book_id}",
        headers={"X-CSRF-Token": csrf},
        json={"attribution": {"surface": "search", "session_id": SESSION_ID}},
    )
    assert response.status_code == 204, response.text

    assert _shelf_books(test_engine)[0]["source_surface"] == "search"
    assert str(_events(test_engine, "shelf_book_added")[0]["session_id"]) == SESSION_ID


def test_shelf_add_without_body_still_works(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)
    shelf_id = _create_shelf(client, csrf)

    response = client.put(
        f"/api/v1/shelves/{shelf_id}/books/{book_id}", headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 204, response.text
    assert _shelf_books(test_engine)[0]["source_surface"] is None


def test_shelf_removal_event_is_not_stamped_with_save_attribution(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    """Attribution describes the *save*. The surface a reader happened to be
    on while un-shelving says nothing about why the book was saved, so
    stamping the removal with it would misattribute the original save."""
    book_id = insert_book()
    csrf = _register_and_login(client)
    shelf_id = _create_shelf(client, csrf)

    client.put(
        f"/api/v1/books/{book_id}/shelves",
        headers={"X-CSRF-Token": csrf},
        json={"shelf_ids": [shelf_id], "attribution": {"surface": "home"}},
    )
    client.put(
        f"/api/v1/books/{book_id}/shelves",
        headers={"X-CSRF-Token": csrf},
        json={"shelf_ids": [], "attribution": {"surface": "book_detail"}},
    )

    removals = _events(test_engine, "shelf_book_removed")
    assert len(removals) == 1
    assert removals[0]["surface"] is None


def test_multi_shelf_save_stamps_every_membership(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)
    first = _create_shelf(client, csrf, "Sci-fi")
    second = _create_shelf(client, csrf, "Favourites")

    response = client.put(
        f"/api/v1/books/{book_id}/shelves",
        headers={"X-CSRF-Token": csrf},
        json={"shelf_ids": [first, second], "attribution": {"surface": "home"}},
    )
    assert response.status_code == 200, response.text

    memberships = _shelf_books(test_engine)
    assert len(memberships) == 2
    assert {m["source_surface"] for m in memberships} == {"home"}


# --- submitted searches (rec-spec §4.4) -------------------------------------


def test_search_suggestions_create_no_search_query_rows(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    """The core rec-spec §4.4 rule: only *committed* searches are logged.
    `GET /search/books` also backs the debounced suggestions dropdown, so
    if it wrote a row the log would fill with keystroke prefixes."""
    insert_book(title="Dune")
    _register_and_login(client)

    response = client.get("/api/v1/search/books", params={"q": "dun", "limit": 5})
    assert response.status_code == 200

    assert _search_queries(test_engine) == []
    assert _events(test_engine) == []


def test_submitted_search_is_recorded(client: TestClient, test_engine: Engine) -> None:
    csrf = _register_and_login(client)

    response = client.post(
        "/api/v1/search/queries",
        headers={"X-CSRF-Token": csrf},
        json={"query_text": "dune", "session_id": SESSION_ID, "surface": "search"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["query_text"] == "dune"
    assert UUID(body["id"])

    rows = _search_queries(test_engine)
    assert len(rows) == 1
    assert rows[0]["query_text"] == "dune"
    assert str(rows[0]["session_id"]) == SESSION_ID
    assert rows[0]["surface"] == "search"

    # ...and mirrored into the single event log, with a null book_id — the
    # first use of that column's nullability.
    events = _events(test_engine, "search_submitted")
    assert len(events) == 1
    assert events[0]["book_id"] is None
    assert str(events[0]["search_query_id"]) == str(rows[0]["id"])


def test_search_result_open_links_back_to_the_query(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    """The end-to-end point of the whole search-instrumentation slice:
    "which search caused this open?" must be answerable."""
    book_id = insert_book(title="Dune")
    csrf = _register_and_login(client)

    submitted = client.post(
        "/api/v1/search/queries",
        headers={"X-CSRF-Token": csrf},
        json={"query_text": "dune", "session_id": SESSION_ID},
    )
    search_query_id = submitted.json()["id"]

    client.post(
        f"/api/v1/books/{book_id}/opened",
        headers={"X-CSRF-Token": csrf},
        json={
            "attribution": {
                "surface": "search",
                "session_id": SESSION_ID,
                "search_query_id": search_query_id,
                "rank_position": 0,
            }
        },
    )

    opened = _events(test_engine, "book_opened")
    assert len(opened) == 1
    assert str(opened[0]["search_query_id"]) == search_query_id
    assert opened[0]["book_id"] == book_id


def test_blank_search_query_is_rejected(
    client: TestClient, test_engine: Engine
) -> None:
    csrf = _register_and_login(client)
    response = client.post(
        "/api/v1/search/queries",
        headers={"X-CSRF-Token": csrf},
        json={"query_text": ""},
    )
    assert response.status_code == 422
    assert _search_queries(test_engine) == []


def test_search_query_requires_csrf(client: TestClient, test_engine: Engine) -> None:
    _register_and_login(client)
    response = client.post("/api/v1/search/queries", json={"query_text": "dune"})
    assert response.status_code == 403
    assert _search_queries(test_engine) == []


def test_search_query_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/v1/search/queries", json={"query_text": "dune"})
    assert response.status_code == 401
