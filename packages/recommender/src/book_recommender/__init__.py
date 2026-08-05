"""Typed recommendation engine and provider package.

No FastAPI or SQLAlchemy/ORM imports are allowed in this package — see
``docs/adr/0001-modular-monolith.md`` and
``docs/adr/0006-recommender-provider-boundary.md``. ``contracts/`` defines
the typed context/request/result shapes; ``engines/`` implements the
synchronous ``RecommendationEngine`` protocol (mock, popularity, and a
future-pipeline placeholder); ``providers/`` implements the asynchronous
``RecommendationProvider`` protocol (in-process, fallback, and a remote
skeleton) that wraps an engine; ``artifacts/`` is the manifest schema and
local-disk storage a precomputed model (e.g. the popularity ranking) is
loaded from.
"""

from __future__ import annotations

__version__ = "0.1.0"
