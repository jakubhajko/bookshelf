"""Recommendation surface identifiers (spec §9.5's three routes).

Stored as plain TEXT on ``recommendation_requests.surface`` (not a native
enum) — same reasoning as ``interaction_events.event_type`` (Phase 4): the
set of surfaces is very plausibly going to grow (e.g. once search exists,
spec §10.4's ``SearchContext`` already anticipates a fourth).
"""

from __future__ import annotations

from enum import StrEnum


class Surface(StrEnum):
    HOME = "home"
    SHELF = "shelf"
    SIMILAR = "similar"
