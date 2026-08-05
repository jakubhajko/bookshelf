"""Opaque keyset-pagination cursors for ordinary list endpoints (spec §4's
``shared/pagination/``): ``GET /me/ratings``, ``GET /shelves/{id}/books``.

Distinct from the persisted-batch recommendation cursors (spec §9.9, Phase
5), which encode a request ID + position into an already-computed,
persisted ordering. These encode a plain keyset — the last-seen sort value
plus a unique tiebreaker id — for queries with no persisted batch behind
them at all.
"""

from __future__ import annotations

from book_app.shared.pagination.cursor import (
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
)
from book_app.shared.pagination.page import Page

__all__ = ["InvalidCursorError", "Page", "decode_cursor", "encode_cursor"]
