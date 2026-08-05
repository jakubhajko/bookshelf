"""Recommendation provider wiring tests against real PostgreSQL (spec
§10.10, §10.13): which provider shape gets selected per configuration, and
graceful degradation when no popularity artifact exists on disk.

Structural (isinstance) checks only — the engines/providers' actual
``recommend()`` behavior is already covered by packages/recommender's own
contract tests; this only confirms configuration selects the right one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from book_app.core.config import Settings
from book_app.modules.recommendations.wiring import build_recommendation_provider
from book_recommender.providers.fallback import FallbackProvider
from book_recommender.providers.in_process import InProcessProvider
from sqlalchemy.orm import Session, sessionmaker


def _settings(
    database_url: str,
    *,
    provider: Literal["mock", "popularity", "future_pipeline"],
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


def test_future_pipeline_primary_is_wrapped_with_a_popularity_fallback(
    test_database_url: str, test_session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    settings = _settings(
        test_database_url, provider="future_pipeline", artifact_path=tmp_path
    )
    provider = build_recommendation_provider(settings, test_session_factory)
    assert isinstance(provider, FallbackProvider)
