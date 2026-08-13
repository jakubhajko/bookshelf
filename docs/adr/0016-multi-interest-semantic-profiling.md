# ADR-0016: Multi-interest semantic profiling — explicit shelves plus inferred clusters

## Status

Accepted (Recommender Phase 0). Depends on ADR-0018 (offline embeddings).

## Context

A reader is not one taste. Someone with a hard-SF shelf, a poetry shelf and
a slowly-growing interest in medieval history has at least three, and
averaging their books into one profile vector produces a centroid that sits
in empty space between them and retrieves nothing anyone actually wants —
the classic single-centroid failure. The dominant interest also washes out
the smaller ones purely by member count.

Two sources of interest structure exist, and they are not redundant. Shelves
are *explicit*: the reader curated them, named them, and drew the
boundaries deliberately. But shelves are incomplete — plenty of positive
evidence (ratings, taste seeds, saves to a catch-all shelf) belongs to a
coherent interest the reader never made a shelf for.

Fixing the number of interests at some K is also wrong. K is not a property
of the algorithm; it is a property of the person, and it ranges from zero
(a brand-new user) to a dozen. A fixed K fabricates structure for readers
who have one interest and destroys it for readers who have many.

Interest inference is also the part of this system most likely to be
*subtly* wrong — a bad cluster produces recommendations that are confidently
irrelevant, and there is no metric that reliably catches it. It has to be
readable by a person.

## Decision

Represent semantic user preference with **both** strategies, sharing one
embedding artifact and one retrieval primitive. They are different query
strategies over the same vector space, not two embedding systems.

**Explicit shelf profiles.** A normalized weighted vector per shelf, derived
from its member books' embeddings, optionally weighted by save recency and
strong ratings on those books. The target shelf's profile dominates the
Shelf surface. On Home, individual shelf profiles contribute *separate*
candidate lists, so a large shelf cannot wash out a small curated one.

**Inferred interest clusters.** Threshold-based agglomerative/hierarchical
clustering under cosine distance over normalized embeddings of the
strongest/most recent positive evidence (bounded, ~100 items by default, to
keep runtime predictable). A distance threshold, not a fixed K — the number
of interests falls out of the evidence.

Fallbacks are specified, not emergent, because the degenerate cases are the
common ones for new users:

- 0 positive items → no inferred semantic profile at all;
- 1-2 items → use the individual books as query vectors;
- coherent evidence → a single cluster is a valid, correct answer;
- only noise/singletons → fall back to the strongest individual books or
  one global weighted centroid rather than fabricating cluster structure.

Each valid cluster keeps a normalized weighted centroid (the default
retrieval query) *and* a medoid — the real interacted book closest to the
cluster's center. Centroid-vs-medoid retrieval stays configurable so the
choice can be settled by offline comparison rather than assertion. Cluster
weight derives from evidence strength and recency, not member count alone,
so ten lukewarm saves do not outrank three loved books.

**Human inspectability is a required feature, not a debug affordance.**
Every cluster exposes a deterministic, non-vector summary: interest ID
within the profile version, a deterministic label, weight, member count,
representative/medoid book, member books, top cleaned tags/terms, top
genres, and an evidence summary. Labels are built from cleaned tags/genres
and the representative book (e.g. `Interest around "The Left Hand of
Darkness"`) — deterministic and non-LLM in V1, so the same profile always
produces the same label and a diff between two profile versions means
something.

A developer command (`make inspect-recommender-profile USERNAME=<name>`,
with JSON output) renders this. It **must call the same `InterestProfiler`
the live pipeline calls.** A separate debug clustering implementation would
inspect something other than what serves users, which is worse than no
inspection tool at all.

Raw high-dimensional vectors are never printed or exposed by default.

## Alternatives considered

- **One global user centroid** — rejected, see Context. Simple, and wrong
  for exactly the multi-interest readers this product is for.
- **Fixed-K clustering (k-means with K=5, or similar)** — rejected. K is a
  property of the person. K-means additionally requires a K to be chosen
  before seeing the evidence and produces non-deterministic results
  depending on initialization, which breaks the determinism this design
  needs for inspectability.
- **Shelves only, no inference** — rejected. Ignores every positive signal
  outside a shelf, and readers who never build shelves would get no
  semantic profile at all.
- **Inference only, ignoring shelves** — rejected. Discards the highest
  quality signal available: a boundary the reader drew themselves.
- **LLM-generated cluster labels** — rejected for V1. Non-deterministic,
  adds a runtime/build dependency on an external model, and makes label
  diffs meaningless. The deterministic label is auditable; that is worth
  more than fluency here.
- **Persisting the full cluster object on every recommendation result row**
  — rejected. Compact profile summaries belong at request level or in
  feature-flagged diagnostics, not duplicated across 60 rows per batch.

## Consequences

- Home retrieval issues multiple query vectors per user (one per interest,
  one per shelf profile). These batch into a single matrix multiply against
  the catalog rather than a loop, or the latency budget in
  `RECOMMENDER_SPECIFICATION.md` §24 will not hold.
- Interest IDs are stable only within a profile version. They are not
  durable identifiers and must never be persisted as if they were.
- Clustering must be deterministic for fixed inputs and configuration —
  this is testable, and it is what makes the inspection command meaningful.
- A reader with sparse evidence legitimately has no inferred interests.
  Downstream surfaces must treat that as a normal state served by shelf
  profiles and popularity, not as an error.
