"""Tests for username validation (spec §6.2)."""

from __future__ import annotations

import pytest

from book_app.modules.users.exceptions import InvalidUsernameError, UsernameReservedError
from book_app.modules.users.username_rules import validate_username


@pytest.mark.parametrize(
    "username",
    ["abc", "a" * 30, "kubo_hajko", "user-name", "user123", "Ωμέγα", "日本語ユーザー"],
)
def test_valid_usernames_pass(username: str) -> None:
    validate_username(username)  # must not raise


def test_too_short() -> None:
    with pytest.raises(InvalidUsernameError):
        validate_username("ab")


def test_too_long() -> None:
    with pytest.raises(InvalidUsernameError):
        validate_username("a" * 31)


def test_leading_whitespace_rejected() -> None:
    with pytest.raises(InvalidUsernameError):
        validate_username(" abc")


def test_trailing_whitespace_rejected() -> None:
    with pytest.raises(InvalidUsernameError):
        validate_username("abc ")


@pytest.mark.parametrize("bad_char", ["!", "@", " ", ".", "/", "$", "'", '"'])
def test_disallowed_characters_rejected(bad_char: str) -> None:
    with pytest.raises(InvalidUsernameError):
        validate_username(f"abc{bad_char}def")


def test_control_character_rejected() -> None:
    with pytest.raises(InvalidUsernameError):
        validate_username("abc\x00def")


def test_zero_width_joiner_rejected() -> None:
    zero_width_joiner = chr(0x200D)
    with pytest.raises(InvalidUsernameError):
        validate_username(f"abc{zero_width_joiner}def")


@pytest.mark.parametrize(
    # "me" excluded: at 2 characters it's already below MIN_LENGTH, so it's
    # rejected for length before the reserved-name check ever runs — see
    # test_reserved_word_below_min_length_still_rejected below. Still fully
    # blocked either way; just via a different, equally-correct error.
    "reserved",
    ["admin", "api", "auth", "login", "logout", "register", "system", "support", "demo"],
)
def test_reserved_names_rejected(reserved: str) -> None:
    with pytest.raises(UsernameReservedError):
        validate_username(reserved)


def test_reserved_word_below_min_length_still_rejected() -> None:
    """ "me" is reserved but only 2 characters (below MIN_LENGTH=3) — length
    validation runs first, so it never reaches the reserved-name check.
    Still can't be registered, just via InvalidUsernameError, not
    UsernameReservedError."""
    with pytest.raises(InvalidUsernameError):
        validate_username("me")


def test_reserved_names_case_and_normalization_insensitive() -> None:
    with pytest.raises(UsernameReservedError):
        validate_username("ADMIN")


def test_underscore_and_hyphen_allowed() -> None:
    validate_username("under_score-hyphen")
