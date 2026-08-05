"""Tests for the public half-star <-> internal integer rating conversion
(spec §9.2, §5.2)."""

from __future__ import annotations

import pytest

from book_app.modules.interactions.exceptions import InvalidRatingError
from book_app.modules.interactions.rating_scale import internal_to_public, public_to_internal


@pytest.mark.parametrize(
    ("public", "internal"),
    [
        (0.5, 1),
        (1.0, 2),
        (1.5, 3),
        (2.0, 4),
        (2.5, 5),
        (3.0, 6),
        (3.5, 7),
        (4.0, 8),
        (4.5, 9),
        (5.0, 10),
    ],
)
def test_all_ten_half_steps_round_trip(public: float, internal: int) -> None:
    assert public_to_internal(public) == internal
    assert internal_to_public(internal) == public


@pytest.mark.parametrize("bad_value", [0.0, 0.3, 3.3, 5.5, -1.0, 6.0])
def test_non_half_step_or_out_of_range_values_rejected(bad_value: float) -> None:
    with pytest.raises(InvalidRatingError):
        public_to_internal(bad_value)


def test_floating_point_noise_still_resolves_to_the_intended_step() -> None:
    """Binary floating point can't represent 3.0 exactly after certain
    arithmetic (e.g. a client computing it as a sum) — 2.9999999999999996 is
    what that drift looks like. The _EPSILON tolerance in public_to_internal
    exists for inputs like this one."""
    almost_three = 2.9999999999999996
    assert almost_three != 3.0  # confirms this value actually exercises the tolerance
    assert public_to_internal(almost_three) == 6
