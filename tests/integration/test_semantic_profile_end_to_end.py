"""Semantic profiling end to end against real PostgreSQL (rec-spec §12, §13).

Covers the path the inspection command takes: real user state → the real
``UserContext`` builder → the real profiler → the real summariser, over real
artifacts. Everything except the encoder itself, which is external and
already exercised by the live build — the embeddings here are synthetic so
the test needs no GPU and no 1.2 GB download.

This is the seam rec-spec §13 cares about: "The inspection path must reuse
the **same profiling code** used by the live recommender."
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
from book_app.modules.recommendations.artifact_paths import read_catalog_snapshot
from book_app.modules.recommendations.context_builder import build_user_context
from book_recommender.artifacts import (
    LocalArtifactStorage,
    load_content_artifact,
    load_item_metadata_artifact,
    write_artifact,
    write_embeddings,
    write_item_metadata,
)
from book_recommender.artifacts.content import EMBEDDINGS_FILENAME
from book_recommender.artifacts.item_metadata import METADATA_FILENAME
from book_recommender.config import CONTENT, ITEM_METADATA
from book_recommender.content.tags import TAG_CLEANING_VERSION
from book_recommender.profiling import (
    build_semantic_profile,
    summarize,
)
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

DIMENSION = 8
#: Two clearly separated tastes, so "found two interests" is a fact about
#: the fixture rather than a hope.
SCIFI = list(range(6))
COOKING = list(range(6, 12))


def _insert_books(engine: Engine) -> list[int]:
    ids: list[int] = []
    with engine.begin() as conn:
        for index in range(12):
            genre = "science fiction" if index in SCIFI else "cooking"
            ids.append(
                int(
                    conn.execute(
                        text(
                            "INSERT INTO books (work_id, title, primary_author_name, "
                            "top_genre, catalog_status) VALUES "
                            "(:work_id, :title, :author, :genre, 'ACTIVE') RETURNING id"
                        ),
                        {
                            "work_id": f"w-{index}",
                            "title": f"{'Space' if index in SCIFI else 'Kitchen'} Book {index}",
                            "author": f"Author {index}",
                            "genre": genre,
                        },
                    ).scalar_one()
                )
            )
    return ids


def _write_artifacts(root: Path, book_ids: list[int], catalog_version: str) -> None:
    storage = LocalArtifactStorage(root)
    items = [(book_id, f"w-{index}") for index, book_id in enumerate(book_ids)]

    vectors = np.zeros((len(book_ids), DIMENSION), dtype=np.float32)
    for index in range(len(book_ids)):
        vectors[index, 0 if index in SCIFI else 1] = 1.0
        vectors[index, 2 + (index % 4)] = 0.05
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

    write_artifact(
        storage,
        CONTENT,
        model_version="20260813T120000Z",
        catalog_version=catalog_version,
        items=items,
        payloads={EMBEDDINGS_FILENAME: lambda path: write_embeddings(path, vectors)},
        config={"encoder": "test-encoder", "dimension": DIMENSION, "normalized": True},
    )

    titles = [
        f"{'Space' if i in SCIFI else 'Kitchen'} Book {i}" for i in range(len(book_ids))
    ]
    genre_vocab = ["science fiction", "cooking"]
    genre_codes = [0 if i in SCIFI else 1 for i in range(len(book_ids))]
    tag_vocab = ["space-opera", "recipes"]
    tag_indptr = [0]
    tag_codes: list[int] = []
    for index in range(len(book_ids)):
        tag_codes.append(0 if index in SCIFI else 1)
        tag_indptr.append(len(tag_codes))

    write_artifact(
        storage,
        ITEM_METADATA,
        model_version="20260813T120000Z",
        catalog_version=catalog_version,
        items=items,
        payloads={
            METADATA_FILENAME: lambda path: write_item_metadata(
                path,
                titles=titles,
                authors=[f"Author {i}" for i in range(len(book_ids))],
                genre_codes=genre_codes,
                genre_vocab=genre_vocab,
                tag_indptr=tag_indptr,
                tag_codes=tag_codes,
                tag_vocab=tag_vocab,
            )
        },
        config={"tags_version": TAG_CLEANING_VERSION},
    )


def _create_user(engine: Engine, username: str) -> UUID:
    """users.id is generated application-side, not by the database, so
    the id is supplied explicitly here."""
    user_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users "
                "(id, username, normalized_username, password_hash, account_status) "
                "VALUES (:id, :username, :normalized, 'x', 'ACTIVE')"
            ),
            {"id": user_id, "username": username, "normalized": username.lower()},
        )
    return user_id


def _rate(engine: Engine, user_id: UUID, book_id: int, value: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO user_book_states (user_id, book_id, rating_value) "
                "VALUES (:user_id, :book_id, :value)"
            ),
            {"user_id": user_id, "book_id": book_id, "value": value},
        )


def _shelve(engine: Engine, user_id: UUID, book_ids: list[int], name: str) -> UUID:
    shelf_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO shelves (id, user_id, name, normalized_name) "
                "VALUES (:id, :user_id, :name, :normalized)"
            ),
            {
                "id": shelf_id,
                "user_id": user_id,
                "name": name,
                "normalized": name.lower(),
            },
        )
        for book_id in book_ids:
            conn.execute(
                text(
                    "INSERT INTO shelf_books (shelf_id, book_id) VALUES (:shelf_id, :book_id)"
                ),
                {"shelf_id": shelf_id, "book_id": book_id},
            )
    return shelf_id


def test_a_reader_with_two_tastes_gets_two_labelled_interests(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    """The phase's central claim, end to end over real application state."""
    book_ids = _insert_books(test_engine)
    user_id = _create_user(test_engine, "two_tastes")
    for index in SCIFI[:3]:
        _rate(test_engine, user_id, book_ids[index], 10)
    for index in COOKING[:3]:
        _rate(test_engine, user_id, book_ids[index], 9)

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
        _write_artifacts(tmp_path, book_ids, catalog.catalog_version)
        storage = LocalArtifactStorage(tmp_path)
        embeddings = load_content_artifact(storage, catalog=catalog)
        metadata = load_item_metadata_artifact(storage, catalog=catalog)
        context = build_user_context(session, user_id=user_id)

    profile = build_semantic_profile(context, embeddings)
    summary = summarize(profile, metadata)

    assert summary.strategy == "clustered"
    assert len(summary.interests) == 2
    labels = {interest.label for interest in summary.interests}
    assert labels == {"space-opera", "recipes"}
    # Each interest's members come from one taste, not both.
    for interest in summary.interests:
        members = set(interest.member_book_ids)
        assert members <= {book_ids[i] for i in SCIFI} or members <= {
            book_ids[i] for i in COOKING
        }


