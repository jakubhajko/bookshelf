"""Product eligibility rules (spec §5.5) — pure functions over an
already-built ``UserContext``, no database access of their own. These are
the application's hard exclusions, sent to the provider, which must obey
them (spec §10.8); results are still validated defensively regardless.
"""

from __future__ import annotations

from book_recommender.contracts.context import UserContext


def home_exclusions(user_context: UserContext) -> frozenset[int]:
    """Home excludes rated, Not Interested, and shelved-anywhere books."""
    rated = {rating.book_id for rating in user_context.ratings}
    return frozenset(rated | user_context.not_interested_book_ids | user_context.saved_book_ids)


def shelf_exclusions(
    user_context: UserContext, *, shelf_book_ids: frozenset[int]
) -> frozenset[int]:
    """Shelf discovery excludes books already in *that* shelf, rated, and
    Not Interested — books on *other* shelves remain eligible, which is why
    this uses ``shelf_book_ids`` (one shelf) rather than
    ``user_context.saved_book_ids`` (every shelf)."""
    rated = {rating.book_id for rating in user_context.ratings}
    return frozenset(rated | user_context.not_interested_book_ids | shelf_book_ids)


def similar_exclusions(user_context: UserContext, *, source_book_id: int) -> frozenset[int]:
    """Similar books excludes the source book, rated, and Not Interested —
    saved (shelved) books may still appear, so ``saved_book_ids`` is
    deliberately not included."""
    rated = {rating.book_id for rating in user_context.ratings}
    return frozenset(rated | user_context.not_interested_book_ids | {source_book_id})
