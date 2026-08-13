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
    #: An *intentional* open of a book's detail view (rec-spec §4.2).
    #: Written only from a dedicated endpoint the UI calls on a real click —
    #: never as a side effect of `GET /books/{id}`, which stays pure so it
    #: can't fire on prefetches, crawlers or a page refresh (ADR-0015).
    #: Weak attention evidence, not a durable preference: rec-spec §7.1
    #: keeps it out of long-term ALS and item-item seeding entirely.
    BOOK_OPENED = "book_opened"
    #: A *submitted* search, never a debounced autocomplete keystroke. The
    #: query text lives in `search_queries`; this row is the event-log view
    #: of the same act, carrying `search_query_id` so a later `book_opened`
    #: can be traced back to the search that produced it. `book_id` is null
    #: here — the first use of that column's nullability.
    SEARCH_SUBMITTED = "search_submitted"
