"""Shelf name validation (spec §5.4, §8.6). Pure validation logic — no
database session (uniqueness needs one; checked by the caller).

Unlike usernames (spec §6.2), the spec gives no character-class rules for
shelf names, only that they're unique per user after Unicode normalization
and case folding and fit `varchar(100)`. Leading/trailing whitespace is
silently trimmed rather than rejected — reasonable for casual, free-form
collection names (unlike usernames, spec never asks for rejection here).
"""

from __future__ import annotations

from book_app.modules.shelves.exceptions import InvalidShelfNameError

MAX_LENGTH = 100


def clean_shelf_name(raw: str) -> str:
    """Return the trimmed, storable name, or raise InvalidShelfNameError."""
    cleaned = raw.strip()
    if not cleaned:
        raise InvalidShelfNameError("Shelf name must not be empty.")
    if len(cleaned) > MAX_LENGTH:
        raise InvalidShelfNameError(f"Shelf name must be at most {MAX_LENGTH} characters.")
    return cleaned
