"""Cross-module enums (spec §4.1)."""

from __future__ import annotations

from enum import StrEnum


class CatalogStatus(StrEnum):
    """Book visibility/validity state (spec §8.3)."""

    ACTIVE = "ACTIVE"
    HIDDEN = "HIDDEN"
    INVALID = "INVALID"
