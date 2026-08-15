"""Recommendation provider wiring tests against real PostgreSQL (spec
§10.10, §10.13, ADR-0014): which provider shape gets selected per
configuration, whether a real artifact built by the CLI is actually loaded,
and graceful degradation when the artifact is missing or stale.

The selection tests are structural (isinstance) only — the
engines/providers' actual ``recommend()`` behavior is already covered by
packages/recommender's own contract tests. The artifact tests below are not
structural: they build a real artifact with the real builder and assert on
what the constructed engine serves, because that is the seam ADR-0014 moved
in recommender Phase R3.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from book_app.cli.build_popularity import run_build as build_popularity
from book_app.core.config import Settings
from book_app.modules.recommendations.wiring import build_recommendation_provider
from book_recommender.contracts.context import HomeContext, UserContext
from book_recommender.contracts.provider import RecommendationRequest
from book_recommender.providers.fallback import FallbackProvider
from book_recommender.providers.in_process import InProcessProvider
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker


def _settings(
    database_url: str,
    *,
    provider: Literal["mock", "popularity", "pipeline"],
    artifact_path: Path,
) -> Settings:
    return Settings(
        environment="test",
        database_url=database_url,
        recommendation_provider=provider,
        artifact_storage_local_path=artifact_path,
    )


def test_missing_artifact_degrades_gracefully_instead_of_raising(
    test_database_url: str, test_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    settings = _settings(
        test_database_url, provider="popularity", artifact_path=tmp_path
    )
    provider = build_recommendation_provider(settings, test_session_factory)
    assert isinstance(provider, InProcessProvider)


def test_popularity_primary_is_not_wrapped_in_a_redundant_fallback(
    test_database_url: str, test_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    settings = _settings(
        test_database_url, provider="popularity", artifact_path=tmp_path
    )
    provider = build_recommendation_provider(settings, test_session_factory)
    # Not a FallbackProvider: wrapping popularity in itself as its own
    # fallback couldn't help if it failed (see wiring.py's own docstring).
    assert not isinstance(provider, FallbackProvider)


def test_mock_primary_is_wrapped_with_a_popularity_fallback(
    test_database_url: str, test_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    settings = _settings(test_database_url, provider="mock", artifact_path=tmp_path)
    provider = build_recommendation_provider(settings, test_session_factory)
    assert isinstance(provider, FallbackProvider)


def test_pipeline_primary_is_wrapped_with_a_popularity_fallback(
    test_database_url: str, test_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    settings = _settings(test_database_url, provider="pipeline", artifact_path=tmp_path)
    provider = build_recommendation_provider(settings, test_session_factory)
    assert isinstance(provider, FallbackProvider)


def test_pipeline_builds_with_no_artifacts_at_all(
    test_database_url: str, test_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    """rec-spec §27: a missing artifact degrades, it does not stop startup.

    ``tmp_path`` holds no artifacts whatsoever, so every generator is
    constructed with ``None`` and reports NO_ARTIFACT. The process must
    still boot and still answer requests — through the popularity fallback
    if the pipeline itself has nothing to say.
    """
    settings = _settings(test_database_url, provider="pipeline", artifact_path=tmp_path)
    provider = build_recommendation_provider(settings, test_session_factory)
    assert isinstance(provider, FallbackProvider)


# --- Real artifact loading (ADR-0014) ---------------------------------------


def _insert_book(
    engine: Engine, *, work_id: str, title: str, ratings_count: int
) -> int:
    with engine.begin() as conn:
        book_id: int = conn.execute(
            text(
                "INSERT INTO books "
                "(work_id, title, catalog_status, ratings_count, average_rating) "
                "VALUES (:work_id, :title, 'ACTIVE', :ratings_count, 4.0) RETURNING id"
            ),
            {"work_id": work_id, "title": title, "ratings_count": ratings_count},
        ).scalar_one()
    return book_id


def _recommend(
    provider: InProcessProvider | FallbackProvider, *, catalog_version: str = "x"
) -> list[int]:
    request = RecommendationRequest(
        request_id=uuid4(),
        user_context=UserContext(
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            ratings=(),
            saved_book_ids=frozenset(),
            shelf_ids=(),
            not_interested_book_ids=frozenset(),
            recent_interactions=(),
            shelf_summaries=(),
            profile_version="test-profile-v1",
        ),
        surface_context=HomeContext(),
        requested_count=10,
        hard_exclusions=frozenset(),
        session_exclusions=frozenset(),
        catalog_version=catalog_version,
    )
    batch = asyncio.run(provider.recommend(request))
    return [candidate.book_id for candidate in batch.candidates]


def test_an_artifact_built_by_the_cli_is_actually_served(
    test_database_url: str,
    test_session_factory: sessionmaker[Session],
    test_engine: Engine,
    tmp_path: Path,
) -> None:
    """End to end across the seam ADR-0014 moved: the builder writes
    ``mapping.npz``/``scores.npz``, the recommender package's own loader
    reads them, and ``wiring.py`` — which no longer knows either format —
    hands the result to the engine in the builder's order."""
    popular = _insert_book(
        test_engine, work_id="w1", title="Popular", ratings_count=10_000
    )
    obscure = _insert_book(test_engine, work_id="w2", title="Obscure", ratings_count=1)
    build_popularity(test_session_factory, artifact_root=tmp_path)

    provider = build_recommendation_provider(
        _settings(test_database_url, provider="popularity", artifact_path=tmp_path),
        test_session_factory,
    )

    assert _recommend(provider) == [popular, obscure]


