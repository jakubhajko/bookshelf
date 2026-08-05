"""Tests for recommendation eligibility rules (spec §5.5) — pure functions
over an already-built UserContext, no database involved."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from book_recommender.contracts.context import RatingSnapshot, UserContext

from book_app.modules.recommendations import eligibility

USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _user_context(
    *,
    rated_book_ids: frozenset[int] = frozenset(),
    not_interested_book_ids: frozenset[int] = frozenset(),
    saved_book_ids: frozenset[int] = frozenset(),
) -> UserContext:
    return UserContext(
        user_id=USER_ID,
        ratings=tuple(
            RatingSnapshot(book_id=book_id, rating_value=8, rated_at=datetime.now(UTC))
            for book_id in rated_book_ids
        ),
        saved_book_ids=saved_book_ids,
        shelf_ids=(),
        not_interested_book_ids=not_interested_book_ids,
        recent_interactions=(),
        shelf_summaries=(),
    )


def test_home_exclusions_combines_rated_not_interested_and_saved() -> None:
    context = _user_context(
        rated_book_ids=frozenset({1}),
        not_interested_book_ids=frozenset({2}),
        saved_book_ids=frozenset({3}),
    )
    assert eligibility.home_exclusions(context) == frozenset({1, 2, 3})


def test_home_exclusions_empty_for_a_new_user() -> None:
    assert eligibility.home_exclusions(_user_context()) == frozenset()


def test_shelf_exclusions_uses_only_the_given_shelfs_books_not_every_saved_book() -> None:
    context = _user_context(
        rated_book_ids=frozenset({1}),
        not_interested_book_ids=frozenset({2}),
        saved_book_ids=frozenset({3, 4}),
    )
    result = eligibility.shelf_exclusions(context, shelf_book_ids=frozenset({4}))
    # Book 3 is saved to a *different* shelf (spec §5.5: "books saved to
    # other shelves remain eligible") and must not be excluded here.
    assert result == frozenset({1, 2, 4})
    assert 3 not in result


def test_similar_exclusions_includes_source_book_but_not_saved_books() -> None:
    context = _user_context(
        rated_book_ids=frozenset({1}),
        not_interested_book_ids=frozenset({2}),
        saved_book_ids=frozenset({5}),
    )
    result = eligibility.similar_exclusions(context, source_book_id=99)
    # Spec §5.5: "Saved books may appear" in similar-books results.
    assert result == frozenset({1, 2, 99})
    assert 5 not in result
