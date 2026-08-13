# ADR-0019: Cold-start taste seeds are domain state, not ratings or shelf saves

## Status

Accepted (Recommender Phase 0). Consistent with ADR-0015's raw-evidence
principle.

## Context

A brand-new user has no ratings, no shelves and no history. Every
personalized generator returns nothing, so the feed collapses to
popularity — which is a correct fallback but a poor first impression, and
it produces no signal to improve on. The standard fix is onboarding: ask
the new reader to pick a handful of books they already like.

The question is how to store those picks, and there is a shortcut that
looks harmless and is not: write them as 5-star ratings, or auto-create a
"Favourites" shelf and save them there.

Both corrupt domain state that the application already defines precisely.
A rating in this product means *"I have read this and here is my
judgment"* — it is the basis of the Rated page, it drives spec §5.5's
eligibility exclusions (rated books are excluded from Home), and it is
mutually exclusive with Not Interested. "A book I like the look of" is a
different claim. Writing it as a 10/10 rating means the reader's Rated page
fills with books they never told us they read, and the numbers are not
theirs.

A shelf is likewise something the reader created and named. Auto-creating
one puts a shelf in their library they did not make, on a Shelves page
whose entire premise is curation.

There is also an evidence-quality reason to keep them distinct: a taste
seed is a weaker, differently-shaped signal than a rating. It says
"this appeals to me," not "I read this and loved it." Storing it as a
rating destroys the distinction permanently — no generator can later weigh
it differently, because nothing records that it was ever different.

## Decision

Taste seeds are their own domain concept with their own state, distinct
from ratings and from shelf membership.

Persist current seed state as `(user_id, book_id, selected_at, source)`,
with `source` = `onboarding` initially and room for other origins later,
plus corresponding raw events consistent with ADR-0015's event-log model.
The state table answers "what are this reader's seeds now"; the events
answer "how did that change over time."

Onboarding itself is **skippable**. It encourages roughly 3-10 selections
but does not hard-block completion below that — a forced onboarding wall
on a discovery product costs more readers than a sparse profile does.

Taste seeds enter `UserContext` as first-class evidence and feed ALS
fold-in, item-item seeding, and semantic profile queries at the weights
their signal strength warrants (ADR-0015's signal policy) — not
automatically at rating-equivalent weight.

They do **not** create ratings, do **not** create shelf memberships, and do
**not** by themselves make a book ineligible on Home. Eligibility rules
stay exactly as spec §5.5 defines them; if a seeded book should be excluded
somewhere, that is a separate, explicit product decision, not a side effect
of storage choice.

Cold-start behavior is specified end to end:

- new user with seeds → ALS fold-in, item-item seeds and semantic queries
  are all immediately available;
- new user who skipped → diversified popularity Home (a good fallback, not
  a broken state);
- known user, empty shelf → conservative global context plus popularity on
  that shelf until it has members;
- Similar Books is never truly cold — the source book is itself the seed.

## Alternatives considered

- **Store seeds as 5-star ratings** — rejected, see Context. Corrupts the
  meaning of a rating, pollutes the Rated page with books the reader never
  claimed to have read, silently changes Home eligibility, and destroys the
  distinction between "looks appealing" and "read and loved."
- **Auto-create a shelf and save seeds into it** — rejected. Puts an
  uncurated shelf into a curated space, and makes seeds subject to shelf
  semantics (removal, renaming, deletion) they should not have.
- **Extend `user_book_states` with a `taste_seed` flag** — considered.
  Rejected in favour of separate state: `user_book_states` encodes the
  Neutral/Rated/Not-Interested trichotomy with a database-level mutual
  -exclusion constraint, and a seed is orthogonal to all three (a seed can
  reasonably coexist with any of them). Overloading that row would mean
  loosening a constraint that currently protects a real domain rule.
- **Store an opaque preference vector from onboarding instead of book
  picks** — rejected. It is a derived artifact, not a product fact; it
  cannot be shown back to the reader, edited, or reinterpreted by a
  different generator — the same objection ADR-0015 makes to a universal
  interaction score.
- **Make onboarding mandatory** — rejected. Popularity fallback exists
  precisely so that skipping produces a usable product.

## Consequences

- A new API surface is needed to read and update onboarding selections, and
  the frontend onboarding UI (recommender Phase 8) builds on the existing
  search/card components rather than a bespoke picker.
- A book being a taste seed is independent of every other state it can be
  in. Tests assert this directly: seeding a book must not make it appear
  rated, saved, or ineligible.
- Seeds are durable long-term preference evidence, so mutating them changes
  the deterministic `profile_version` — the same as a rating or a shelf
  save, and unlike a passive impression.
- Because seeds are their own signal, their weight relative to ratings and
  saves is a tunable configuration value that can be revised from
  evaluation, rather than a fact frozen into the schema.
