"""User-book interaction state (spec §5.2-§5.3, §8.5, §8.9): ratings, Not
Interested, and the append-only interaction event log. Distinct from
``modules/books`` (the catalog resource itself) and ``modules/shelves``
(organizational collections) — this module owns the user's *relationship*
to a book.
"""

from __future__ import annotations
