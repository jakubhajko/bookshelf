"""Storage abstractions (spec §7.3, §10.13, §14).

Only an ``object_key`` is ever stored in the database — never an absolute,
machine-specific path (spec §14/§20: "Do not construct cover paths in
frontend" implies the backend owns safe path resolution too). Used for cover
images now (Phase 2); model artifacts (Phase 5) reuse the same pattern.
"""

from __future__ import annotations

from book_app.shared.storage.base import ObjectStorage, UnsafeObjectKeyError
from book_app.shared.storage.local import LocalFileStorage

__all__ = ["LocalFileStorage", "ObjectStorage", "UnsafeObjectKeyError"]
