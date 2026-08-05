"""Unit tests for the search module's DB-free logic (spec §9.6). The
ranking query itself needs real Postgres (trigram/full-text operators) —
see tests/integration/test_search.py.
"""

from __future__ import annotations

from book_app.modules.search.repository import SearchResultRow, cursor_value_for_row


def test_cursor_value_for_row_uses_the_real_ratings_count() -> None:
    row = SearchResultRow(
        book_id=1,
        work_id="w1",
        title="Title",
        primary_author_name="Author",
        cover_object_key=None,
        tier=3,
        ratings_count=42,
    )
    assert cursor_value_for_row(row) == {"tier": 3, "popularity": 42, "book_id": 1}


def test_cursor_value_for_row_treats_a_missing_ratings_count_as_lowest() -> None:
    row = SearchResultRow(
        book_id=2,
        work_id="w2",
        title="Title",
        primary_author_name=None,
        cover_object_key=None,
        tier=6,
        ratings_count=None,
    )
    assert cursor_value_for_row(row) == {"tier": 6, "popularity": -1, "book_id": 2}
