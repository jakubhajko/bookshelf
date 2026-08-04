"""Storage protocol every backend (local, later S3) implements identically.

Only a local implementation exists so far — Phase 2's own scope (spec §18)
is "local cover storage" specifically. An S3-backed implementation of this
same protocol (spec §7.3/§10.13: "Implement local and S3 storage backends")
is a straightforward addition later, when an actual deployment needs it,
without changing any caller — not built speculatively ahead of that.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


class UnsafeObjectKeyError(ValueError):
    """An object key would resolve outside the storage root (path traversal)."""


@runtime_checkable
class ObjectStorage(Protocol):
    def resolve(self, object_key: str) -> Path:
        """Return a servable local path for ``object_key``.

        Raises :class:`UnsafeObjectKeyError` if the key would escape the
        storage root.
        """
        ...

    def exists(self, object_key: str) -> bool: ...
