# ADR-0023: The candidate-generator contract, and what a generator is not allowed to decide

## Status

Accepted (Recommender Phase R6). Implements rec-spec §16 and supplies the
five ranked lists ADR-0017 fuses. Consumes the artifacts of ADR-0014,
ADR-0018 and ADR-0021, and the semantic profile of ADR-0016.

## Context

R6 introduces the layer where five very different retrieval mechanisms —
a folded-in latent factor, a precomputed neighbour row, a cosine search, a
graph edge list and a static ranking — have to become five comparable
objects. Three questions had to be answered before any of them was written,
and answering them differently in five places is the failure mode.

**What does "empty" mean?** A generator returning nothing can mean its
artifact is missing, the reader has no evidence, it does not run on this
surface at all, or it ran and matched nothing eligible. rec-spec §27
requires these degrade differently, and the first is an operational alarm
while the third is correct behaviour.

**Who decides how much a generator matters?** rec-spec §17 is explicit that
generator quotas and RRF weights are surface configuration. But a generator
still needs its own knobs — how deep to read a neighbour list, how many
seeds to consider — and the boundary between the two is easy to blur in a
way that would scatter surface policy across five files.

**How do several queries become one list?** The semantic generator is the
only one that issues more than one query, because ADR-0016 refuses to
collapse a reader into a single centroid. Those per-interest result lists
have to merge, and the obvious merge is wrong.

## Decision

### A structural protocol with an explicit status taxonomy

`CandidateGenerator` is a `Protocol` with `generator_id` and `generate`,
matching the package's existing engine/provider style. Every call returns a
`GeneratorResult` carrying a `GeneratorStatus` from a closed set:
`OK`, `NO_ARTIFACT`, `NO_EVIDENCE`, `NOT_APPLICABLE`, `EMPTY`, `FAILED`.

The taxonomy is the decision, not the protocol. "ALS artifact absent" and
"this reader is cold" both produce zero candidates and mean opposite
things — one needs a rebuild, the other is the cold-start path working.
Collapsing them into an empty list would make rec-spec §27's degradation
requirements unobservable in production.

### Rank is assigned in exactly one place, and it is 1-based and dense

`rank_all` applies exclusions, drops within-generator duplicates and
numbers what survives. ADR-0017 fuses with `weight / (rrf_k + rank)`, so a
0-based rank, a gap left by an excluded book, or a book appearing at two
ranks each silently rescale that book's fused score. Five independent
implementations of that arithmetic would eventually disagree; one cannot.

Input order is trusted and never re-sorted — every caller has already
ordered deterministically, and a generator's own ordering is a decision it
is entitled to make.

### Generators own retrieval knobs; surfaces own quotas and weights

`GeneratorConfig` holds only what a generator needs regardless of who asked:
seed cap, neighbour depth, semantic query cap and score floor. **How many
candidates to return arrives per request**, from the caller. Per-surface
quotas and RRF weights are not represented in this package yet at all —
they are R7's `SurfaceConfig`, and inventing a placeholder for them here
would have created a contract before anything could honour it.

The one place a generator does encode surface knowledge is applicability:
`AlsCandidateGenerator` returns `NOT_APPLICABLE` on Similar Books. That is
not a tuning weight that belongs in configuration — rec-spec §20.3 says
global personalization is absent from that surface, and expressing "absent"
as a weight of zero would leave a generator that still folds in a user
factor, still scores 92k items, and still could be re-enabled by a config
edit that nobody would recognise as changing what Similar Books means.

### Seed selection is shared, not per generator

ALS, item-CF and source-similarity all answer "which books does this
request retrieve from, and how much does each count?", and rec-spec §20
gives each surface a different answer — the reader's evidence on Home, the
target shelf's books on Shelf, the source book alone on Similar. That lives
in one `collect_seeds`, so the three cannot drift into three subtly
different notions of "seed" whose provenance is then incomparable at fusion.

Combination policy is **max-dominant**: a book both saved and rated 10/10
counts once, at its strongest weight. rec-spec §7.1 asks for "a deliberate
combination policy" against "uncontrolled double-counting", and this matches
what ADR-0016 already chose for the semantic profile.

`CollaborativeSignalWeights` is separate from R5's `SignalWeights` because
rec-spec §7.1 gives the CF columns their own values, and they differ
decisively in one row: an open is worth 0.0 to long-term CF and a low
positive to the semantic profile.

### The semantic generator interleaves its queries; it does not merge by score

One query per inferred interest and per shelf profile, batched into a single
matrix multiply (rec-spec §24), then merged **round-robin** — every query
contributes its best result before any query contributes its second.

Merging by raw cosine score instead would let the single tightest cluster
take every slot. A reader with a dense Dune shelf and a sparse poetry shelf
would receive Dune, which defeats the entire reason ADR-0016 infers multiple
interests. The consequence is deliberate and worth stating plainly: **the
semantic generator's `score` is not monotonically decreasing down its own
list**, because rank is interleave position. RRF consumes rank, so this is
invisible downstream; anything that later sorts semantic candidates by score
would be re-introducing the bug.

A book several queries reach keeps its best rank and records the others, so
agreement between interests survives into fusion rather than being
flattened.

## Alternatives considered

- **An abstract base class** — rejected. Structural typing keeps a test
  double to two members and stops a generator inheriting behaviour it did
  not ask for, matching how engines and providers already work here.
- **A boolean `supports(surface)` method** — rejected in favour of
  `NOT_APPLICABLE`. A generator that reports *why* it declined produces a
  diagnostic; one that is merely skipped by the caller produces silence.
- **Per-surface weights inside each generator** — rejected; rec-spec §17
  forbids it, and it is the specific thing that would make tuning a hunt
  through five files.
- **Score-normalizing across queries in the semantic generator** — rejected
  for the same reason ADR-0017 rejected it across generators: it requires a
  distributional assumption the queries do not share.
- **Letting the semantic generator build its own profile** — rejected. The
  profile is per-request derived state and depends on application signal
  policy; building it inside the generator would put a second clustering
  path next to ADR-0016's, which rec-spec §13 explicitly forbids.

## Consequences

- **Serving is unchanged.** R6 adds a layer nothing calls yet: `wiring.py`
  holds zero references to any generator. Fusion is R7 and the serving
  switch is R8, so the reader-visible behaviour after R6 is identical.
- **Exclusions are applied twice on four of the five generators** — once in
  the artifact retrieval path (before top-K, so a heavily-excluded reader
  still gets a full page) and again in `rank_all`. That redundancy is
  deliberate: the first is a correctness-of-page-size concern, the second is
  the contract. A sabotage of `rank_all`'s filter fails only the popularity
  test, which is the honest shape of the guarantee.
- **Tie groups are large, and rank is all RRF sees.** On the live artifacts
  a single rank-0 source edge from a shelf save is worth exactly 3.0, and
  10.4% of the 7.6M item-CF edges have a similarity of exactly 1.0. Within
  such a group the ordering is whatever the tiebreak says. The
  source-similarity generator therefore breaks ties by *how many seeds
  agreed* before falling back to `book_id`; item-CF's aggregation is R4's
  and still breaks on `book_id` alone. This is the main quality risk R6
  hands to R7 (risks #111, #112).
- The `FAILED` status exists but nothing sets it yet. Isolating a raising
  generator is the pipeline's job (R8), and the status is defined here so
  that phase does not have to widen the contract.