def test_shelves_become_their_own_profiles(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    book_ids = _insert_books(test_engine)
    user_id = _create_user(test_engine, "shelver")
    shelf_id = _shelve(test_engine, user_id, [book_ids[i] for i in SCIFI[:3]], "Space")

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
        _write_artifacts(tmp_path, book_ids, catalog.catalog_version)
        storage = LocalArtifactStorage(tmp_path)
        embeddings = load_content_artifact(storage, catalog=catalog)
        metadata = load_item_metadata_artifact(storage, catalog=catalog)
        context = build_user_context(session, user_id=user_id)

    profile = build_semantic_profile(context, embeddings)
    summary = summarize(profile, metadata, shelf_names={str(shelf_id): "Space"})

    assert len(summary.shelves) == 1
    assert summary.shelves[0].shelf_name == "Space"
    assert summary.shelves[0].member_count == 3
    assert summary.shelves[0].label == "space-opera"


def test_a_reader_with_no_evidence_gets_no_profile(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    book_ids = _insert_books(test_engine)
    user_id = _create_user(test_engine, "newcomer")

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
        _write_artifacts(tmp_path, book_ids, catalog.catalog_version)
        storage = LocalArtifactStorage(tmp_path)
        embeddings = load_content_artifact(storage, catalog=catalog)
        metadata = load_item_metadata_artifact(storage, catalog=catalog)
        context = build_user_context(session, user_id=user_id)

    summary = summarize(build_semantic_profile(context, embeddings), metadata)

    assert summary.strategy == "none"
    assert summary.interests == ()


def test_low_rated_books_do_not_shape_the_profile(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    """rec-spec §7.1: a book someone disliked must not pull their interest
    centroid toward it."""
    book_ids = _insert_books(test_engine)
    user_id = _create_user(test_engine, "picky")
    for index in SCIFI[:3]:
        _rate(test_engine, user_id, book_ids[index], 10)
    for index in COOKING[:3]:
        _rate(test_engine, user_id, book_ids[index], 2)

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
        _write_artifacts(tmp_path, book_ids, catalog.catalog_version)
        storage = LocalArtifactStorage(tmp_path)
        embeddings = load_content_artifact(storage, catalog=catalog)
        metadata = load_item_metadata_artifact(storage, catalog=catalog)
        context = build_user_context(session, user_id=user_id)

    summary = summarize(build_semantic_profile(context, embeddings), metadata)

    members = {b for interest in summary.interests for b in interest.member_book_ids}
    assert members <= {book_ids[i] for i in SCIFI}


def test_the_profile_is_json_serializable_for_the_inspection_command(
    test_session_factory: sessionmaker[Session], test_engine: Engine, tmp_path: Path
) -> None:
    import json

    book_ids = _insert_books(test_engine)
    user_id = _create_user(test_engine, "json_user")
    for index in SCIFI[:3]:
        _rate(test_engine, user_id, book_ids[index], 10)

    with test_session_factory() as session:
        catalog = read_catalog_snapshot(session)
        _write_artifacts(tmp_path, book_ids, catalog.catalog_version)
        storage = LocalArtifactStorage(tmp_path)
        embeddings = load_content_artifact(storage, catalog=catalog)
        metadata = load_item_metadata_artifact(storage, catalog=catalog)
        context = build_user_context(session, user_id=user_id)

    payload = json.dumps(
        summarize(build_semantic_profile(context, embeddings), metadata).as_dict()
    )

    # rec-spec §13: no raw vectors in diagnostics.
    assert "query_vector" not in payload
    assert json.loads(payload)["strategy"] in {"clustered", "single_cluster"}
