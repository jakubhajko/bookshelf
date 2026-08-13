"""Tests for the deterministic profile version (rec-spec §5, recommender
Phase R2) — a pure function, so no database and no fixtures.

The contract has two halves and both matter:

- **sensitive** to every change in durable preference evidence, or readers
  get recommendations derived from preferences they have since revised;
- **insensitive** to passive activity, or the version churns on every feed
  request and caches nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from book_app.modules.recommendations.profile_version import (
    PROFILE_VERSION_ALGORITHM,
    compute_profile_version,
)

SHELF_A = UUID("11111111-1111-1111-1111-111111111111")
SHELF_B = UUID("22222222-2222-2222-2222-222222222222")
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _version(
    *,
    ratings: list[tuple[int, int]] | None = None,
    saved_books: list[tuple[int, UUID, datetime]] | None = None,
    not_interested_book_ids: list[int] | None = None,
    taste_seeds: list[tuple[int, str, datetime]] | None = None,
) -> str:
    return compute_profile_version(
        ratings=ratings or [],
        saved_books=saved_books or [],
        not_interested_book_ids=not_interested_book_ids or [],
        taste_seeds=taste_seeds or [],
    )


# --- shape -------------------------------------------------------------------


def test_version_is_prefixed_with_the_algorithm_id() -> None:
    """So versions from a future algorithm can never collide with these and
    silently share a cache entry."""
    assert _version().startswith(f"{PROFILE_VERSION_ALGORITHM}:")


def test_empty_profile_has_a_stable_version() -> None:
    assert _version() == _version()


# --- determinism -------------------------------------------------------------


def test_identical_evidence_produces_identical_versions() -> None:
    args = {
        "ratings": [(1, 9), (2, 7)],
        "saved_books": [(3, SHELF_A, T0)],
        "not_interested_book_ids": [4],
        "taste_seeds": [(5, "onboarding", T0)],
    }
    assert _version(**args) == _version(**args)  # type: ignore[arg-type]


def test_input_order_does_not_change_the_version() -> None:
    """The load-bearing determinism property. Without internal sorting, an
    unordered query could return the same profile in two different row
    orders and produce two different versions — defeating the cache
    entirely, and intermittently, which is the worst way to find a bug."""
    forward = _version(
        ratings=[(1, 9), (2, 7), (3, 8)],
        saved_books=[(10, SHELF_A, T0), (11, SHELF_B, T0)],
        not_interested_book_ids=[20, 21],
        taste_seeds=[(30, "onboarding", T0), (31, "onboarding", T0)],
    )
    reversed_ = _version(
        ratings=[(3, 8), (2, 7), (1, 9)],
        saved_books=[(11, SHELF_B, T0), (10, SHELF_A, T0)],
        not_interested_book_ids=[21, 20],
        taste_seeds=[(31, "onboarding", T0), (30, "onboarding", T0)],
    )
    assert forward == reversed_


def test_timezone_representation_does_not_change_the_version() -> None:
    """`TIMESTAMPTZ` values arrive rendered in the session's time zone, so
    the same instant can show up as +00:00 in one process and +02:00 in
    another. Same instant must mean same version."""
    utc = _version(saved_books=[(1, SHELF_A, T0)])
    other_offset = _version(saved_books=[(1, SHELF_A, T0.astimezone(_fixed_offset(hours=2)))])
    assert utc == other_offset


def _fixed_offset(*, hours: int):  # type: ignore[no-untyped-def]
    from datetime import timezone

    return timezone(timedelta(hours=hours))


# --- sensitivity to durable evidence ----------------------------------------


def test_new_rating_changes_the_version() -> None:
    assert _version(ratings=[(1, 9)]) != _version(ratings=[(1, 9), (2, 8)])


def test_changed_rating_value_changes_the_version() -> None:
    assert _version(ratings=[(1, 9)]) != _version(ratings=[(1, 4)])


def test_new_shelf_save_changes_the_version() -> None:
    assert _version(saved_books=[(1, SHELF_A, T0)]) != _version(
        saved_books=[(1, SHELF_A, T0), (2, SHELF_A, T0)]
    )


def test_same_book_on_a_different_shelf_changes_the_version() -> None:
    """Shelf identity is part of the evidence — per-shelf semantic
    profiling (rec-spec §12.1) treats the same book on two shelves as two
    different statements of interest."""
    assert _version(saved_books=[(1, SHELF_A, T0)]) != _version(saved_books=[(1, SHELF_B, T0)])


def test_same_book_on_two_shelves_differs_from_one() -> None:
    assert _version(saved_books=[(1, SHELF_A, T0)]) != _version(
        saved_books=[(1, SHELF_A, T0), (1, SHELF_B, T0)]
    )


def test_resaving_at_a_new_time_changes_the_version() -> None:
    """Removing and re-adding leaves the membership *set* identical but the
    recency evidence genuinely different, and generators weight save
    recency — so this must not be treated as a no-op."""
    assert _version(saved_books=[(1, SHELF_A, T0)]) != _version(
        saved_books=[(1, SHELF_A, T0 + timedelta(days=30))]
    )


def test_not_interested_changes_the_version() -> None:
    assert _version() != _version(not_interested_book_ids=[1])


def test_taste_seed_changes_the_version() -> None:
    assert _version() != _version(taste_seeds=[(1, "onboarding", T0)])


def test_seed_source_is_part_of_the_version() -> None:
    assert _version(taste_seeds=[(1, "onboarding", T0)]) != _version(
        taste_seeds=[(1, "import", T0)]
    )


# --- insensitivity: the anti-churn half -------------------------------------


def test_passive_evidence_has_no_input_to_change() -> None:
    """rec-spec §5: impressions and opens must not invalidate the long-term
    profile. This is enforced structurally — the function has no parameter
    for them — so this test documents the guarantee and will fail loudly
    (a TypeError) the day someone adds one without thinking it through.
    """
    import inspect

    parameters = set(inspect.signature(compute_profile_version).parameters)
    assert parameters == {
        "ratings",
        "saved_books",
        "not_interested_book_ids",
        "taste_seeds",
    }


def test_components_cannot_be_confused_across_the_separator() -> None:
    """A book id in one component must not be able to masquerade as part of
    another. Distinct evidence, distinct version."""
    rated = _version(ratings=[(1, 9)])
    seeded = _version(taste_seeds=[(1, "onboarding", T0)])
    not_interested = _version(not_interested_book_ids=[1])

    assert len({rated, seeded, not_interested}) == 3
