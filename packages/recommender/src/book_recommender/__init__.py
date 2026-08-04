"""Typed recommendation engine and provider package.

No FastAPI or SQLAlchemy/ORM imports are allowed in this package — see
``docs/adr/0001-modular-monolith.md`` and
``docs/adr/0006-recommender-provider-boundary.md``. The real engine/provider
protocols (``contracts/``, ``providers/``, ``artifacts/``) land in Phase 5
(``APP_SPECIFICATION.md`` §10, §18); this package currently only establishes
the installable workspace member and the boundary itself.
"""

from __future__ import annotations

__version__ = "0.1.0"
