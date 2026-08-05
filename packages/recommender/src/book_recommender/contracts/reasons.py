"""Stable recommendation reason codes (spec §10.9).

The API maps these to user-facing prose; the codes themselves are a stable
contract engines/providers emit and callers can switch on, not display text.
"""

from __future__ import annotations

from enum import StrEnum


class ReasonCode(StrEnum):
    POPULAR_WITH_READERS = "POPULAR_WITH_READERS"
    BASED_ON_HIGH_RATINGS = "BASED_ON_HIGH_RATINGS"
    SIMILAR_TO_SAVED_BOOKS = "SIMILAR_TO_SAVED_BOOKS"
    SIMILAR_TO_SHELF = "SIMILAR_TO_SHELF"
    SIMILAR_TO_CURRENT_BOOK = "SIMILAR_TO_CURRENT_BOOK"
    SEMANTIC_QUERY_MATCH = "SEMANTIC_QUERY_MATCH"
    EXPLORATION = "EXPLORATION"
