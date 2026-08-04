"""Shared text normalization for case/Unicode-insensitive uniqueness.

The spec asks for "Unicode normalization and case folding" in three places
that all need the exact same algorithm to compare equal: usernames (§6.2),
shelf names (§5.4), and catalog taxonomy — genres, shelf tags, authors
(§8.4). One shared implementation avoids three slightly-different ones.
"""

from __future__ import annotations

import unicodedata


def normalize_for_uniqueness(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()
