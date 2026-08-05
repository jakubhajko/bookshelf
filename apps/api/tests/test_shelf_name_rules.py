"""Tests for shelf name validation (spec §5.4, §8.6)."""

from __future__ import annotations

import pytest

from book_app.modules.shelves.exceptions import InvalidShelfNameError
from book_app.modules.shelves.shelf_name_rules import MAX_LENGTH, clean_shelf_name


def test_valid_name_passes_through_unchanged() -> None:
    assert clean_shelf_name("Summer Reading") == "Summer Reading"


def test_leading_and_trailing_whitespace_is_trimmed() -> None:
    assert clean_shelf_name("  Summer Reading  ") == "Summer Reading"


def test_empty_name_rejected() -> None:
    with pytest.raises(InvalidShelfNameError):
        clean_shelf_name("")


def test_whitespace_only_name_rejected() -> None:
    with pytest.raises(InvalidShelfNameError):
        clean_shelf_name("   ")


def test_max_length_name_accepted() -> None:
    name = "a" * MAX_LENGTH
    assert clean_shelf_name(name) == name


def test_over_max_length_name_rejected() -> None:
    with pytest.raises(InvalidShelfNameError):
        clean_shelf_name("a" * (MAX_LENGTH + 1))


def test_unicode_name_preserved() -> None:
    assert clean_shelf_name("Café Reads 日本語") == "Café Reads 日本語"
