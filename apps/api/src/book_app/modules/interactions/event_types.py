"""Known interaction event type strings.

``interaction_events.event_type`` is plain text, not a native Postgres enum
(spec §8.9 gives it as "enum/text") — deliberately: this log is meant to grow
new event kinds as later phases add recommendation/search interactions
(spec §22), and a Postgres enum type requires a migration to extend where a
text column doesn't. This ``StrEnum`` gives application code the same
autocomplete/type-safety a DB enum would, without that migration cost.
"""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    RATING_SET = "rating_set"
    RATING_CHANGED = "rating_changed"
    RATING_REMOVED = "rating_removed"
    NOT_INTERESTED_SET = "not_interested_set"
    NOT_INTERESTED_REMOVED = "not_interested_removed"
    SHELF_BOOK_ADDED = "shelf_book_added"
    SHELF_BOOK_REMOVED = "shelf_book_removed"
