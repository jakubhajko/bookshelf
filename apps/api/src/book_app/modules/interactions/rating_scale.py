"""Public half-star rating (0.5-5.0) <-> internal integer (1-10) conversion.

Spec §9.2: 'Public rating body: {"rating": 4.5}. Allowed values are exact
half steps from 0.5 to 5.0. Convert to 1-10 internally.' Store as integer
1-10 (spec §5.2), display as 0.5-5.0 stars.
"""

from __future__ import annotations

from book_app.modules.interactions.exceptions import InvalidRatingError

MIN_PUBLIC_RATING = 0.5
MAX_PUBLIC_RATING = 5.0
_STEP = 0.5
_EPSILON = 1e-6


def public_to_internal(rating: float) -> int:
    """Raise InvalidRatingError unless ``rating`` is exactly one of the ten
    allowed half-step values."""
    doubled = rating / _STEP
    rounded = round(doubled)
    if abs(doubled - rounded) > _EPSILON or not (1 <= rounded <= 10):
        raise InvalidRatingError()
    return int(rounded)


def internal_to_public(value: int) -> float:
    return value / 2.0
