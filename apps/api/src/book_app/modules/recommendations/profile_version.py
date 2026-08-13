"""Deterministic fingerprint of a user's durable preference evidence
(rec-spec §5).

Pure: takes already-fetched values, touches no database, imports nothing
from SQLAlchemy or FastAPI. That makes it exhaustively unit-testable
without fixtures, which matters because the property under test — "equal
long-term profile implies equal version, and passive activity never
changes it" — is a claim about *every* input, not about one scenario.

## What it is for

rec-spec §9.2 wants a live user's ALS factor cacheable by
`(user_id, profile_version, model_version)` rather than recomputed on every
fresh batch. That is only sound if the version changes exactly when the
evidence the factor was computed from changes. Too eager and the cache
never hits; too lazy and readers get recommendations built from preferences
they have since revised — the worse failure of the two.

## What counts as durable

Included, because a generator reads them as preference:

- ratings — book and value;
- shelf memberships — book, shelf and `added_at`;
- Not Interested;
- taste seeds — book, source and `selected_at`.

Excluded, deliberately:

- **recommendation impressions.** rec-spec §5 is explicit that passive
  exposure must not invalidate the long-term profile. Being *shown* books
  is not a preference, and if it bumped the version, the version would
  change on every feed request and cache nothing.
- **book opens.** Weak attention, not durable preference (rec-spec §7.1).
  Session recency is tracked separately through browsing-session state.
- **search queries.** Contextual intent, not long-term taste.

## Timestamps

Rating *values* are included but rating timestamps are not. `updated_at` on
`user_book_states` fires on any change to the row — including a
Not-Interested transition — so folding it in would make the version churn
for reasons that have nothing to do with the rating. The rating's value
already changes whenever the rating meaningfully does.

Shelf `added_at` and seed `selected_at` *are* included, because unlike a
rating timestamp they are evidence generators actually weight (save
recency, rec-spec §12.1). It follows that removing a book from a shelf and
re-adding it changes the version even though the membership set is
unchanged — correct, since the recency evidence genuinely changed.

## Truncation

The caller passes the *context's* components, already bounded and
truncated. The version therefore describes what the engine will actually
see, not the full database state — which is the right thing for a cache
key over derived state.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

#: Bumped when the *algorithm* changes, so versions computed by different
#: implementations can never collide and silently share a cache entry.
PROFILE_VERSION_ALGORITHM = "v1"

_FINGERPRINT_LENGTH = 16


def _timestamp(value: datetime) -> str:
    """The instant, normalized to UTC.

    Always converting is the point. These come from `TIMESTAMPTZ` columns,
    and psycopg renders them in the *session's* time zone — so the same
    stored instant can arrive as `+00:00` in one process and `+02:00` in
    another. Formatting whatever arrived would then fingerprint two
    identical profiles differently and quietly defeat the cache this
    version exists to enable.

    A naive value is assumed to be UTC. Every column feeding this is
    `timezone=True`, so that case only arises from hand-built test data.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def compute_profile_version(
    *,
    ratings: Iterable[tuple[int, int]],
    saved_books: Iterable[tuple[int, UUID, datetime]],
    not_interested_book_ids: Iterable[int],
    taste_seeds: Iterable[tuple[int, str, datetime]],
) -> str:
    """Fingerprint the durable evidence.

    Every component is sorted before hashing, so the version depends on the
    *content* of the profile and not on the order rows happened to come
    back from PostgreSQL — without that, an unordered query could hand back
    two different versions for an identical profile and defeat the cache
    entirely.

    :param ratings: ``(book_id, rating_value)`` on the internal 1-10 scale.
    :param saved_books: ``(book_id, shelf_id, added_at)`` per membership.
    :param not_interested_book_ids: book ids marked Not Interested.
    :param taste_seeds: ``(book_id, source, selected_at)``.
    """
    parts: list[str] = [f"algo={PROFILE_VERSION_ALGORITHM}"]

    parts.append("ratings=" + ";".join(sorted(f"{b}:{v}" for b, v in ratings)))
    parts.append("saved=" + ";".join(sorted(f"{b}:{s}:{_timestamp(t)}" for b, s, t in saved_books)))
    parts.append("not_interested=" + ";".join(sorted(str(b) for b in not_interested_book_ids)))
    parts.append(
        "seeds=" + ";".join(sorted(f"{b}:{src}:{_timestamp(t)}" for b, src, t in taste_seeds))
    )

    # "|" cannot appear in any component (ids are numeric, UUIDs and ISO
    # timestamps have a fixed alphabet, and `source` is a closed enum
    # validated at the API edge), so it is an unambiguous separator — no
    # component can be crafted to look like the start of the next one.
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return f"{PROFILE_VERSION_ALGORITHM}:{digest[:_FINGERPRINT_LENGTH]}"