def test_a_reimport_that_reassigns_book_ids_still_serves_the_right_books(
    test_database_url: str,
    test_session_factory: sessionmaker[Session],
    test_engine: Engine,
    tmp_path: Path,
) -> None:
    """The silent-corruption scenario ADR-0014 names. The artifact is built,
    the catalog is rebuilt from scratch so the same works get different
    autoincrement ids, and the artifact is served without rebuilding. Keyed
    on ``book_id`` this would recommend the wrong books and look fine;
    resolution by ``work_id`` makes it correct.
    """
    _insert_book(test_engine, work_id="w1", title="Popular", ratings_count=10_000)
    _insert_book(test_engine, work_id="w2", title="Obscure", ratings_count=1)
    build_popularity(test_session_factory, artifact_root=tmp_path)

    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE books RESTART IDENTITY CASCADE"))
    # Reinserted in the opposite order, so every id now belongs to the other work.
    new_obscure = _insert_book(
        test_engine, work_id="w2", title="Obscure", ratings_count=1
    )
    new_popular = _insert_book(
        test_engine, work_id="w1", title="Popular", ratings_count=10_000
    )
    assert new_obscure < new_popular

    provider = build_recommendation_provider(
        _settings(test_database_url, provider="popularity", artifact_path=tmp_path),
        test_session_factory,
    )

    # The artifact still says "w1 first". Resolved through work_id, that is
    # now new_popular — not the book that inherited w1's old integer id.
    assert _recommend(provider) == [new_popular, new_obscure]


def test_an_artifact_for_a_different_catalog_degrades_instead_of_serving_wrong_books(
    test_database_url: str,
    test_session_factory: sessionmaker[Session],
    test_engine: Engine,
    tmp_path: Path,
) -> None:
    for index in range(20):
        _insert_book(
            test_engine, work_id=f"old-{index}", title=f"Old {index}", ratings_count=10
        )
    build_popularity(test_session_factory, artifact_root=tmp_path)

    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE books RESTART IDENTITY CASCADE"))
    for index in range(20):
        _insert_book(
            test_engine, work_id=f"new-{index}", title=f"New {index}", ratings_count=10
        )

    provider = build_recommendation_provider(
        _settings(test_database_url, provider="popularity", artifact_path=tmp_path),
        test_session_factory,
    )

    # Degraded to an empty ranking rather than raising at startup or serving
    # 20 books that no longer exist.
    assert _recommend(provider) == []
