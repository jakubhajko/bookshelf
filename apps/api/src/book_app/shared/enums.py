"""Cross-module enums (spec §4.1)."""

from __future__ import annotations

from enum import StrEnum


class CatalogStatus(StrEnum):
    """Book visibility/validity state (spec §8.3)."""

    ACTIVE = "ACTIVE"
    HIDDEN = "HIDDEN"
    INVALID = "INVALID"


class AccountStatus(StrEnum):
    """User account state (spec §8.1)."""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    PENDING_DELETION = "PENDING_DELETION"


class ModelVersionStatus(StrEnum):
    """Recommendation artifact registry lifecycle (spec §8.10's ``status``
    column — no explicit value list given in the spec, unlike catalog/account
    status; this is a conservative minimal set, documented in
    docs/implementation/plan.md). No admin UI/CLI moves a version between
    these yet — ``build-popularity`` writes ACTIVE directly."""

    READY = "READY"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
