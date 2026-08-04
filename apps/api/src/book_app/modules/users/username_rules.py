"""Username validation and normalization (spec §6.2).

Pure validation logic — no database session, no HTTP concerns — kept apart
from ``repository.py`` (persistence) so it's independently testable and
reusable wherever a username needs checking before a session even exists.
"""

from __future__ import annotations

import unicodedata

from book_app.modules.users.exceptions import InvalidUsernameError, UsernameReservedError
from book_app.shared.text import normalize_for_uniqueness

MIN_LENGTH = 3
MAX_LENGTH = 30

RESERVED_USERNAMES = frozenset(
    {"admin", "api", "auth", "login", "logout", "register", "me", "system", "support", "demo"}
)


def _is_allowed_char(char: str) -> bool:
    return char.isalpha() or char.isdigit() or char in "_-"


def validate_username(raw: str) -> None:
    """Raise ``InvalidUsernameError``/``UsernameReservedError`` on any spec §6.2 violation.

    Does not check uniqueness against existing users — that needs a
    database session, which this function deliberately doesn't take.
    """
    if raw != raw.strip():
        raise InvalidUsernameError("Username must not have leading or trailing whitespace.")

    if not (MIN_LENGTH <= len(raw) <= MAX_LENGTH):
        raise InvalidUsernameError(f"Username must be {MIN_LENGTH}-{MAX_LENGTH} characters.")

    for char in raw:
        if unicodedata.category(char) in ("Cc", "Cf"):
            raise InvalidUsernameError(
                "Username must not contain control or invisible formatting characters."
            )
        if not _is_allowed_char(char):
            raise InvalidUsernameError(
                "Username may only contain Unicode letters, digits, underscore, and hyphen."
            )

    if normalize_for_uniqueness(raw) in RESERVED_USERNAMES:
        raise UsernameReservedError(f"{raw!r} is a reserved username.")
