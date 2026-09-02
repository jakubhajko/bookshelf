"""Shared pytest fixtures.

No fixture here requires a live PostgreSQL instance: engine construction is
lazy (SQLAlchemy doesn't connect until first use), and the one route that
does touch the database (``/health/ready``) is tested with the database
check monkeypatched — see ``tests/test_health.py``. Real connectivity is
validated separately by running the app against the project-local Postgres
cluster (``make db-start`` + ``make dev-api``), not by this suite.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from book_app.core.config import Settings
from book_app.main import create_app


@pytest.fixture
def settings() -> Settings:
    # The startup warm-up is the one thing in the lifespan that would need a
    # database (risk #121), and this suite deliberately has none — see the
    # module docstring. Off explicitly rather than by environment, so a
    # developer running these next to a live Postgres gets the same run.
    return Settings(environment="test", recommendation_warmup_on_startup=False)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings=settings)
    with TestClient(app) as test_client:
        yield test_client
