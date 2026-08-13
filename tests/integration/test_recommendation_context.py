"""Recommender Phase R2: the recommendation context preserves preference
*structure*, and `profile_version` behaves as a cache key (rec-spec §5, §6;
ADR-0019).

Built against real PostgreSQL through `context_builder`, the same code path
`modules/recommendations/service.py` uses before it calls a provider —
testing the real thing rather than a reconstruction of it.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from book_app.modules.recommendations import context_builder
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

USERNAME = "context_user"
PASSWORD = "correct horse battery staple"


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


def _user_id(engine: Engine, username: str = USERNAME) -> UUID:
    with engine.begin() as conn:
        return conn.execute(
            text("SELECT id FROM users WHERE username = :u"), {"u": username}
        ).scalar_one()


def _build(session_factory: sessionmaker[Session], user_id: UUID):  # type: ignore[no-untyped-def]
    with session_factory() as session:
        return context_builder.build_user_context(session, user_id=user_id)


def _create_shelf(client: TestClient, csrf: str, name: str) -> str:
    response = client.post(
        "/api/v1/shelves", headers={"X-CSRF-Token": csrf}, json={"name": name}
    )
    assert response.status_code == 201, response.text
    shelf_id: str = response.json()["id"]
    return shelf_id


# --- per-shelf membership (rec-spec §5) -------------------------------------


def test_multi_shelf_membership_survives_context_construction(
    client: TestClient,
    insert_book: Callable[..., int],
    test_engine: Engine,
    test_session_factory: sessionmaker[Session],
) -> None:
    """The core R2 fix. `saved_book_ids` collapses a book on three shelves
    to one id, which is right for eligibility and useless for shelf-scoped
    profiling — so `saved_books` keeps every membership."""
    book_id = insert_book(title="Multi-shelved")
    csrf = _register_and_login(client)
    shelf_a = _create_shelf(client, csrf, "Sci-fi")
    shelf_b = _create_shelf(client, csrf, "Favourites")
    shelf_c = _create_shelf(client, csrf, "Re-read")

    response = client.put(
        f"/api/v1/books/{book_id}/shelves",
        headers={"X-CSRF-Token": csrf},
        json={"shelf_ids": [shelf_a, shelf_b, shelf_c]},
    )
    assert response.status_code == 200, response.text

    context = _build(test_session_factory, _user_id(test_engine))

    assert context.saved_book_ids == frozenset({book_id})
    assert len(context.saved_books) == 3
    assert {str(s.shelf_id) for s in context.saved_books} == {shelf_a, shelf_b, shelf_c}
    assert all(s.book_id == book_id for s in context.saved_books)


def test_save_timestamp_survives(
    client: TestClient,
    insert_book: Callable[..., int],
    test_engine: Engine,
    test_session_factory: sessionmaker[Session],
) -> None:
    """Save recency is real evidence (rec-spec §12.1), not bookkeeping."""
    book_id = insert_book()
    csrf = _register_and_login(client)
    shelf_id = _create_shelf(client, csrf, "Sci-fi")
    client.put(
        f"/api/v1/books/{book_id}/shelves",
        headers={"X-CSRF-Token": csrf},
        json={"shelf_ids": [shelf_id]},
    )

    context = _build(test_session_factory, _user_id(test_engine))

    assert len(context.saved_books) == 1
    assert context.saved_books[0].added_at is not None
    assert context.saved_books[0].added_at.tzinfo is not None


def test_recent_interactions_preserve_attribution(
    client: TestClient,
    insert_book: Callable[..., int],
    test_engine: Engine,
    test_session_factory: sessionmaker[Session],
) -> None:
    """Phase R1 wrote these columns; before R2 the context builder threw
    every one of them away, so the engine could never see them."""
    book_id = insert_book()
    csrf = _register_and_login(client)
    session_id = "11111111-2222-3333-4444-555555555555"

    client.post(
        f"/api/v1/books/{book_id}/opened",
        headers={"X-CSRF-Token": csrf},
        json={
            "attribution": {
                "surface": "home",
                "session_id": session_id,
                "rank_position": 4,
            }
        },
    )

    context = _build(test_session_factory, _user_id(test_engine))

    opened = [e for e in context.recent_interactions if e.event_type == "book_opened"]
    assert len(opened) == 1
    assert opened[0].surface == "home"
    assert str(opened[0].session_id) == session_id
    assert opened[0].rank_position == 4


# --- taste seeds (rec-spec §6, ADR-0019) ------------------------------------


def test_taste_seeds_reach_the_context(
    client: TestClient,
    insert_book: Callable[..., int],
    test_engine: Engine,
    test_session_factory: sessionmaker[Session],
) -> None:
    first = insert_book(title="Seed One")
    second = insert_book(title="Seed Two")
    csrf = _register_and_login(client)

    response = client.put(
        "/api/v1/me/taste-seeds",
        headers={"X-CSRF-Token": csrf},
        json={"book_ids": [first, second]},
    )
    assert response.status_code == 200, response.text

    context = _build(test_session_factory, _user_id(test_engine))

    assert {s.book_id for s in context.taste_seeds} == {first, second}
    assert all(s.source == "onboarding" for s in context.taste_seeds)


def test_taste_seed_implies_no_rating_shelf_or_not_interested_state(
    client: TestClient,
    insert_book: Callable[..., int],
    test_engine: Engine,
    test_session_factory: sessionmaker[Session],
) -> None:
    """ADR-0019's central claim, asserted rather than assumed. Storing seeds
    as 5-star ratings or an auto-created shelf is the shortcut this table
    exists to avoid; if that ever regresses, a reader's Rated page fills
    with books they never said they read."""
    book_id = insert_book()
    csrf = _register_and_login(client)

    client.put(
        "/api/v1/me/taste-seeds",
        headers={"X-CSRF-Token": csrf},
        json={"book_ids": [book_id]},
    )

    context = _build(test_session_factory, _user_id(test_engine))

    assert {s.book_id for s in context.taste_seeds} == {book_id}
    assert context.ratings == ()
    assert context.saved_book_ids == frozenset()
    assert context.saved_books == ()
    assert context.not_interested_book_ids == frozenset()

    # ...and nothing leaked into the tables those come from.
    with test_engine.begin() as conn:
        assert (
            conn.execute(text("SELECT count(*) FROM user_book_states")).scalar_one()
            == 0
        )
        assert conn.execute(text("SELECT count(*) FROM shelves")).scalar_one() == 0

    # The book is still absent from the Rated listing.
    rated = client.get("/api/v1/me/ratings")
    assert rated.json()["items"] == []


def test_seeding_is_a_full_replace(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    first = insert_book(title="Seed One")
    second = insert_book(title="Seed Two")
    csrf = _register_and_login(client)

    client.put(
        "/api/v1/me/taste-seeds",
        headers={"X-CSRF-Token": csrf},
        json={"book_ids": [first]},
    )
    response = client.put(
        "/api/v1/me/taste-seeds",
        headers={"X-CSRF-Token": csrf},
        json={"book_ids": [second]},
    )

    assert {item["book_id"] for item in response.json()["items"]} == {second}

    # Both transitions are in the event log, not just the end state.
    with test_engine.begin() as conn:
        events = [
            (row[0], row[1])
            for row in conn.execute(
                text(
                    "SELECT event_type, book_id FROM interaction_events "
                    "WHERE event_type LIKE 'taste_seed%' ORDER BY id"
                )
            )
        ]
    assert events == [
        ("taste_seed_added", first),
        ("taste_seed_added", second),
        ("taste_seed_removed", first),
    ]


def test_clearing_seeds_is_supported(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    """Skipping or undoing onboarding is a valid state, not an error
    (rec-spec §6: optional and skippable)."""
    book_id = insert_book()
    csrf = _register_and_login(client)
    client.put(
        "/api/v1/me/taste-seeds",
        headers={"X-CSRF-Token": csrf},
        json={"book_ids": [book_id]},
    )

    response = client.put(
        "/api/v1/me/taste-seeds", headers={"X-CSRF-Token": csrf}, json={"book_ids": []}
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_reseeding_the_same_books_is_idempotent(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)
    body = {"book_ids": [book_id]}

    client.put("/api/v1/me/taste-seeds", headers={"X-CSRF-Token": csrf}, json=body)
    client.put("/api/v1/me/taste-seeds", headers={"X-CSRF-Token": csrf}, json=body)

    with test_engine.begin() as conn:
        seeds = conn.execute(text("SELECT count(*) FROM user_taste_seeds")).scalar_one()
        events = conn.execute(
            text(
                "SELECT count(*) FROM interaction_events WHERE event_type = 'taste_seed_added'"
            )
        ).scalar_one()
    assert seeds == 1
    assert events == 1


def test_seeding_an_unknown_book_is_rejected_atomically(
    client: TestClient, insert_book: Callable[..., int], test_engine: Engine
) -> None:
    """Validate everything before writing anything, so one bad id can't
    leave a half-applied selection behind."""
    good = insert_book()
    csrf = _register_and_login(client)

    response = client.put(
        "/api/v1/me/taste-seeds",
        headers={"X-CSRF-Token": csrf},
        json={"book_ids": [good, 987654321]},
    )

    assert response.status_code == 404
    with test_engine.begin() as conn:
        assert (
            conn.execute(text("SELECT count(*) FROM user_taste_seeds")).scalar_one()
            == 0
        )


def test_taste_seeds_require_auth_and_csrf(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_id = insert_book()
    assert client.get("/api/v1/me/taste-seeds").status_code == 401

    _register_and_login(client)
    assert (
        client.put("/api/v1/me/taste-seeds", json={"book_ids": [book_id]}).status_code
        == 403
    )


def test_seeds_are_per_user(
    client: TestClient, insert_book: Callable[..., int]
) -> None:
    book_id = insert_book()
    csrf_a = _register_and_login(client, username="seed_owner_a")
    client.put(
        "/api/v1/me/taste-seeds",
        headers={"X-CSRF-Token": csrf_a},
        json={"book_ids": [book_id]},
    )

    _register_and_login(client, username="seed_owner_b")
    assert client.get("/api/v1/me/taste-seeds").json()["items"] == []


# --- profile_version (rec-spec §5) ------------------------------------------


def test_profile_version_is_deterministic_for_unchanged_state(
    client: TestClient,
    insert_book: Callable[..., int],
    test_engine: Engine,
    test_session_factory: sessionmaker[Session],
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)
    client.put(
        f"/api/v1/books/{book_id}/rating",
        headers={"X-CSRF-Token": csrf},
        json={"rating": 4.5},
    )
    user_id = _user_id(test_engine)

    assert (
        _build(test_session_factory, user_id).profile_version
        == _build(test_session_factory, user_id).profile_version
    )


def test_rating_changes_the_profile_version(
    client: TestClient,
    insert_book: Callable[..., int],
    test_engine: Engine,
    test_session_factory: sessionmaker[Session],
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)
    user_id = _user_id(test_engine)
    before = _build(test_session_factory, user_id).profile_version

    client.put(
        f"/api/v1/books/{book_id}/rating",
        headers={"X-CSRF-Token": csrf},
        json={"rating": 5.0},
    )

    assert _build(test_session_factory, user_id).profile_version != before


def test_shelf_save_changes_the_profile_version(
    client: TestClient,
    insert_book: Callable[..., int],
    test_engine: Engine,
    test_session_factory: sessionmaker[Session],
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)
    shelf_id = _create_shelf(client, csrf, "Sci-fi")
    user_id = _user_id(test_engine)
    before = _build(test_session_factory, user_id).profile_version

    client.put(
        f"/api/v1/books/{book_id}/shelves",
        headers={"X-CSRF-Token": csrf},
        json={"shelf_ids": [shelf_id]},
    )

    assert _build(test_session_factory, user_id).profile_version != before


def test_not_interested_changes_the_profile_version(
    client: TestClient,
    insert_book: Callable[..., int],
    test_engine: Engine,
    test_session_factory: sessionmaker[Session],
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)
    user_id = _user_id(test_engine)
    before = _build(test_session_factory, user_id).profile_version

    client.put(
        f"/api/v1/books/{book_id}/not-interested", headers={"X-CSRF-Token": csrf}
    )

    assert _build(test_session_factory, user_id).profile_version != before


def test_taste_seed_changes_the_profile_version(
    client: TestClient,
    insert_book: Callable[..., int],
    test_engine: Engine,
    test_session_factory: sessionmaker[Session],
) -> None:
    book_id = insert_book()
    csrf = _register_and_login(client)
    user_id = _user_id(test_engine)
    before = _build(test_session_factory, user_id).profile_version

    client.put(
        "/api/v1/me/taste-seeds",
        headers={"X-CSRF-Token": csrf},
        json={"book_ids": [book_id]},
    )

    assert _build(test_session_factory, user_id).profile_version != before


def test_recommendation_impressions_do_not_change_the_profile_version(
    client: TestClient,
    insert_book: Callable[..., int],
    test_engine: Engine,
    test_session_factory: sessionmaker[Session],
) -> None:
    """rec-spec §5's explicit requirement, and the whole reason the version
    is worth having: if being *shown* books invalidated it, it would change
    on every feed request and cache nothing."""
    for i in range(10):
        insert_book(title=f"book {i}", work_id=f"book-{i}")
    _register_and_login(client)
    user_id = _user_id(test_engine)
    before = _build(test_session_factory, user_id).profile_version

    feed = client.get("/api/v1/recommendations/home?limit=5")
    assert feed.status_code == 200
    assert feed.json()["items"], "expected the feed to actually deliver impressions"

    with test_engine.begin() as conn:
        impressions = conn.execute(
            text("SELECT count(*) FROM recommendation_impressions")
        ).scalar_one()
    assert impressions > 0

    assert _build(test_session_factory, user_id).profile_version == before


def test_book_opened_does_not_change_the_profile_version(
    client: TestClient,
    insert_book: Callable[..., int],
    test_engine: Engine,
    test_session_factory: sessionmaker[Session],
) -> None:
    """An open is weak attention, not durable preference (rec-spec §7.1) —
    session recency is tracked separately."""
    book_id = insert_book()
    csrf = _register_and_login(client)
    user_id = _user_id(test_engine)
    before = _build(test_session_factory, user_id).profile_version

    client.post(f"/api/v1/books/{book_id}/opened", headers={"X-CSRF-Token": csrf})

    assert _build(test_session_factory, user_id).profile_version == before


def test_submitted_search_does_not_change_the_profile_version(
    client: TestClient,
    test_engine: Engine,
    test_session_factory: sessionmaker[Session],
) -> None:
    csrf = _register_and_login(client)
    user_id = _user_id(test_engine)
    before = _build(test_session_factory, user_id).profile_version

    client.post(
        "/api/v1/search/queries",
        headers={"X-CSRF-Token": csrf},
        json={"query_text": "dune"},
    )

    assert _build(test_session_factory, user_id).profile_version == before


def test_two_users_with_different_evidence_have_different_versions(
    client: TestClient,
    insert_book: Callable[..., int],
    test_engine: Engine,
    test_session_factory: sessionmaker[Session],
) -> None:
    book_id = insert_book()
    csrf_a = _register_and_login(client, username="version_user_a")
    client.put(
        f"/api/v1/books/{book_id}/rating",
        headers={"X-CSRF-Token": csrf_a},
        json={"rating": 5.0},
    )
    _register_and_login(client, username="version_user_b")

    version_a = _build(test_session_factory, _user_id(test_engine, "version_user_a"))
    version_b = _build(test_session_factory, _user_id(test_engine, "version_user_b"))

    assert version_a.profile_version != version_b.profile_version


def test_two_users_with_identical_evidence_share_a_version(
    client: TestClient,
    insert_book: Callable[..., int],
    test_engine: Engine,
    test_session_factory: sessionmaker[Session],
) -> None:
    """The version fingerprints the *profile*, not the user — which is what
    makes `(user_id, profile_version, model_version)` a meaningful cache
    key rather than a per-user salt."""
    _register_and_login(client, username="twin_a")
    _register_and_login(client, username="twin_b")

    version_a = _build(test_session_factory, _user_id(test_engine, "twin_a"))
    version_b = _build(test_session_factory, _user_id(test_engine, "twin_b"))

    assert version_a.profile_version == version_b.profile_version
